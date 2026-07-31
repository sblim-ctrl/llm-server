"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""

from app.graphs.writers.policy_draft import (
    MAX_EXTRA_RULES,
    _mock_extra_rules,
    generate_draft,
    load_template,
    load_templates,
    verify_draft_pure,
)
from app.graphs.writers.report import aggregate_pure, verify_report_pure
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


def _draft(rules=None, auto=50_000, force=300_000, categories=None, notes=""):
    # 카테고리는 실제 generate_draft가 항상 유형별 6개를 채우므로 기본값도 채워 둔다
    # (빈 목록은 마법사 1단계 칩이 비는 상태라 검증이 잡아야 할 결함이다).
    return PolicyDraft(
        rules=rules if rules is not None else ["제1조 테스트"],
        policy_params=PolicyParamsSuggestion(
            auto_approve_limit=auto, force_escalation_amount=force
        ),
        recommended_categories=(
            categories if categories is not None
            else ["도서", "강의", "다과", "대관", "비품", "기타"]
        ),
        notes=notes,
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


# ── 검증 강화분 (마법사 산출물이 '그럴듯하지만 어긋난' 상태로 나가지 않게) ──


def test_verify_catches_duplicate_rules():
    """문장부호·공백만 다른 사실상 같은 조항도 중복으로 잡는다."""
    err = verify_draft_pure(_draft(rules=["영수증을 첨부한다.", "영수증을 첨부한다"]))
    assert err is not None and "중복" in err


def test_verify_catches_blank_rule():
    err = verify_draft_pure(_draft(rules=["제1조 테스트", "   "]))
    assert err is not None and "빈 조항" in err


def test_verify_catches_empty_categories():
    err = verify_draft_pure(_draft(categories=[]))
    assert err is not None and "카테고리" in err


def test_verify_catches_duplicate_categories():
    err = verify_draft_pure(_draft(categories=["도서", "도서"]))
    assert err is not None and "카테고리" in err


def test_verify_catches_hallucinated_limit_in_rule():
    """LLM 추가 조항이 코드 계산 한도와 다른 금액을 말하면 불통과 — 회칙과 심사 기준이 갈라진다."""
    err = verify_draft_pure(
        _draft(rules=["80,000원 이하의 지출은 AI 자동 심사로 처리한다."], auto=50_000)
    )
    assert err is not None and "불일치" in err


def test_verify_allows_rule_citing_either_suggested_limit():
    """자동승인 한도·강제 에스컬레이션 금액 둘 다 정당한 인용값이다."""
    rules = [
        "50,000원 이하의 지출은 AI 자동 심사로 처리한다.",
        "300,000원 이상은 자동 승인 대상에서 제외한다.",
    ]
    assert verify_draft_pure(_draft(rules=rules, auto=50_000, force=300_000)) is None


def test_verify_catches_hallucinated_limit_without_the_word_auto():
    """'자동'이라는 말 없이 관리자 확인으로 기준을 말해도 금액이 어긋나면 잡는다."""
    err = verify_draft_pure(
        _draft(rules=["80,000원을 넘는 지출은 관리자가 확인한다."], auto=50_000)
    )
    assert err is not None and "불일치" in err


def test_verify_ignores_amounts_in_non_auto_rules():
    """자동 심사와 무관한 조항의 금액(식비 한도 등)은 대조 대상이 아니다."""
    rules = ["1인당 식비는 회당 30,000원을 초과할 수 없다."]
    assert verify_draft_pure(_draft(rules=rules, auto=50_000)) is None


def test_verify_catches_dues_rule_without_notes():
    """회비 조항과 notes 표기는 같은 입력에서 나오므로 한쪽만 있으면 조립 버그다."""
    err = verify_draft_pure(_draft(rules=["회비는 1인당 30,000원으로 하며, 그 범위에서 집행한다."]))
    assert err is not None and "회비" in err


def test_verify_allows_dues_free_team_whose_name_contains_dues_word():
    """모임 이름에 '회비'가 들어가도 회비 없는 초안은 통과 — 골든 pd-dues-zero가 잡은 오탐 회귀.

    notes는 모임 이름을 그대로 품기 때문에 '회비' 단어만 보고 판별하면 안 된다.
    """
    notes = "'무회비 동아리' (동아리/학생회) 초기예산 1,000,000원 기준 자동 생성 초안"
    assert verify_draft_pure(_draft(notes=notes)) is None


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
