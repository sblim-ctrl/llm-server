"""DigestWriter — "AI 총무" 주간 브리핑 (§4.4-c, A-4).

한 주간의 자동 처리 현황(승인/반려/에스컬레이션) + 주간 지출 + 예산 소진 전망
(BurnForecast — 개발자 B의 B-2 재사용, C8 계약) + 이상 징후를 브리핑으로 만든다.

패턴: 수집 → 결정적 집계(순수) → 생성(LLM은 문구만) → 수치 대조 검증
(Generator-Evaluator, report/briefing/budget_planner와 동일). 수치·이상 징후
탐지는 전부 코드가 계산하고 LLM은 사람이 읽는 문장으로만 바꾼다.

주간 윈도우는 요청 파라미터(week_of)로 받는다 — 목 get_expense_history가 6월
고정 데이터라 "오늘 기준 최근 7일"이면 weekly_spent=0이 되기 때문(테스트·데모
결정성). 데모에선 목 데이터가 있는 주(예: 2026-06-22 주)를 지정한다.

B-2 규칙 준수: daily_burn·소진일은 budget.spent(총액) 기준, 카테고리 비중은
expenses 기준 — 두 수치를 한 문장에 섞지 않는다.
"""

import asyncio
import calendar
import logging
import re
from datetime import date, timedelta

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.db.pool import get_pool
# 과장 표현 그물은 dashboard와 **같은 상수를 쓴다** — writer마다 복사해 두면 한쪽만
# 고쳐지는 사고가 난다(2026-08-05에 _MONEY_RE가 정확히 그래서 양쪽 다 결함이었다).
from app.graphs.writers.dashboard import _OVERSTATE_RE
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta
from app.schemas.writers import DigestRequest
from app.tools.backend_client import get_budget_status, get_expense_history
from app.tools.burn_rate_forecast import BurnForecast, forecast

logger = logging.getLogger(__name__)

ANOMALY_SPIKE_FACTOR = 2.0  # 카테고리 주간 지출이 직전 4주 주평균의 2배 초과
ANOMALY_PRIOR_WEEKS = 4
ANOMALY_ESCALATE_RUN = 3  # 에스컬레이션 연속 발생 임계


class DigestFigures(BaseModel):
    """결정적 집계 결과 — 브리핑 텍스트의 수치는 반드시 이 값과 대조·일치해야 함.

    (BurnForecast를 참조하므로 schemas/writers.py가 아닌 여기 정의 —
    writers.py → burn_rate_forecast → report.py → writers.py 순환 import 방지.
    budget_planner.py의 ProposalText 배치와 같은 이유.)
    """

    week_start: str  # 월요일
    week_end: str  # 일요일
    auto_approved: int  # AGENT 승인 (주간 판례 기준)
    auto_rejected: int  # AGENT 반려
    escalated: int  # 관리자 확인으로 넘어간 건
    weekly_spent: int  # 주간 APPROVED 지출 합 (원)
    forecast: BurnForecast  # B-2 재사용 (C8) — 총액 기준 소진 전망
    anomalies: list[str]  # 결정적 규칙으로 탐지한 이상 징후 문장


class DigestText(BaseModel):
    """LLM 산출은 문구만 — 수치 figures는 코드가 붙인다 (digest_writer 프롬프트).

    advice(총무 코멘트): 이상 징후·소진 전망에 근거한 다음 주 권고 — 여기가 LLM이
    실질 가치를 내는 자리다. 단, 새 금액 생성은 금지(수치는 summary 몫)이며
    verify_digest_pure가 advice 속 금액 토큰을 허용 목록과 대조해 강제한다.
    """

    summary: str
    highlights: list[str]
    advice: str


class DigestDoc(BaseModel):
    figures: DigestFigures
    summary: str
    highlights: list[str]
    advice: str = ""          # 총무 코멘트 (기본값은 구버전 호환용)
    verified: bool


class DigestState(TypedDict, total=False):
    request: DigestRequest
    precedents: list[dict]  # 주간 판례 (자동 처리 현황 재료)
    budget: dict  # {total_budget, spent}
    expenses: list[dict]  # APPROVED 전체 이력 (주간·직전 4주 분리는 집계에서)
    figures: DigestFigures
    digest: DigestDoc
    llm_meta: dict[str, LLMCallMeta]  # 작성 노드 하나뿐 — reducer 불요 (B-7 합산용)


def week_bounds(week_of: str) -> tuple[str, str]:
    """week_of가 속한 주의 (월요일, 일요일) — 순수 함수."""
    d = date.fromisoformat(week_of)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


async def _fetch_week_precedents(team_id: int, week_start: str, week_end: str) -> list[dict]:
    # 주간 판례 — briefing.py fetch_precedents 패턴 + created_at 주간 필터 (A-4 명세)
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT decision, decided_by, created_at
               FROM precedents
               WHERE team_id = %s AND active
                 AND created_at >= %s::date AND created_at < %s::date + 1
               ORDER BY created_at""",
                (team_id, week_start, week_end),
            )
        ).fetchall()
    return [dict(r) for r in rows]


async def fetch(state: DigestState) -> dict:
    req = state["request"]
    week_start, week_end = week_bounds(req.week_of)

    # DB·백엔드 3개 조회는 상호 독립 — 동시 실행 (성능)
    precedents, budget, expenses = await asyncio.gather(
        _fetch_week_precedents(req.team_id, week_start, week_end),
        get_budget_status(req.team_id),
        get_expense_history(req.team_id),
    )
    approved = [e for e in expenses if e.get("status") == "APPROVED"]
    return {"precedents": precedents, "budget": budget, "expenses": approved}


def _in_window(d: str, start: str, end: str) -> bool:
    return start <= d <= end


def detect_anomalies_pure(
    precedents: list[dict], expenses: list[dict], week_start: str, week_end: str
) -> list[str]:
    """이상 징후 — 결정적 규칙 2종 (순수 함수, 단위 테스트 대상).

    ① 카테고리 주간 지출이 직전 4주 주평균의 2배 초과 (직전 지출이 있는 카테고리만 —
       신규 카테고리 첫 지출은 급증이 아니라 정보 부족)
    ② 주간 판례에서 에스컬레이션이 3건 연속 발생
    """
    anomalies: list[str] = []

    ws = date.fromisoformat(week_start)
    prior_start = (ws - timedelta(weeks=ANOMALY_PRIOR_WEEKS)).isoformat()
    this_week: dict[str, int] = {}
    prior: dict[str, int] = {}
    for e in expenses:
        cat, amount, d = e["category"], e["amount"], e["date"]
        if _in_window(d, week_start, week_end):
            this_week[cat] = this_week.get(cat, 0) + amount
        elif _in_window(d, prior_start, week_start) and d != week_start:
            prior[cat] = prior.get(cat, 0) + amount
    for cat in sorted(this_week):  # 정렬 — 결정적 순서
        if cat in prior and prior[cat] > 0:
            weekly_avg = prior[cat] / ANOMALY_PRIOR_WEEKS
            if this_week[cat] > ANOMALY_SPIKE_FACTOR * weekly_avg:
                anomalies.append(
                    f"{cat} 주간 지출이 직전 {ANOMALY_PRIOR_WEEKS}주 주평균의 "
                    f"{ANOMALY_SPIKE_FACTOR:g}배를 초과했습니다"
                )

    run = 0
    for p in precedents:  # created_at 순 (fetch가 정렬)
        run = run + 1 if p["decision"] == "escalate" else 0
        if run == ANOMALY_ESCALATE_RUN:
            anomalies.append(f"에스컬레이션이 {ANOMALY_ESCALATE_RUN}건 연속 발생했습니다")
            break

    return anomalies


def aggregate_digest_pure(
    precedents: list[dict], expenses: list[dict], budget: dict, week_of: str
) -> DigestFigures:
    """결정적 집계 — 순수 함수 (단위 테스트 대상). forecast 계산 포함.

    as_of/period_end: week_of가 속한 달을 기간으로 보고(월 단위 — B-2 가정과 동일),
    as_of는 주 종료일을 기간 말로 클램프 (주가 월 경계를 걸치는 경우).
    """
    week_start, week_end = week_bounds(week_of)

    auto_approved = sum(
        1 for p in precedents if p["decided_by"] == "AGENT" and p["decision"] == "approve"
    )
    auto_rejected = sum(
        1 for p in precedents if p["decided_by"] == "AGENT" and p["decision"] == "reject"
    )
    escalated = sum(1 for p in precedents if p["decision"] == "escalate")

    weekly_spent = sum(e["amount"] for e in expenses if _in_window(e["date"], week_start, week_end))

    base = date.fromisoformat(week_of)
    period_end = base.replace(day=calendar.monthrange(base.year, base.month)[1])
    as_of = min(date.fromisoformat(week_end), period_end)
    fc = forecast(
        budget["total_budget"],
        budget["spent"],
        expenses,
        as_of=as_of.isoformat(),
        period_end=period_end.isoformat(),
    )

    return DigestFigures(
        week_start=week_start,
        week_end=week_end,
        auto_approved=auto_approved,
        auto_rejected=auto_rejected,
        escalated=escalated,
        weekly_spent=weekly_spent,
        forecast=fc,
        anomalies=detect_anomalies_pure(precedents, expenses, week_start, week_end),
    )


async def aggregate(state: DigestState) -> dict:
    return {
        "figures": aggregate_digest_pure(
            state["precedents"], state["expenses"], state["budget"], state["request"].week_of
        )
    }


def _mock_advice(f: DigestFigures) -> str:
    """목 모드 총무 코멘트 — 이상 징후·소진 전망 기반 결정적 권고 (금액 숫자 없음)."""
    tips: list[str] = []
    for a in f.anomalies:
        if "주간 지출이" in a:
            cat = a.split(" ")[0]
            tips.append(f"{cat} 지출이 급증했습니다 — 다음 주 관련 일정을 조정하거나 "
                        "사전 협의 후 집행을 권장합니다.")
        elif a.startswith("에스컬레이션"):
            tips.append("에스컬레이션이 연속 발생했습니다 — 회칙에 판단 기준을 보완하면 "
                        "자동 처리율을 높일 수 있습니다.")
    if f.forecast.depletion_date:
        tips.append("현재 속도면 기간 내 잔액 소진이 예상됩니다 — 지출 우선순위 점검을 "
                    "권장합니다.")
    if not tips:
        tips.append("지출 흐름이 안정적입니다 — 현재 기준을 유지하셔도 좋습니다.")
    return " ".join(tips)


def _mock_digest_text(f: DigestFigures) -> DigestText:
    """목 모드 결정적 문구 — verify가 요구하는 수치를 전부 포함해서 생성."""
    fc = f.forecast
    summary = (
        f"{f.week_start}~{f.week_end} 주간 브리핑입니다. 자동 승인 {f.auto_approved}건, "
        f"반려 {f.auto_rejected}건, 관리자 확인 {f.escalated}건을 처리했습니다. "
        f"주간 지출은 {f.weekly_spent:,}원입니다. 현재 속도 유지 시 기간 말 예상 지출은 "
        f"{fc.projected_period_end_spent:,}원입니다."
    )
    if fc.depletion_date:
        summary += f" 잔액은 {fc.depletion_date}에 소진될 것으로 예상됩니다."
    summary += (
        " 이상 징후: " + " / ".join(f.anomalies) if f.anomalies else " 이번 주 특이사항은 없습니다."
    )

    highlights = [
        f"자동 승인 {f.auto_approved}건 · 반려 {f.auto_rejected}건 · 에스컬레이션 {f.escalated}건",
        f"주간 지출 {f.weekly_spent:,}원 · 기간 말 예상 {fc.projected_period_end_spent:,}원",
    ]
    highlights += f.anomalies or ["이상 징후 없음"]
    return DigestText(summary=summary, highlights=highlights, advice=_mock_advice(f))


async def generate_digest(state: DigestState) -> dict:
    f = state["figures"]
    spec = load_prompt("digest_writer")
    result, meta = await chat_structured(
        agent="digest_writer",
        system=spec.system_with_few_shot(),
        user=f.model_dump_json(),  # figures만 전달 — 수치 출처 강제
        schema=DigestText,
        mock_response=_mock_digest_text(f),
        prompt_version=spec.version,
    )
    digest = DigestDoc(
        figures=f, summary=result.summary, highlights=result.highlights,
        advice=result.advice, verified=False,
    )
    return {"digest": digest, "llm_meta": {"digest_writer": meta}}


# 앞의 마이너스 포함 — dashboard와 같은 이유다. allowed_money에 잔액
# (total_budget - spent)이 들어 있어 예산 초과 시 음수 표기가 나온다. 마이너스를
# 빼고 잡으면 허용 목록과 어긋나 advice가 통째로 폐기된다 (2026-08-05 발견).
_MONEY_RE = re.compile(r"-?[\d,]*\d원")


def verify_digest_pure(doc: DigestDoc, f: DigestFigures) -> bool:
    """검증(Evaluator) — 브리핑 속 핵심 수치가 figures와 일치하는지 대조.

    이상 징후는 문장 그대로 강제하지 않고(실모드 LLM이 다듬을 수 있음) 핵심 표지
    (카테고리명·'에스컬레이션')가 본문에 남아 있는지만 본다.

    advice(총무 코멘트)는 LLM의 자유 서술 영역이지만 **금액 토큰은 예외** —
    figures에서 유도된 허용 목록에 없는 '□□원'이 등장하면 환각으로 보고 폐기한다
    (실측에서 LLM이 없는 수치를 지어낸 전례 — 조언은 자유롭게, 돈 얘기는 정확하게).
    """
    body = doc.summary + " " + " ".join(doc.highlights)
    checks = [
        f"승인 {f.auto_approved}건",
        f"반려 {f.auto_rejected}건",
        f"{f.escalated}건",
        f"{f.weekly_spent:,}원",
        f"{f.forecast.projected_period_end_spent:,}원",
    ]
    if f.forecast.depletion_date:
        checks.append(f.forecast.depletion_date)
    # 이상 징후 표지: "X 주간 지출이…" → 카테고리명 X, 에스컬레이션 연속 → '에스컬레이션'
    checks += [a.split(" ")[0] for a in f.anomalies]
    if not (all(v in body for v in checks) and doc.figures == f):
        return False

    if not doc.advice.strip():
        return False                      # 코멘트 누락도 불합격 — 스키마상 필수 산출물
    allowed_money = {
        f"{f.weekly_spent:,}원", f"{f.forecast.projected_period_end_spent:,}원",
        f"{f.forecast.total_budget:,}원", f"{f.forecast.spent:,}원",
        f"{f.forecast.total_budget - f.forecast.spent:,}원",   # 잔액 표현 허용
    }
    if not all(tok in allowed_money for tok in _MONEY_RE.findall(doc.advice)):
        return False

    # 잔액이 남았는데 "다 썼다"고 하는 과장 — dashboard와 같은 그물이다(같은 상수를
    # 쓴다). advice는 자유 서술이라 오히려 이런 표현이 나오기 쉬운 자리인데 검사가
    # 없었다. 잔액이 0 이하면 사실 보고이므로 검사하지 않는다(`> 0` — dashboard와 동일).
    remaining = f.forecast.total_budget - f.forecast.spent
    return not (remaining > 0 and _OVERSTATE_RE.search(doc.advice + " " + doc.summary))


async def verify_digest(state: DigestState) -> dict:
    """검증 실패 시 **집계로 조립한 안전한 브리핑으로 교체**한다 (verified=false는 유지).

    dashboard의 같은 처리와 한 쌍이다. 종전에는 실패해도 AI 문구를 그대로 두고
    verified=false만 내렸는데, 그러면 화면이 비거나 멀쩡한 주에도 '확인 필요'가 달린다.
    2026-08-05에 검증기 결함(음수 잔액)으로 실제로 그 상태가 됐다.

    폴백은 `_mock_digest_text` — 집계값만으로 조립하므로 정의상 검증을 통과한다.
    **verified는 정직하게 false로 남긴다** (백엔드 계약상 "수치 대조 통과 여부"이고,
    폴백을 썼다고 true로 올리면 AI 품질 저하가 영영 안 보인다).
    """
    doc, figures = state["digest"], state["figures"]
    if verify_digest_pure(doc, figures):
        return {"digest": doc.model_copy(update={"verified": True})}

    logger.error(
        "digest 검증 실패 — 집계 기반 문구로 교체(verified=false 유지). 거부된 원문: "
        "summary=%r advice=%r", doc.summary, doc.advice,
    )
    safe = _mock_digest_text(figures)
    fallback = doc.model_copy(update={
        "summary": safe.summary, "highlights": safe.highlights,
        "advice": safe.advice, "verified": False,
    })
    if not verify_digest_pure(fallback, figures):
        # 폴백까지 실패하면 집계 자체가 이상한 것이다 — 조용히 넘기지 않는다.
        logger.critical("폴백 브리핑도 검증 실패 — 집계값 점검 필요: %r", safe.summary)
    return {"digest": fallback}


def build_digest_graph():
    g = StateGraph(DigestState)
    g.add_node("fetch", fetch)
    g.add_node("aggregate", aggregate)
    g.add_node("generate_digest", generate_digest)
    g.add_node("verify_digest", verify_digest)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "aggregate")
    g.add_edge("aggregate", "generate_digest")
    g.add_edge("generate_digest", "verify_digest")
    g.add_edge("verify_digest", END)
    return g.compile()


digest_graph = build_digest_graph()
