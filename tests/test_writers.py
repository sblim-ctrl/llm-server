"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""
from app.graphs.writers.policy_draft import load_templates, verify_draft_pure
from app.graphs.writers.report import aggregate_pure, verify_report_pure
from app.schemas.writers import BudgetReport, PolicyDraft, PolicyParamsSuggestion

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]


# ── PolicyDrafter (예산 배분 없음 — 팀 결정 2026-07-09) ──

def test_templates_cover_all_five_team_types():
    templates = load_templates()
    assert set(templates.keys()) == set(TEAM_TYPES)
    for t in templates.values():
        assert t["base_rules"]
        assert 0 < t["auto_approve_ratio"] < 1


def _draft(rules=None, auto=50_000, force=300_000):
    return PolicyDraft(
        rules=rules if rules is not None else ["제1조 테스트"],
        policy_params=PolicyParamsSuggestion(auto_approve_limit=auto,
                                             force_escalation_amount=force))


def test_verify_catches_limit_order_error():
    err = verify_draft_pure(_draft(auto=300_000, force=100_000))
    assert err is not None and "한도" in err


def test_verify_catches_empty_rules():
    assert verify_draft_pure(_draft(rules=[])) is not None


def test_verify_catches_unresolved_placeholder():
    err = verify_draft_pure(_draft(rules=["한도는 {auto_approve_limit}원"]))
    assert err is not None and "placeholder" in err


def test_verify_passes_valid_draft():
    assert verify_draft_pure(_draft()) is None


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
