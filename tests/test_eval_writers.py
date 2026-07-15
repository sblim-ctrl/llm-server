"""라이터 골든셋 평가기 테스트 — expect 대조 규칙 + 목 이력 규약."""
from app.eval_writers import evaluate_expectations
from app.graphs.writers.report import HIGH_SHARE, LOW_SHARE, aggregate_pure
from app.tools.backend_client import get_expense_history

ACTUAL = {
    "verified": True,
    "rules_count": 6,
    "rules_text": "제1조 영수증 첨부\n안전장비 구입은 우선 인정한다.",
}


def test_equality_check_passes_and_fails():
    assert evaluate_expectations({"rules_count": 6}, ACTUAL) == []
    fails = evaluate_expectations({"rules_count": 5}, ACTUAL)
    assert len(fails) == 1 and "rules_count" in fails[0]


def test_contain_checks_text_field():
    assert evaluate_expectations({"rules_contain": ["안전장비"]}, ACTUAL) == []
    fails = evaluate_expectations({"rules_contain": ["홍보물"]}, ACTUAL)
    assert len(fails) == 1 and "홍보물" in fails[0]


def test_not_contain_flags_forbidden_substring():
    fails = evaluate_expectations({"rules_not_contain": ["안전장비"]}, ACTUAL)
    assert len(fails) == 1
    assert evaluate_expectations({"rules_not_contain": ["{placeholder}"]}, ACTUAL) == []


def test_missing_actual_key_is_a_failure():
    fails = evaluate_expectations({"top_category": "식비"}, ACTUAL)
    assert len(fails) == 1


# ── 목 이력 규약 (골든셋 시나리오의 결정성 기반) ─────────


async def test_noexpense_team_returns_empty_history():
    assert await get_expense_history("eval-writers-report-noexpense") == []


async def test_balanced_team_has_no_share_outliers():
    expenses = await get_expense_history("eval-writers-report-balanced")
    figures = aggregate_pure("2026-06", expenses)
    assert figures.by_category
    for cat in figures.by_category:
        assert LOW_SHARE < cat.share < HIGH_SHARE  # 편중·저활용 어느 쪽도 아님


async def test_default_team_history_unchanged():
    expenses = await get_expense_history("golden-club-1")
    assert len(expenses) == 8  # 기존 규약 보존 — 리포트 기본 시나리오가 의존
