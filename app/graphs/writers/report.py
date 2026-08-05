"""ReportWriter + 예산 추천 — 정산 리포트 AI 요약 (REQ-019, §4.4-c).

패턴: 수집 → 결정적 집계 → 생성(요약) → 검증(수치 대조, 강의 12-03
Generator-Evaluator). 집계 수치는 코드가 계산하고 LLM은 해석만 —
생성 결과의 figures가 집계와 다르면 verified=false로 강등(환각 수치 차단).

'다음번 예산 활용 추천'은 이 리포트의 recommendations 섹션으로 제공한다:
사용률 편중·저활용 카테고리를 규칙 기반으로 감지한다(_recommendations). LLM은
summary 문단만 쓴다 — recommendations는 골든셋이 정확한 문구를 대조하므로
결정성 유지를 위해 LLM 개입 없이 규칙 기반 그대로 둔다(digest.py의 anomalies와
동일한 분리 원칙).
"""

import logging

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta
from app.schemas.writers import BudgetReport, CategoryStat, ReportFigures, ReportRequest
from app.tools.backend_client import get_expense_history

logger = logging.getLogger(__name__)

HIGH_SHARE = 0.4  # 한 카테고리가 전체의 40% 이상이면 편중 경고
LOW_SHARE = 0.05  # 5% 미만이면 저활용 → 재배분 후보


class ReportText(BaseModel):
    """LLM 산출은 summary만 — recommendations는 규칙 기반 그대로, figures는 코드가
    붙인다 (report_writer/v1.yaml)."""

    summary: str


class ReportState(TypedDict, total=False):
    request: ReportRequest
    expenses: list[dict]
    figures: ReportFigures
    report: BudgetReport
    llm_meta: dict[str, LLMCallMeta]  # 작성 노드가 하나뿐 — reducer 불요 (B-7 합산용)


async def fetch_expenses(state: ReportState) -> dict:
    req = state["request"]
    expenses = await get_expense_history(req.team_id, period=req.period)
    approved = [e for e in expenses if e.get("status") == "APPROVED"]
    return {"expenses": approved}


def aggregate_pure(period: str, expenses: list[dict]) -> ReportFigures:
    """결정적 집계 — 순수 함수 (단위 테스트 대상). 수치 계산은 LLM에 맡기지 않는다."""
    total = sum(e["amount"] for e in expenses)
    by_cat: dict[str, dict] = {}
    for e in expenses:
        s = by_cat.setdefault(e["category"], {"spent": 0, "count": 0})
        s["spent"] += e["amount"]
        s["count"] += 1
    stats = [
        CategoryStat(
            category=c,
            spent=s["spent"],
            count=s["count"],
            share=(s["spent"] / total) if total else 0.0,
        )
        for c, s in sorted(by_cat.items(), key=lambda kv: -kv[1]["spent"])
    ]
    top = max(expenses, key=lambda e: e["amount"], default={"title": "-", "amount": 0})
    return ReportFigures(
        period=period,
        total_spent=total,
        expense_count=len(expenses),
        by_category=stats,
        top_expense_title=top["title"],
        top_expense_amount=top["amount"],
    )


async def aggregate(state: ReportState) -> dict:
    return {"figures": aggregate_pure(state["request"].period, state["expenses"])}


def _recommendations(figures: ReportFigures) -> list[str]:
    recs: list[str] = []
    for cat in figures.by_category:
        if cat.share >= HIGH_SHARE:
            recs.append(
                f"'{cat.category}' 지출이 전체의 {cat.share:.0%}로 편중 — 다음 달 한도 상향을 검토하거나 "
                f"회당 상한을 정해 분산하는 것을 권장합니다."
            )
        elif cat.share <= LOW_SHARE and cat.spent > 0:
            recs.append(
                f"'{cat.category}'는 사용률이 낮습니다({cat.share:.0%}) — 예산 일부를 수요가 큰 카테고리로 "
                f"재배분할 수 있습니다."
            )
    if figures.top_expense_amount > 0:
        recs.append(
            f"최대 단건 지출은 '{figures.top_expense_title}' {figures.top_expense_amount:,}원 — "
            f"유사 건은 사전 공유 후 집행하면 심사 지연을 줄일 수 있습니다."
        )
    return recs or ["지출 패턴에 특이사항이 없습니다. 현재 배분을 유지하세요."]


def _mock_report_text(f: ReportFigures) -> ReportText:
    """목 모드 결정적 문구 — 기존 하드코딩 문장과 동일 (verify가 요구하는 수치 전부 포함)."""
    cat_line = ", ".join(f"{c.category} {c.spent:,}원({c.share:.0%})" for c in f.by_category)
    summary = (
        f"{f.period} 총 지출 {f.total_spent:,}원 ({f.expense_count}건). 카테고리별: {cat_line}."
    )
    return ReportText(summary=summary)


async def generate_report(state: ReportState) -> dict:
    """요약 생성 — gpt-4o-mini가 summary 문구를 쓰되 수치는 figures에서만 인용
    (프롬프트 강제) + verify가 대조. recommendations는 규칙 기반 그대로 유지."""
    f = state["figures"]
    spec = load_prompt("report_writer")
    result, meta = await chat_structured(
        agent="report_writer",
        system=spec.system_with_few_shot(),
        user=f.model_dump_json(),  # figures만 전달 — 수치 출처 강제
        schema=ReportText,
        mock_response=_mock_report_text(f),
        prompt_version=spec.version,
    )
    report = BudgetReport(
        figures=f, summary=result.summary, recommendations=_recommendations(f), verified=False
    )
    return {"report": report, "llm_meta": {"report_writer": meta}}


def verify_report_pure(report: BudgetReport, figures: ReportFigures) -> bool:
    """검증(Evaluator) — 요약 텍스트의 핵심 수치가 집계와 일치하는지 프로그램적 대조."""
    text = report.summary
    checks = [f"{figures.total_spent:,}", str(figures.expense_count)]
    checks += [f"{c.spent:,}" for c in figures.by_category]
    return all(v in text for v in checks) and report.figures == figures


async def verify_report(state: ReportState) -> dict:
    report = state["report"]
    ok = verify_report_pure(report, state["figures"])
    if not ok:
        # 수치 불일치 → 요약은 신뢰 불가로 강등, 결정적 figures만 사용하도록 표시
        logger.error("report verification failed — 수치 불일치, verified=false로 강등")
    return {"report": report.model_copy(update={"verified": ok})}


def build_report_graph():
    g = StateGraph(ReportState)
    g.add_node("fetch_expenses", fetch_expenses)
    g.add_node("aggregate", aggregate)
    g.add_node("generate_report", generate_report)
    g.add_node("verify_report", verify_report)
    g.add_edge(START, "fetch_expenses")
    g.add_edge("fetch_expenses", "aggregate")
    g.add_edge("aggregate", "generate_report")
    g.add_edge("generate_report", "verify_report")
    g.add_edge("verify_report", END)
    return g.compile()


report_graph = build_report_graph()
