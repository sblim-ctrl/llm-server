"""BudgetPlanner 단위 테스트 — 순수 함수 + 목 모드 generate 노드 (DB 무접촉)."""

from datetime import date

import pytest
from pydantic import ValidationError

import app.graphs.writers.budget_planner as bp
from app.graphs.writers.budget_planner import (
    ProposalText,
    _mock_proposal_text,
    _period_bounds,
    generate_proposal,
    verify_proposal_pure,
)
from app.schemas.proposals import ProposalBudgetRequest
from app.tools.burn_rate_forecast import forecast

EXPENSES = [
    {"category": "식비", "amount": 45_000},  # 45% → over
    {"category": "대관", "amount": 30_000},
    {"category": "도서", "amount": 22_500},
    {"category": "다과", "amount": 2_500},  # 2.5% → under
]


def _forecast():
    return forecast(
        total_budget=100_000,
        spent=60_000,
        expenses=EXPENSES,
        as_of="2026-06-11",
        period_end="2026-06-30",
    )


def test_period_bounds_current_month():
    assert _period_bounds(None, date(2026, 7, 19)) == ("2026-07-19", "2026-07-31")


def test_period_bounds_past_month_clamps_to_end():
    # 지난달 지정 → 기간 전체 경과로 간주 (as_of = 기간 말)
    assert _period_bounds("2026-06", date(2026, 7, 19)) == ("2026-06-30", "2026-06-30")


def test_period_bounds_future_month_clamps_to_start():
    assert _period_bounds("2026-08", date(2026, 7, 19)) == ("2026-08-01", "2026-08-31")


def test_mock_text_passes_verification():
    f = _forecast()
    text = _mock_proposal_text(f)
    assert verify_proposal_pure(text, f)


def test_mock_text_separates_total_and_share_sentences():
    # 총액 기준 수치는 rationale에만, 카테고리 비중 권고는 adjustments에만 (B-2 규칙)
    f = _forecast()
    text = _mock_proposal_text(f)
    for adj in text.adjustments:
        assert f"{f.total_budget:,}" not in adj
        assert f"{f.spent:,}" not in adj


def test_verify_fails_on_number_mismatch():
    f = _forecast()
    text = ProposalText(
        adjustments=["'식비' 재배분", "'다과' 재배분"],
        rationale="총예산 999,999원 기준 제안입니다.",
    )
    assert not verify_proposal_pure(text, f)


async def test_generate_proposal_mock_meta():
    f = _forecast()
    out = await generate_proposal({"forecast": f})
    assert out["proposal_text"].adjustments
    meta = out["llm_meta"]["budget_planner"]
    assert meta.mock is True
    assert meta.model == "gpt-4o-mini"  # models.yaml budget_planner 라우팅


def test_period_format_validation():
    # 유효값은 통과, 형식이 다르면 즉시 422 거부 (조기 검증 — 리뷰 발견)
    ProposalBudgetRequest(team_id="t", period="2026-06")
    ProposalBudgetRequest(team_id="t", period=None)
    for bad in ("2026-6", "June", "2026-13", "2026/06"):
        with pytest.raises(ValidationError):
            ProposalBudgetRequest(team_id="t", period=bad)


async def test_save_skips_persistence_when_not_verified(monkeypatch):
    """검증 실패 시 save_proposal이 호출되지 않아야 한다 — 환각 수치 차단의 마지막 방어선."""
    calls = []

    async def fake_save_proposal(team_id, proposal_type, payload):
        calls.append((team_id, proposal_type, payload))
        return "should-not-be-reached"

    monkeypatch.setattr(bp, "save_proposal", fake_save_proposal)
    f = _forecast()
    state = {
        "request": ProposalBudgetRequest(team_id="t"),
        "proposal_text": _mock_proposal_text(f),
        "forecast": f,
        "verified": False,
    }
    out = await bp.save(state)
    assert out["proposal_id"] is None
    assert calls == []


async def test_save_persists_when_verified(monkeypatch):
    calls = []

    async def fake_save_proposal(team_id, proposal_type, payload):
        calls.append((team_id, proposal_type, payload))
        return "pid-123"

    monkeypatch.setattr(bp, "save_proposal", fake_save_proposal)
    f = _forecast()
    state = {
        "request": ProposalBudgetRequest(team_id="t"),
        "proposal_text": _mock_proposal_text(f),
        "forecast": f,
        "verified": True,
    }
    out = await bp.save(state)
    assert out["proposal_id"] == "pid-123"
    assert len(calls) == 1
    assert calls[0][0] == "t"
    assert calls[0][1] == "budget"
