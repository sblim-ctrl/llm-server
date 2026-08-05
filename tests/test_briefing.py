"""BriefingWriter 순수 함수 테스트 — 판례 집계·수치 검증."""

from app.graphs.writers.briefing import (
    aggregate_precedents_pure,
    generate_briefing,
    verify_briefing_pure,
)
from app.schemas.writers import BriefingDoc

PRECEDENTS = [
    {
        "expense_summary": "[식비] 회식 — 45,000원",
        "decision": "escalate",
        "decided_by": "AGENT",
        "is_override": False,
        "reason": None,
    },
    {
        "expense_summary": "[식비] 회식 — 45,000원",
        "decision": "reject",
        "decided_by": "ADMIN",
        "is_override": True,
        "reason": "한도 초과",
    },
    {
        "expense_summary": "[도서] 교재 — 32,000원",
        "decision": "approve",
        "decided_by": "AGENT",
        "is_override": False,
        "reason": None,
    },
]


def test_aggregate_counts():
    f = aggregate_precedents_pure(PRECEDENTS)
    assert f.total_precedents == 3
    assert f.agent_decisions == 2
    assert f.admin_decisions == 1
    assert f.override_count == 1
    assert f.escalated_count == 1
    assert f.gap_categories == ["식비"]  # 1/3 ≥ 30% 임계값


def test_aggregate_empty():
    f = aggregate_precedents_pure([])
    assert f.total_precedents == 0 and f.gap_categories == []


async def test_generated_briefing_passes_verification():
    f = aggregate_precedents_pure(PRECEDENTS)
    state = await generate_briefing({"figures": f})
    assert verify_briefing_pure(state["briefing"], f) is True
    assert state["llm_meta"]["briefing_writer"].mock is True  # 목 모드 계측 확인 (B-7 재료)


def test_verification_detects_figure_mismatch():
    f = aggregate_precedents_pure(PRECEDENTS)
    bad = BriefingDoc(figures=f, summary="누적 판정 999건", handover_notes=[], verified=False)
    assert verify_briefing_pure(bad, f) is False
