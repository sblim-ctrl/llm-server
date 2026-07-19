"""BudgetPlanner 단위 테스트 — 순수 함수 + 목 모드 generate 노드 (DB 무접촉)."""

from datetime import date

from app.graphs.writers.budget_planner import (
    ProposalText,
    _mock_proposal_text,
    _period_bounds,
    generate_proposal,
    verify_proposal_pure,
)
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
