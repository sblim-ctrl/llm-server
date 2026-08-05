"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.graphs.writers.policy_draft import (
    MAX_EXTRA_RULES,
    _mock_extra_rules,
    generate_draft,
    load_template,
    load_templates,
    policy_draft_graph,
    retrieve_references,
    verify_draft_pure,
)
from app.graphs.writers.report import aggregate_pure, generate_report, verify_report_pure
from app.schemas.writers import (
    BudgetReport,
    PolicyDraft,
    PolicyDraftRequest,
)

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]

# 통합 요청(LLM-005 전면 개정)의 공통 필수 필드 — rule_source는 각 테스트가 정한다
BASE_KW = dict(
    team_id=9001,
    team_type="스터디",
    team_name="알고리즘 스터디",
    initial_budget=500_000,
    force_escalation_amount=50_000,
)


# ── PolicyDrafter (예산 배분·정책 제안 없음 — 2026-07-09·08-05 결정) ──


def test_templates_cover_all_five_team_types():
    templates = load_templates()
    assert set(templates.keys()) == set(TEAM_TYPES)
    for t in templates.values():
        assert t["base_rules"]


def _draft(rules=None, categories=None, notes=""):
    # 카테고리는 실제 generate_draft가 항상 전역 9종을 채우므로 기본값도 채워 둔다
    # (빈 목록은 마법사 1단계 칩이 비는 상태라 검증이 잡아야 할 결함이다).
    return PolicyDraft(
        rules=rules if rules is not None else ["제1조 테스트"],
        recommended_categories=(
            categories
            if categories is not None
            else ["도서", "강의", "다과", "대관", "비품", "기타"]
        ),
        notes=notes,
    )


def _verify(draft, force=300_000, rule_source="ai"):
    return verify_draft_pure(draft, rule_source=rule_source, force_escalation_amount=force)


def test_verify_catches_empty_rules():
    assert _verify(_draft(rules=[])) is not None


def test_verify_catches_unresolved_placeholder():
    err = _verify(_draft(rules=["한도는 {auto_approve_limit}원"]))
    assert err is not None and "placeholder" in err


def test_verify_passes_valid_draft():
    assert _verify(_draft()) is None


# ── 검증 강화분 (마법사 산출물이 '그럴듯하지만 어긋난' 상태로 나가지 않게) ──


def test_verify_catches_duplicate_rules():
    """문장부호·공백만 다른 사실상 같은 조항도 중복으로 잡는다."""
    err = _verify(_draft(rules=["영수증을 첨부한다.", "영수증을 첨부한다"]))
    assert err is not None and "중복" in err


def test_verify_catches_blank_rule():
    err = _verify(_draft(rules=["제1조 테스트", "   "]))
    assert err is not None and "빈 조항" in err


def test_verify_catches_empty_categories():
    err = _verify(_draft(categories=[]))
    assert err is not None and "카테고리" in err


def test_verify_catches_duplicate_categories():
    err = _verify(_draft(categories=["도서", "도서"]))
    assert err is not None and "카테고리" in err


def test_verify_catches_hallucinated_limit_in_rule():
    """LLM 추가 조항이 설정 금액과 다른 금액을 말하면 불통과 — 회칙과 심사 기준이 갈라진다."""
    err = _verify(_draft(rules=["80,000원 이하의 지출은 AI 자동 심사로 처리한다."]), force=50_000)
    assert err is not None and "불일치" in err


def test_verify_allows_rule_citing_the_configured_amount():
    """정당한 인용값은 사용자가 입력한 기준 금액 하나뿐이다."""
    rules = ["50,000원 미만의 지출은 AI 자동 심사로 처리한다."]
    assert _verify(_draft(rules=rules), force=50_000) is None


def test_verify_rejects_rule_citing_the_old_secondary_limit():
    """옛 4배 에스컬레이션 금액은 더 이상 정당한 인용값이 아니다 (배수 계산식 폐기)."""
    err = _verify(_draft(rules=["200,000원 이상은 자동 승인 대상에서 제외한다."]), force=50_000)
    assert err is not None and "불일치" in err


def test_verify_catches_hallucinated_limit_without_the_word_auto():
    """'자동'이라는 말 없이 관리자 확인으로 기준을 말해도 금액이 어긋나면 잡는다."""
    err = _verify(_draft(rules=["80,000원을 넘는 지출은 관리자가 확인한다."]), force=50_000)
    assert err is not None and "불일치" in err


def test_verify_ignores_amounts_in_non_auto_rules():
    """자동 심사와 무관한 조항의 금액(식비 한도 등)은 대조 대상이 아니다."""
    rules = ["1인당 식비는 회당 30,000원을 초과할 수 없다."]
    assert _verify(_draft(rules=rules), force=50_000) is None


def test_verify_catches_dues_rule_without_notes():
    """회비 조항과 notes 표기는 같은 입력에서 나오므로 한쪽만 있으면 조립 버그다."""
    err = _verify(_draft(rules=["회비는 1인당 30,000원으로 하며, 그 범위에서 집행한다."]))
    assert err is not None and "회비" in err


def test_verify_allows_dues_free_team_whose_name_contains_dues_word():
    """모임 이름에 '회비'가 들어가도 회비 없는 초안은 통과 — 골든 pd-dues-zero가 잡은 오탐 회귀.

    notes는 모임 이름을 그대로 품기 때문에 '회비' 단어만 보고 판별하면 안 된다.
    """
    notes = "'무회비 동아리' (동아리/학생회) 초기예산 1,000,000원 기준 자동 생성 초안"
    assert _verify(_draft(notes=notes)) is None


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
        **{**BASE_KW, "team_type": "동호회", "team_name": "주말 등산 모임"},
        rule_source="ai",
        description="매주 등산을 가는 모임입니다",
    )
    state = await load_template({"request": req})
    result = await generate_draft({"request": req, "template": state["template"]})
    draft = result["draft"]
    base_count = len(load_templates()["동호회"]["base_rules"])
    assert len(draft.rules) == base_count + 1  # 기본 6개 + 추가 1개
    assert "안전장비" in draft.rules[-1]
    assert _verify(draft, force=50_000) is None  # placeholder 없이 정상 치환


async def test_generate_draft_without_description_matches_old_behavior():
    req = PolicyDraftRequest(
        **{**BASE_KW, "team_type": "회사", "team_name": "테스트팀", "initial_budget": 1_000_000},
        rule_source="ai",
    )
    state = await load_template({"request": req})
    result = await generate_draft({"request": req, "template": state["template"]})
    draft = result["draft"]
    assert len(draft.rules) == len(load_templates()["회사"]["base_rules"])


# ── 마법사 2단계 기준 금액 · 1단계 회비 ───────────────────


async def _draft_for(**kwargs):
    req = PolicyDraftRequest(**{**BASE_KW, "rule_source": "ai", **kwargs})
    state = await load_template({"request": req})
    return (await generate_draft({"request": req, "template": state["template"]}))["draft"]


async def test_ai_draft_uses_the_requested_amount_in_rules():
    """사용자가 입력한 기준 금액이 그대로 회칙 조항에 들어간다 — 추천 계산은 폐기됐다."""
    draft = await _draft_for(force_escalation_amount=70_000)
    joined = "\n".join(draft.rules)
    assert "70,000원" in joined
    assert "{" not in joined
    assert _verify(draft, force=70_000) is None


async def test_dues_adds_one_rule_and_appears_in_notes():
    base = len(load_templates()["스터디"]["base_rules"])
    draft = await _draft_for(initial_budget=600_000, dues=20_000)
    assert len(draft.rules) == base + 1
    assert "20,000원" in draft.rules[-1]
    assert "회비 20,000원" in draft.notes
    assert _verify(draft, force=50_000) is None


async def test_no_dues_adds_no_rule():
    """화면의 '없음' 체크 — None·0 둘 다 조항을 만들지 않는다."""
    base = len(load_templates()["스터디"]["base_rules"])
    for dues in (None, 0):
        draft = await _draft_for(initial_budget=600_000, dues=dues)
        assert len(draft.rules) == base
        assert "회비" not in draft.notes


# ── LLM-005 통합 요청 계약 (전면 개정 2026-08-05, 개정안 §1) ──


def test_request_requires_new_mandatory_fields():
    for missing in ("team_id", "force_escalation_amount", "rule_source"):
        kw = {**BASE_KW, "rule_source": "ai"}
        kw.pop(missing)
        with pytest.raises(ValidationError):
            PolicyDraftRequest(**kw)


def test_manual_requires_rule_text():
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**BASE_KW, rule_source="manual")
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**BASE_KW, rule_source="manual", rule_text="   ")
    ok = PolicyDraftRequest(**BASE_KW, rule_source="manual", rule_text="제1조 …")
    assert ok.rule_text == "제1조 …"


def test_file_requires_rule_file_ref():
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**BASE_KW, rule_source="file")
    ok = PolicyDraftRequest(**BASE_KW, rule_source="file", rule_file_ref="doc-123")
    assert ok.rule_file_ref == "doc-123"


def test_unknown_rule_source_rejected():
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**BASE_KW, rule_source="번역")


def test_ai_source_tolerates_leftover_rule_text():
    """FE 관용 — 3단계에서 '직접 입력'을 쓰다 'AI 초안'으로 바꾸면 rule_text가 남을 수 있다.

    반대 방향(manual/file에 필요한 필드 누락)만 거절한다 — ai에 남은 값은 무시한다.
    """
    ok = PolicyDraftRequest(**BASE_KW, rule_source="ai", rule_text="남은 입력")
    assert ok.rule_source == "ai"


async def test_non_ai_sources_return_empty_rules_without_llm():
    """file·manual·skip은 초안을 만들지 않는다 — rules 빈 배열, LLM·RAG 미호출.

    dues를 함께 보낸다 — non-ai notes는 회비 조각을 붙이지 않는데, 그 전제가 깨지면
    verify의 회비-notes 정합 검사가 오탐 500을 낸다(회귀 방지).
    """
    extras = {
        "manual": {"rule_text": "제1조 회비는 월 1만원으로 한다."},
        "file": {"rule_file_ref": "doc-1"},
        "skip": {},
    }
    for source, extra in extras.items():
        req = PolicyDraftRequest(
            **BASE_KW,
            rule_source=source,
            dues=20_000,
            description="매주 등산을 가는 모임입니다",
            **extra,
        )
        with (
            patch("app.graphs.writers.policy_draft.chat_structured", AsyncMock()) as llm,
            patch("app.graphs.writers.policy_draft.search_references", AsyncMock()) as rag,
        ):
            state = await load_template({"request": req})
            refs = await retrieve_references({"request": req})
            result = await generate_draft({"request": req, "template": state["template"]})
        draft = result["draft"]
        assert draft.rules == []
        assert len(draft.recommended_categories) == 9  # 전역 9종은 그대로 내려간다
        assert refs == {"references": []}
        llm.assert_not_awaited()
        rag.assert_not_awaited()
        assert verify_draft_pure(draft, rule_source=source, force_escalation_amount=50_000) is None


def test_verify_rejects_rules_on_non_ai_source():
    """ai가 아닌데 조항이 있으면 조립 버그다."""
    err = _verify(_draft(), rule_source="skip")
    assert err is not None and "rule_source" in err


async def test_non_ai_notes_does_not_false_positive_on_team_name_containing_dues_mark():
    """팀 이름에 ' · 회비 '가 우연히 들어가도(예: '산악 · 회비 모임') non-ai 경로는 통과해야 한다.

    non-ai notes는 팀 이름을 그대로 품는데, 회비 조항-notes 정합 검사를 non-ai에도 걸면
    조항이 하나도 없는데 이 마커만으로 검증 실패 → 500이 나는 오탐이었다.
    """
    req = PolicyDraftRequest(
        **{**BASE_KW, "team_name": "산악 · 회비 모임"},
        rule_source="skip",
    )
    state = await load_template({"request": req})
    draft = (await generate_draft({"request": req, "template": state["template"]}))["draft"]
    assert draft.rules == []
    assert verify_draft_pure(draft, rule_source="skip", force_escalation_amount=50_000) is None


def test_response_no_longer_carries_policy_params():
    assert "policy_params" not in _draft().model_dump()


def test_old_stored_payload_with_policy_params_still_validates():
    """proposals에 저장된 옛 초안(policy_params 포함)도 그대로 읽힌다 — 재사용 경로 회귀."""
    payload = {
        "rules": ["제1조"],
        "policy_params": {"auto_approve_limit": 50_000, "force_escalation_amount": 200_000},
        "recommended_categories": ["교육"],
        "notes": "",
    }
    d = PolicyDraft.model_validate(payload)
    assert d.rules == ["제1조"]
    assert "policy_params" not in d.model_dump()


async def test_full_graph_roundtrip_skip_and_ai():
    """전체 그래프 배선 확인 — DB·LLM 없이 skip과 ai(소개 없음) 둘 다 verified."""
    skip_state = await policy_draft_graph.ainvoke(
        {"request": PolicyDraftRequest(**BASE_KW, rule_source="skip")}
    )
    assert skip_state["verified"] is True
    assert skip_state["draft"].rules == []

    ai_state = await policy_draft_graph.ainvoke(
        {"request": PolicyDraftRequest(**BASE_KW, rule_source="ai")}
    )
    assert ai_state["verified"] is True
    assert ai_state["draft"].rules  # base_rules가 채워진다


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
