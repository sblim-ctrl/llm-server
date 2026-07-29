"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""

from app.graphs.writers.policy_draft import (
    MAX_EXTRA_RULES,
    _mock_extra_rules,
    generate_draft,
    load_template,
    load_templates,
    verify_draft_pure,
)
from app.graphs.writers.report import aggregate_pure, generate_report, verify_report_pure
from app.schemas.writers import (
    BudgetReport,
    PolicyDraft,
    PolicyDraftRequest,
    PolicyParamsSuggestion,
)

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
        policy_params=PolicyParamsSuggestion(
            auto_approve_limit=auto, force_escalation_amount=force
        ),
    )


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


# ── generate_draft: description 기반 맞춤 조항 (목 모드) ─


def test_no_description_adds_no_extra_rules():
    assert _mock_extra_rules("") == []


def test_hiking_description_adds_safety_rule():
    rules = _mock_extra_rules("매주 등산을 가는 모임입니다")
    assert len(rules) == 1
    assert "안전장비" in rules[0]


def test_multiple_keywords_still_capped_at_max():
    text = "등산도 하고 개발 스터디도 하고 신입 모집도 하는 모임"
    rules = _mock_extra_rules(text)
    assert len(rules) <= MAX_EXTRA_RULES


async def test_generate_draft_appends_extra_rules_without_touching_base():
    req = PolicyDraftRequest(
        team_type="동호회",
        team_name="주말 등산 모임",
        initial_budget=500_000,
        description="매주 등산을 가는 모임입니다",
    )
    state = await load_template({"request": req})
    result = await generate_draft({"request": req, "template": state["template"]})
    draft = result["draft"]
    base_count = len(load_templates()["동호회"]["base_rules"])
    assert len(draft.rules) == base_count + 1  # 기본 6개 + 추가 1개
    assert "안전장비" in draft.rules[-1]
    assert verify_draft_pure(draft) is None  # placeholder 없이 정상 치환


async def test_generate_draft_without_description_matches_old_behavior():
    req = PolicyDraftRequest(team_type="회사", team_name="테스트팀", initial_budget=1_000_000)
    state = await load_template({"request": req})
    result = await generate_draft({"request": req, "template": state["template"]})
    draft = result["draft"]
    assert len(draft.rules) == len(load_templates()["회사"]["base_rules"])


# ── 마법사 2단계 구간표 · 1단계 회비 ──────────────────────


async def _draft_for(**kwargs):
    req = PolicyDraftRequest(**kwargs)
    state = await load_template({"request": req})
    return (await generate_draft({"request": req, "template": state["template"]}))["draft"]


async def test_thresholds_match_wizard_step2_table():
    """마법사 2단계 구간표(소액 5만 미만 / 중간 5~20만 / 고액 20만 이상)와 일치."""
    draft = await _draft_for(
        team_type="동아리/학생회", team_name="코딩 동아리", initial_budget=1_000_000
    )
    assert draft.policy_params.auto_approve_limit == 50_000
    assert draft.policy_params.force_escalation_amount == 200_000


async def test_dues_adds_one_rule_and_appears_in_notes():
    base = len(load_templates()["스터디"]["base_rules"])
    draft = await _draft_for(
        team_type="스터디", team_name="알고리즘 스터디", initial_budget=600_000, dues=20_000
    )
    assert len(draft.rules) == base + 1
    assert "20,000원" in draft.rules[-1]
    assert "회비 20,000원" in draft.notes
    assert verify_draft_pure(draft) is None


async def test_no_dues_adds_no_rule():
    """화면의 '없음' 체크 — None·0 둘 다 조항을 만들지 않는다."""
    base = len(load_templates()["스터디"]["base_rules"])
    for dues in (None, 0):
        draft = await _draft_for(
            team_type="스터디", team_name="알고리즘 스터디", initial_budget=600_000, dues=dues
        )
        assert len(draft.rules) == base
        assert "회비" not in draft.notes


# ── ReportWriter ─────────────────────────────────────────

EXPENSES = [
    {"title": "회식", "amount": 80_000, "category": "식비", "date": "2026-06-05"},
    {"title": "교재", "amount": 20_000, "category": "도서", "date": "2026-06-10"},
]


def test_aggregate_math():
    f = aggregate_pure("2026-06", EXPENSES)
    assert f.total_spent == 100_000
    assert f.expense_count == 2
    assert f.by_category[0].category == "식비"  # 지출 큰 순 정렬
    assert f.by_category[0].share == 0.8
    assert f.top_expense_title == "회식"


def test_aggregate_empty():
    f = aggregate_pure("2026-06", [])
    assert f.total_spent == 0 and f.expense_count == 0 and f.by_category == []


def test_report_verification_detects_figure_mismatch():
    f = aggregate_pure("2026-06", EXPENSES)
    bad = BudgetReport(figures=f, summary="총 지출 999,999원", recommendations=[], verified=False)
    assert verify_report_pure(bad, f) is False


def test_report_verification_passes_when_figures_match():
    f = aggregate_pure("2026-06", EXPENSES)
    text = f"총 지출 {f.total_spent:,}원 (2건). 식비 {80_000:,}원, 도서 {20_000:,}원"
    good = BudgetReport(figures=f, summary=text, recommendations=[], verified=False)
    assert verify_report_pure(good, f) is True


async def test_generated_report_passes_verification():
    f = aggregate_pure("2026-06", EXPENSES)
    state = await generate_report({"figures": f})
    assert verify_report_pure(state["report"], f) is True
    assert state["llm_meta"]["report_writer"].mock is True  # 목 모드 계측 확인 (B-7 재료)
