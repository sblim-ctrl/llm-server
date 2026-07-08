"""BriefingWriter — 인수인계 브리핑 (REQ-043, §4.4-c).

차기 관리자(총무)에게 넘길 운영 요약: 판례 로그 기반으로 ① AI/관리자 결정 분포
② override(AI 추천 뒤집기) 빈도 ③ 자주 문제된 카테고리 ④ 회칙 vs 실운영 갭 후보를
정리한다. 판례는 저장 시점에 이미 PIIMasker로 익명화되어 있다(REQ-042).

패턴: 수집(precedents) → 결정적 집계 → 생성 → 수치 대조 검증 (Generator-Evaluator).
"""
import logging
import re

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.db.pool import get_pool
from app.schemas.writers import BriefingDoc, BriefingFigures, BriefingRequest

logger = logging.getLogger(__name__)

ESCALATE_GAP_THRESHOLD = 0.3   # 특정 카테고리 에스컬레이션 비율이 30% 넘으면 회칙 보완 후보


class BriefingState(TypedDict, total=False):
    request: BriefingRequest
    precedents: list[dict]
    figures: BriefingFigures
    briefing: BriefingDoc


async def fetch_precedents(state: BriefingState) -> dict:
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            """SELECT expense_summary, decision, decided_by, is_override, reason
               FROM precedents
               WHERE team_id = %s AND active
               ORDER BY created_at""",
            (state["request"].team_id,),
        )).fetchall()
    return {"precedents": [dict(r) for r in rows]}


_CATEGORY_RE = re.compile(r"^\[([^\]]+)\]")


def aggregate_precedents_pure(precedents: list[dict]) -> BriefingFigures:
    """결정적 집계 — 순수 함수 (단위 테스트 대상)."""
    total = len(precedents)
    agent_cnt = sum(1 for p in precedents if p["decided_by"] == "AGENT")
    admin_cnt = total - agent_cnt
    override_cnt = sum(1 for p in precedents if p["is_override"])
    escalated = [p for p in precedents if p["decision"] == "escalate"]

    # 판례 요약 포맷 "[카테고리] 제목 — 금액…"에서 카테고리 추출
    esc_by_cat: dict[str, int] = {}
    for p in escalated:
        m = _CATEGORY_RE.match(p["expense_summary"])
        if m:
            esc_by_cat[m.group(1)] = esc_by_cat.get(m.group(1), 0) + 1

    gap_categories = sorted(
        c for c, n in esc_by_cat.items()
        if total and (n / total) >= ESCALATE_GAP_THRESHOLD)

    return BriefingFigures(
        total_precedents=total, agent_decisions=agent_cnt, admin_decisions=admin_cnt,
        override_count=override_cnt, escalated_count=len(escalated),
        gap_categories=gap_categories)


async def aggregate(state: BriefingState) -> dict:
    return {"figures": aggregate_precedents_pure(state["precedents"])}


async def generate_briefing(state: BriefingState) -> dict:
    """브리핑 생성. 목: 결정적 문장. TODO(실키): gpt-4o가 문구 생성 (수치는 figures만 인용)."""
    f = state["figures"]
    summary = (f"누적 판정 {f.total_precedents}건 — AI 자동 {f.agent_decisions}건 / "
               f"관리자 {f.admin_decisions}건, override {f.override_count}건, "
               f"에스컬레이션 {f.escalated_count}건.")

    handover_notes: list[str] = []
    if f.override_count:
        handover_notes.append(
            f"관리자가 AI 추천을 뒤집은 override가 {f.override_count}건 있습니다 — "
            "해당 판례가 이후 유사 건 심사에 자동 반영되고 있으니 기준 변경 시 판례 정리를 먼저 하세요.")
    if f.gap_categories:
        handover_notes.append(
            "에스컬레이션이 잦은 카테고리: " + ", ".join(f.gap_categories)
            + " — 회칙에 명시 기준이 없어 사람 판단으로 넘어오는 경우입니다. 조항 보완을 검토하세요 (회칙 vs 실운영 갭).")
    if not handover_notes:
        handover_notes.append("판례 로그에 특이 패턴이 없습니다. 현행 회칙·정책 파라미터를 유지해도 무리가 없습니다.")

    briefing = BriefingDoc(figures=f, summary=summary,
                           handover_notes=handover_notes, verified=False)
    return {"briefing": briefing}


def verify_briefing_pure(briefing: BriefingDoc, figures: BriefingFigures) -> bool:
    """검증(Evaluator) — 요약 속 수치가 집계와 일치하는지 대조."""
    text = briefing.summary
    checks = [str(figures.total_precedents), str(figures.agent_decisions),
              str(figures.admin_decisions), str(figures.override_count),
              str(figures.escalated_count)]
    return all(v in text for v in checks) and briefing.figures == figures


async def verify_briefing(state: BriefingState) -> dict:
    briefing = state["briefing"]
    ok = verify_briefing_pure(briefing, state["figures"])
    if not ok:
        logger.error("briefing verification failed — 수치 불일치, verified=false로 강등")
    return {"briefing": briefing.model_copy(update={"verified": ok})}


def build_briefing_graph():
    g = StateGraph(BriefingState)
    g.add_node("fetch_precedents", fetch_precedents)
    g.add_node("aggregate", aggregate)
    g.add_node("generate_briefing", generate_briefing)
    g.add_node("verify_briefing", verify_briefing)
    g.add_edge(START, "fetch_precedents")
    g.add_edge("fetch_precedents", "aggregate")
    g.add_edge("aggregate", "generate_briefing")
    g.add_edge("generate_briefing", "verify_briefing")
    g.add_edge("verify_briefing", END)
    return g.compile()


briefing_graph = build_briefing_graph()
