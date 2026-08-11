"""BriefingWriter — 인수인계 브리핑 (REQ-043, §4.4-c).

차기 관리자(총무)에게 넘길 운영 요약: 판례 로그 기반으로 ① AI/관리자 결정 분포
② override(AI 추천 뒤집기) 빈도 ③ 자주 문제된 카테고리 ④ 회칙 vs 실운영 갭 후보를
정리한다. 판례는 저장 시점에 이미 PIIMasker로 익명화되어 있다(REQ-042).

패턴: 수집(precedents) → 결정적 집계 → 생성(summary) → 수치 대조 검증
(Generator-Evaluator). handover_notes는 판례 로직 그대로 결정적으로 생성한다 —
골든셋이 정확한 문구(override·회칙 갭 안내)를 대조하므로 LLM 개입 없이 결정성을
유지한다(report.py의 recommendations와 동일한 분리 원칙).
"""

import logging
import re

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.db.pool import get_pool
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta
from app.schemas.writers import BriefingDoc, BriefingFigures, BriefingRequest

logger = logging.getLogger(__name__)

ESCALATE_GAP_THRESHOLD = 0.3  # 특정 카테고리 에스컬레이션 비율이 30% 넘으면 회칙 보완 후보


class BriefingText(BaseModel):
    """LLM 산출은 summary만 — handover_notes는 판례 로직 그대로, figures는 코드가
    붙인다 (briefing_writer/v1.yaml)."""

    summary: str


class BriefingState(TypedDict, total=False):
    request: BriefingRequest
    precedents: list[dict]
    figures: BriefingFigures
    briefing: BriefingDoc
    llm_meta: dict[str, LLMCallMeta]  # 작성 노드가 하나뿐 — reducer 불요 (B-7 합산용)


async def fetch_precedents(state: BriefingState) -> dict:
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT expense_summary, decision, decided_by, is_override, reason
               FROM precedents
               WHERE team_id = %s AND active
               ORDER BY created_at""",
                (state["request"].team_id,),
            )
        ).fetchall()
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
        c for c, n in esc_by_cat.items() if total and (n / total) >= ESCALATE_GAP_THRESHOLD
    )

    return BriefingFigures(
        total_precedents=total,
        agent_decisions=agent_cnt,
        admin_decisions=admin_cnt,
        override_count=override_cnt,
        escalated_count=len(escalated),
        gap_categories=gap_categories,
    )


async def aggregate(state: BriefingState) -> dict:
    return {"figures": aggregate_precedents_pure(state["precedents"])}


def _mock_briefing_text(f: BriefingFigures) -> BriefingText:
    """목 모드 결정적 문구 — 기존 하드코딩 문장과 동일."""
    summary = (
        f"누적 판정 {f.total_precedents}건 — AI 자동 {f.agent_decisions}건 / "
        f"관리자 {f.admin_decisions}건, AI 추천 번복 {f.override_count}건, "
        f"에스컬레이션 {f.escalated_count}건."
    )
    return BriefingText(summary=summary)


def _handover_notes(f: BriefingFigures) -> list[str]:
    """인수인계 노트 — 판례 로직 기반 결정적 생성 (LLM 미개입)."""
    notes: list[str] = []
    if f.override_count:
        notes.append(
            f"관리자가 AI 추천을 뒤집은 결정이 {f.override_count}건 있습니다 — "
            "해당 판례가 이후 유사 건 심사에 자동 반영되고 있으니 기준 변경 시 판례 정리를 먼저 하세요."
        )
    if f.gap_categories:
        notes.append(
            "에스컬레이션이 잦은 카테고리: "
            + ", ".join(f.gap_categories)
            + " — 회칙에 명시 기준이 없어 사람 판단으로 넘어오는 경우입니다. 조항 보완을 검토하세요 (회칙 vs 실운영 갭)."
        )
    if not notes:
        notes.append(
            "판례 로그에 특이 패턴이 없습니다. 현행 회칙·정책 파라미터를 유지해도 무리가 없습니다."
        )
    return notes


async def generate_briefing(state: BriefingState) -> dict:
    """브리핑 생성 — gpt-4o가 summary 문구를 쓰되 수치는 figures에서만 인용
    (프롬프트 강제) + verify가 대조. handover_notes는 판례 로직 그대로 유지."""
    f = state["figures"]
    spec = load_prompt("briefing_writer")
    result, meta = await chat_structured(
        agent="briefing_writer",
        system=spec.system_with_few_shot(),
        user=f.model_dump_json(),  # figures만 전달 — 수치 출처 강제
        schema=BriefingText,
        mock_response=_mock_briefing_text(f),
        prompt_version=spec.version,
    )
    briefing = BriefingDoc(
        figures=f, summary=result.summary, handover_notes=_handover_notes(f), verified=False
    )
    return {"briefing": briefing, "llm_meta": {"briefing_writer": meta}}


def verify_briefing_pure(briefing: BriefingDoc, figures: BriefingFigures) -> bool:
    """검증(Evaluator) — 요약 속 수치가 집계와 일치하는지 대조."""
    text = briefing.summary
    checks = [
        str(figures.total_precedents),
        str(figures.agent_decisions),
        str(figures.admin_decisions),
        str(figures.override_count),
        str(figures.escalated_count),
    ]
    return all(v in text for v in checks) and briefing.figures == figures


async def verify_briefing(state: BriefingState) -> dict:
    """검증 실패 시 **집계로 조립한 안전한 문장으로 교체**한다 (verified=false는 유지).

    dashboard.py의 verify와 동일한 정책: verified=false는 정직하게 남기되(계약상
    "본문 수치와 집계값의 대조 통과 여부"), summary 본문은 환각 가능성이 있는 원문을
    그대로 두지 않고 _mock_briefing_text(집계값만으로 조립 — 정의상 검증을 통과)로
    교체해 항상 안전한 값이 나가게 한다.
    """
    briefing = state["briefing"]
    ok = verify_briefing_pure(briefing, state["figures"])
    if ok:
        return {"briefing": briefing.model_copy(update={"verified": True})}

    logger.error(
        "briefing verification failed — 수치 불일치, 집계 기반 문장으로 교체(verified=false 유지). "
        "거부된 원문: %r",
        briefing.summary,
    )
    safe = _mock_briefing_text(state["figures"]).summary
    return {"briefing": briefing.model_copy(update={"summary": safe, "verified": False})}


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
