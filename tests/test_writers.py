"""문서 생성 에이전트 순수 함수 테스트 — 배분·검증(Generator-Evaluator)·집계."""
import pytest

from app.graphs.writers.policy_draft import allocate_budget, load_templates, verify_draft_pure
from app.graphs.writers.report import aggregate_pure, verify_report_pure
from app.schemas.writers import (
    BudgetLine, BudgetReport, PolicyDraft, PolicyParamsSuggestion,
)

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]


# ── PolicyDrafter ────────────────────────────────────────

def test_templates_cover_all_five_team_types():
    templates = load_templates()
    assert set(templates.keys()) == set(TEAM_TYPES)
    for t in templates.values():
        assert abs(sum(c["ratio"] for c in t["categories"]) - 1.0) < 1e-9


@pytest.mark.parametrize("total", [500_000, 1_000_000, 333_333, 100_001])
@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_allocation_sums_exactly_to_budget(total, team_type):
    categories = load_templates()[team_type]["categories"]
    lines = allocate_budget(total, categories)
    assert sum(line.amount for line in lines) == total
    assert all(line.amount >= 0 for line in lines)


def _draft(budget_plan, auto=50_000, force=300_000):
    return PolicyDraft(
        rules=["제1조 테스트"], budget_plan=budget_plan,
        policy_params=PolicyParamsSuggestion(auto_approve_limit=auto,
                                             force_escalation_amount=force))


def test_verify_catches_sum_mismatch():
    plan = [BudgetLine(category="식비", amount=90_000, ratio=1.0)]
    assert verify_draft_pure(_draft(plan), initial_budget=100_000) is not None


def test_verify_catches_limit_order_error():
    plan = [BudgetLine(category="식비", amount=100_000, ratio=1.0)]
    err = verify_draft_pure(_draft(plan, auto=300_000, force=100_000), 100_000)
    assert err is not None and "한도" in err


def test_verify_passes_valid_draft():
    plan = [BudgetLine(category="식비", amount=100_000, ratio=1.0)]
    assert verify_draft_pure(_draft(plan), initial_budget=100_000) is None


# ── ReportWriter ─────────────────────────────────────────

EXPENSES = [
    {"title": "회식", "amount": 80_000, "category": "식비", "date": "2026-06-05"},
    {"title": "교재", "amount": 20_000, "category": "도서", "date": "2026-06-10"},
]


def test_aggregate_math():
    f = aggregate_pure("2026-06", EXPENSES)
    assert f.total_spent == 100_000
    assert f.expense_count == 2
    assert f.by_category[0].category == "식비"     # 지출 큰 순 정렬
    assert f.by_category[0].share == 0.8
    assert f.top_expense_title == "회식"


def test_aggregate_empty():
    f = aggregate_pure("2026-06", [])
    assert f.total_spent == 0 and f.expense_count == 0 and f.by_category == []


def test_report_verification_detects_figure_mismatch():
    f = aggregate_pure("2026-06", EXPENSES)
    bad = BudgetReport(figures=f, summary="총 지출 999,999원", recommendations=[],
                       verified=False)
    assert verify_report_pure(bad, f) is False


def test_report_verification_passes_when_figures_match():
    f = aggregate_pure("2026-06", EXPENSES)
    text = f"총 지출 {f.total_spent:,}원 (2건). 식비 {80_000:,}원, 도서 {20_000:,}원"
    good = BudgetReport(figures=f, summary=text, recommendations=[], verified=False)
    assert verify_report_pure(good, f) is True
