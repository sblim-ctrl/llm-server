"""dashboard — 대시보드 AI 요약 (풀스택 협의 2026-08-04 5번).

리포트·브리핑과 같은 **생성기 → 검증기** 구조다. 수치는 결정적 집계에서만 나오고
LLM은 문장만 쓴다. 검증기가 본문의 금액을 집계값에서 유도한 허용 목록과 대조해,
없는 숫자가 나오면 verified=false로 강등한다.

    fetch → aggregate → generate → verify

리포트의 AI 요약을 재활용하지 않은 이유: 리포트는 '기간 정산'이고 대시보드는 '지금
상태'라 말할 거리가 다르다. 리포트는 승인된 지출만 보지만 대시보드는 **승인 대기**도
보여줘야 하고(화면의 '승인이 필요해요'), 전월 대비 추세가 핵심이다.

동기 방식이다 — 202 접수 후 폴링이 아니라 그 자리에서 돌려준다. 페이지 로드 때 뜨는
요약이라 폴링은 화면이 비어 있는 시간을 만든다. `POST /v1/policy-draft`와 같은 결정.
"""
import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.dashboard import (
    CategoryTrend, DashboardFigures, DashboardSummary, DashboardSummaryDoc,
    DashboardSummaryRequest,
)
from app.tools.backend_client import get_budget_status, get_expense_history

logger = logging.getLogger(__name__)

# 승인 대기로 볼 상태값. 백엔드 표기가 확정되면 여기만 고치면 된다
# (풀스택_회신요청 — 지출 상태 ENUM 미확정).
PENDING_STATUSES = {"PENDING", "REQUESTED", "ESCALATED", "AI_ESCALATED"}
APPROVED_STATUS = "APPROVED"


class DashboardState(TypedDict, total=False):
    request: DashboardSummaryRequest
    expenses: list[dict[str, Any]]
    budget: dict[str, Any]
    figures: DashboardFigures
    doc: DashboardSummaryDoc
    llm_meta: dict


# ── 집계 (순수 함수 — 단위 테스트 대상) ────────────────────────────────────

def _prev_period(period: str) -> str:
    year, month = (int(x) for x in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def _in_period(date: str | None, period: str) -> bool:
    return bool(date) and str(date).startswith(period)


def aggregate_dashboard_pure(
    expenses: list[dict[str, Any]], budget: dict[str, Any], period: str
) -> DashboardFigures:
    """지출 이력·예산 → 대시보드 집계. 부수효과 없음.

    승인 지출만 '사용됨'으로 센다. 대기 건은 아직 나간 돈이 아니라서 spent에 넣지
    않고 따로 센다 — 화면도 '사용됨 / 대기 중 / 남은 예산'을 나눠 보여준다.
    """
    prev = _prev_period(period)
    approved = [e for e in expenses if e.get("status") == APPROVED_STATUS]
    this_month = [e for e in approved if _in_period(e.get("date"), period)]
    last_month = [e for e in approved if _in_period(e.get("date"), prev)]

    total_budget = int(budget.get("total_budget", 0))
    spent = sum(int(e.get("amount", 0)) for e in this_month)

    pending = [e for e in expenses
               if str(e.get("status", "")).upper() in PENDING_STATUSES
               and _in_period(e.get("date"), period)]

    def by_category(rows: list[dict[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in rows:
            out[e.get("category") or "기타"] = out.get(e.get("category") or "기타", 0) \
                + int(e.get("amount", 0))
        return out

    now_cat, prev_cat = by_category(this_month), by_category(last_month)
    trends = [
        CategoryTrend(
            category=name,
            spent=amount,
            share=(amount / spent) if spent else 0.0,
            prev_spent=prev_cat.get(name, 0),
            # 전월이 0이면 증가율을 정의할 수 없다. 0으로 두면 '변화 없음'으로 읽혀
            # 신규 카테고리가 묻히므로 null로 둔다.
            change_ratio=((amount - prev_cat[name]) / prev_cat[name]
                          if prev_cat.get(name) else None),
        )
        for name, amount in sorted(now_cat.items(), key=lambda kv: -kv[1])
    ]

    grew = [t for t in trends if t.change_ratio is not None and t.change_ratio > 0]
    largest = max(this_month, key=lambda e: int(e.get("amount", 0)), default=None)

    return DashboardFigures(
        period=period,
        total_budget=total_budget,
        spent=spent,
        remaining=total_budget - spent,
        usage_ratio=(spent / total_budget) if total_budget else 0.0,
        pending_count=len(pending),
        pending_amount=sum(int(e.get("amount", 0)) for e in pending),
        categories=trends,
        top_category=trends[0] if trends else None,
        fastest_growing=max(grew, key=lambda t: t.change_ratio) if grew else None,
        largest_expense_title=(largest or {}).get("title"),
        largest_expense_amount=int((largest or {}).get("amount", 0)),
    )


# ── 노드 ──────────────────────────────────────────────────────────────────

async def fetch(state: DashboardState) -> dict:
    req = state["request"]
    return {
        "expenses": await get_expense_history(req.team_id),
        "budget": await get_budget_status(req.team_id),
    }


async def aggregate(state: DashboardState) -> dict:
    return {"figures": aggregate_dashboard_pure(
        state["expenses"], state["budget"], state["request"].period)}


def _mock_message(f: DashboardFigures) -> DashboardSummary:
    """목 모드 결정적 문장 — 실모드 문장과 같은 수치를 쓰도록 맞춰 둔다."""
    if not f.categories:
        return DashboardSummary(message=(
            f"{f.period}에는 아직 승인된 지출이 없어요. "
            f"총예산 {f.total_budget:,}원이 그대로 남아 있습니다."))

    parts = [f"이번 달 지출은 {f.spent:,}원으로 예산의 {f.usage_ratio:.0%}를 썼어요."]
    if f.top_category:
        parts.append(f"{f.top_category.category}가 {f.top_category.spent:,}원으로"
                     f" 가장 큰 비중이에요.")
    if f.fastest_growing and f.fastest_growing.change_ratio:
        parts.append(f"{f.fastest_growing.category}는 전월 대비"
                     f" {f.fastest_growing.change_ratio:.0%} 늘었습니다.")
    if f.pending_count:
        parts.append(f"승인 대기가 {f.pending_count}건({f.pending_amount:,}원) 있어요.")
    parts.append(f"남은 예산은 {f.remaining:,}원입니다.")
    return DashboardSummary(message=" ".join(parts))


async def generate(state: DashboardState) -> dict:
    f = state["figures"]
    spec = load_prompt("dashboard_writer")
    result, meta = await chat_structured(
        agent="dashboard_writer",
        system=spec.system_with_few_shot(),
        user=f.model_dump_json(),      # figures만 전달 — 수치 출처를 강제한다
        schema=DashboardSummary,
        mock_response=_mock_message(f),
        prompt_version=spec.version,
    )
    return {"doc": DashboardSummaryDoc(figures=f, message=result.message, verified=False),
            "llm_meta": {"dashboard_writer": meta}}


# ── 검증 (순수 함수) ──────────────────────────────────────────────────────

_MONEY_RE = re.compile(r"[\d,]*\d원")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")


def allowed_money(f: DashboardFigures) -> set[str]:
    """본문에 나와도 되는 금액 표기. 집계값에서만 유도한다."""
    values = {f.total_budget, f.spent, f.remaining, f.pending_amount,
              f.largest_expense_amount}
    values |= {c.spent for c in f.categories}
    values |= {c.prev_spent for c in f.categories}
    return {f"{v:,}원" for v in values if v}


def allowed_percent(f: DashboardFigures) -> set[str]:
    """본문에 나와도 되는 백분율. 반올림 자리수가 갈리므로 이웃값까지 허용한다."""
    out: set[str] = set()

    def add(ratio: float | None) -> None:
        if ratio is None:
            return
        pct = abs(ratio) * 100
        for v in {round(pct), int(pct), round(pct, 1)}:
            out.add(f"{v:g}%")

    add(f.usage_ratio)
    for c in f.categories:
        add(c.share)
        add(c.change_ratio)
    return out


def verify_summary_pure(doc: DashboardSummaryDoc) -> bool:
    """요약문의 수치가 집계에서 나온 것인지 대조한다.

    문장 자체는 강제하지 않는다 — 실모드 LLM이 자유롭게 다듬는 영역이다. 다만
    **숫자는 예외**다. 대시보드는 관리자가 예산 판단을 하는 화면이라, 없는 금액이
    적히면 잘못된 결정으로 이어진다.
    """
    if not doc.message.strip():
        return False
    ok_money, ok_pct = allowed_money(doc.figures), allowed_percent(doc.figures)
    if any(tok not in ok_money for tok in _MONEY_RE.findall(doc.message)):
        return False
    return all(tok in ok_pct for tok in _PERCENT_RE.findall(doc.message))


async def verify(state: DashboardState) -> dict:
    doc = state["doc"]
    ok = verify_summary_pure(doc)
    if not ok:
        logger.error("dashboard 요약 검증 실패 — 수치 불일치, verified=false로 강등")
    return {"doc": doc.model_copy(update={"verified": ok})}


def build_dashboard_graph():
    g = StateGraph(DashboardState)
    g.add_node("fetch", fetch)
    g.add_node("aggregate", aggregate)
    g.add_node("generate", generate)
    g.add_node("verify", verify)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "aggregate")
    g.add_edge("aggregate", "generate")
    g.add_edge("generate", "verify")
    g.add_edge("verify", END)
    return g.compile()


dashboard_graph = build_dashboard_graph()
