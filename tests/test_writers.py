"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""

import re
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.graphs.writers.policy_draft import (
    ExtraRule,
    ExtraRules,
    drop_vague_rules,
    round_bylaw_amount,
    round_bylaw_amount_up,
    suggested_limits,
    unknown_amounts_in,
    vague_terms_in,
    MAX_EXTRA_RULES,
    _mock_extra_rules,
    generate_draft,
    load_template,
    load_templates,
    policy_draft_graph,
    retrieve_references,
    verify_draft_pure,
)
from app.graphs.writers.report import (
    _mock_report_text,
    aggregate_pure,
    generate_report,
    verify_report,
    verify_report_pure,
)
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
    assert "안전장비" in rules[0].text
    assert rules[0].title  # 조 제목이 비면 "제N조() …"가 된다


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
    # 회비 미입력이라 회비 조는 빠진다 (2026-08-11: 제안값을 만들지 않는다)
    articles = load_templates()["동호회"]["bylaw_articles"]
    base_count = len(articles) - sum(1 for a in articles if "회비는 1인당 " in a["text"])
    assert len(draft.rules) == base_count + 1
    assert "안전장비" in draft.rules[-1]
    assert _verify(draft, force=50_000) is None  # placeholder 없이 정상 치환


async def test_generate_draft_without_description_uses_bylaw_articles_only():
    """소개가 없으면 LLM을 부르지 않고 유형별 회칙 조항만 나온다.

    회사 유형은 dues_default=0이라 회비 조가 빠진다 — '회비 1인당 0원' 조항은
    회칙으로 성립하지 않기 때문이다.
    """
    req = PolicyDraftRequest(
        **{**BASE_KW, "team_type": "회사", "team_name": "테스트팀", "initial_budget": 1_000_000},
        rule_source="ai",
    )
    state = await load_template({"request": req})
    result = await generate_draft({"request": req, "template": state["template"]})
    draft = result["draft"]
    articles = load_templates()["회사"]["bylaw_articles"]
    dues_articles = sum(1 for a in articles if "회비는 1인당 " in a["text"])
    assert len(draft.rules) == len(articles) - dues_articles


# ── 회칙 초안 형식 · 예산 연동 (2026-08-11 개편) ──────────


async def test_articles_are_numbered_and_titled():
    """조 번호와 제목이 붙어야 회칙 문서로 읽힌다 — 종전엔 번호 없는 단문 목록이었다."""
    draft = await _draft_for(initial_budget=600_000, dues=20_000)
    assert draft.rules[0].startswith("제1조(")
    assert draft.rules[1].startswith("제2조(")
    # 조 번호는 끊기지 않고 이어져야 한다
    for i, rule in enumerate(draft.rules, start=1):
        assert rule.startswith(f"제{i}조("), rule[:20]


async def test_limits_scale_with_budget():
    """한도가 예산에 따라 달라져야 한다 — 종전엔 PER_MEAL_LIMIT 상수 하나였다."""
    small = await _draft_for(initial_budget=300_000, member_count=10, dues=20_000)
    large = await _draft_for(initial_budget=10_000_000, member_count=10, dues=20_000)

    def meal_of(draft):
        rule = next(r for r in draft.rules if "1인 1회" in r)
        return max(int(a.replace(",", "")) for a in re.findall(r"([\d,]+)\s*원", rule))

    assert meal_of(small) < meal_of(large)


async def test_no_bylaw_article_uses_a_non_catalog_category_word():
    """'다과비'처럼 카탈로그에 없는 분류명을 쓰면 회원이 고를 수 있는 분류와 어긋난다."""
    templates = load_templates()
    for team_type, tpl in templates.items():
        blob = " ".join(a["text"] for a in tpl["bylaw_articles"]) + " ".join(tpl["base_rules"])
        assert "다과비" not in blob, team_type
        assert "간식비" not in blob, team_type


# ── 마법사 2단계 기준 금액 · 1단계 회비 ───────────────────


async def _draft_for(**kwargs):
    req = PolicyDraftRequest(**{**BASE_KW, "rule_source": "ai", **kwargs})
    state = await load_template({"request": req})
    return (await generate_draft({"request": req, "template": state["template"]}))["draft"]


async def test_approval_threshold_appears_as_a_real_amount():
    """승인 기준 금액은 화면 입력값이 **숫자 그대로** 회칙에 들어간다 (2026-08-11 저녁).

    한때 숫자를 빼고 "관리자가 설정한 기준 금액"으로만 적었으나 되돌렸다 — 회칙은
    숫자로 말해야 규범으로 기능하고, 레퍼런스 회칙들도 모두 금액을 명시한다.
    생성 시점의 정합성은 verify_draft_pure가 보장한다(설정 금액 외의 금액을 막는다).
    관리자가 나중에 설정을 바꾸면 회칙 숫자가 낡는데, 그것은 회칙 개정으로 다룰 일이다.
    """
    draft = await _draft_for(force_escalation_amount=70_000)
    approval = next(r for r in draft.rules if "관리자 승인" in r)
    assert "70,000원" in approval
    assert "AI가 자동 심사한다" in approval  # 근거를 밝힌 표현 — "AI가 승인한다"가 아니다
    assert "{" not in "\n".join(draft.rules)
    assert _verify(draft, force=70_000) is None


async def test_bylaw_separates_insufficient_balance_from_over_limit():
    """잔액 부족(반려)과 항목 한도 초과(예외 승인)를 회칙이 구분한다 — 가드레일 동작과 일치.

    특별 승인 절차는 '예외 승인' 조로 일원화했다(2026-08-11 밤) — 예산 조와 예외 승인
    조에 같은 내용이 겹쳐 있었다.
    """
    draft = await _draft_for()
    budget_rule = next(r for r in draft.rules if "예산 집행 원칙" in r)
    assert "보유 잔액이 부족한 지출은 금액과 관계없이 승인하지 아니한다" in budget_rule
    assert "전체 잔액이 충분한" not in budget_rule  # 예외 승인 조로 옮겼다

    exception_rule = next(r for r in draft.rules if "예외 승인" in r)
    assert "전체 잔액이 충분한" in exception_rule
    # 예외 승인으로도 허용하지 않는 것이 명시돼야 한다
    assert "예외 승인의 대상이 되지 아니한다" in exception_rule


async def test_bylaw_escalates_regardless_of_amount_on_ambiguity():
    """금액이 작아도 해석 불명확·증빙 불충분·중복 의심이면 관리자 확인 — 가드레일 동작과 일치."""
    for team_type in TEAM_TYPES:
        joined = "\n".join((await _draft_for(team_type=team_type)).rules)
        assert "금액과 관계없이 회칙 해석이 불명확한 경우" in joined or \
               "금액과 관계없이 회칙 해석이 불명확" in joined, team_type
        assert "중복 청구가 의심되는 경우에는 관리자 확인을 거친다" in joined, team_type


async def test_evidence_article_does_not_accept_a_note_alone():
    """증빙 없이 사유서만으로는 인정하지 않고, 확인될 때까지 보류한다."""
    for team_type in TEAM_TYPES:
        joined = "\n".join((await _draft_for(team_type=team_type)).rules)
        assert "확인될 때까지 승인을 보류한다" in joined, team_type
        assert "사유서만으로는 지출을 인정하지 아니한다" in joined, team_type


async def test_dues_article_states_a_payment_period():
    """'1인당 15,000원'만으로는 언제 내는지 알 수 없다 — 주기를 함께 적는다."""
    draft = await _draft_for(team_type="동아리/학생회", dues=15_000)
    dues_rule = next(r for r in draft.rules if "회비는 1인당 " in r)
    assert "학기당" in dues_rule and "15,000원" in dues_rule


def test_bylaw_amounts_are_rounded_to_readable_units():
    """19,000·48,000·320,000처럼 어중간한 금액은 사람이 쓴 규정처럼 보이지 않는다."""
    assert round_bylaw_amount(19_000) == 20_000
    assert round_bylaw_amount(48_000) == 50_000
    assert round_bylaw_amount(320_000) == 300_000
    assert round_bylaw_amount(12_000) == 10_000    # 5,000원 단위
    assert round_bylaw_amount(125_000) == 120_000  # 10,000원 단위
    assert round_bylaw_amount(280_000) == 300_000  # 50,000원 단위


def test_bylaw_amount_rounding_never_lowers_declared_floor():
    """반올림이 한도의 하한(min)을 깎으면 안 된다 (PR #65 리뷰 N1).

    `round_bylaw_amount`는 가까운 쪽으로 붙이는 범용 반올림이라 12,000 → 10,000이
    맞다. 문제는 그것을 **하한에 그대로 쓰던 것**이었다 — min은 "이보다 낮게는 주지
    않는다"는 선언이므로 올림으로 맞춘다. 예산이 아무리 작아도 선언한 하한 미만은
    나오지 않는지 유형 전수로 고정한다.
    """
    assert round_bylaw_amount(12_000) == 10_000      # 범용 반올림은 그대로
    assert round_bylaw_amount_up(12_000) == 15_000   # 하한은 올림

    for team_type, template in load_templates().items():
        # 예산·인원을 최소로 줘서 모든 항목이 하한에 걸리게 만든다
        limits = suggested_limits(template, initial_budget=1, member_count=1)
        for key, cfg in (template.get("limits") or {}).items():
            floor = cfg.get("min")
            if not floor:
                continue
            got = int(limits[key].replace(",", ""))
            assert got >= floor, (
                f"{team_type}/{key}: 선언한 하한 {floor:,}보다 낮은 {got:,}이 나왔다"
            )


def test_unknown_amounts_are_detected():
    """한도 표에 없는 금액을 쓴 LLM 조항은 걸러진다."""
    allowed = {50_000, 240_000}
    assert unknown_amounts_in("건당 240,000원 이내로 인정한다", allowed) == []
    assert unknown_amounts_in("건당 777,000원 이내로 인정한다", allowed) == [777_000]


def test_unknown_amounts_catch_korean_man_notation():
    """'3만원' 같은 한글 단위 표기도 잡는다 — 숫자 표기만 보면 필터를 우회한다 (N5)."""
    allowed = {30_000, 50_000}
    assert unknown_amounts_in("1인 1회 3만원 이내로 집행한다", allowed) == []
    assert unknown_amounts_in("1인 1회 7만원 이내로 집행한다", allowed) == [70_000]
    # 숫자 표기와 같은 값으로 환산되어 한도 표와 그대로 대조된다
    assert unknown_amounts_in("20만 원 이내", {200_000}) == []


async def test_bylaw_forbids_duplicate_split_and_false_claims():
    """중복·분할·허위 청구 금지는 전 유형 공통 조항이다."""
    for team_type in TEAM_TYPES:
        draft = await _draft_for(team_type=team_type)
        joined = "\n".join(draft.rules)
        assert "다시 청구하지 아니한다" in joined, team_type
        assert "나누어 청구하지 아니한다" in joined, team_type
        assert "실제 거래와 다른" in joined, team_type


async def test_bylaw_uses_human_wording_not_system_identifiers():
    """회칙에는 시스템 내부 표기 대신 사람이 쓰는 말을 쓴다 (장소_대관 → 장소 대관비)."""
    for team_type in TEAM_TYPES:
        joined = "\n".join((await _draft_for(team_type=team_type)).rules)
        for token in ("장소_대관", "행사_활동", "IT_인프라"):
            assert token not in joined, f"{team_type}: {token}"


async def test_bylaw_avoids_vague_amount_words():
    """'소액'·'고가'·'적절한' 같은 말은 심사 기준이 되지 못한다."""
    for team_type in TEAM_TYPES:
        joined = "\n".join((await _draft_for(team_type=team_type)).rules)
        for word in ("소액", "적절한", "과도한", "상당한"):
            assert word not in joined, f"{team_type}: {word}"


async def test_dues_input_wins_over_suggestion():
    """사용자가 입력한 회비가 원천이다 — 제안값으로 덮어쓰지 않는다."""
    draft = await _draft_for(initial_budget=600_000, dues=20_000)
    dues_rule = next(r for r in draft.rules if "회비는 1인당 " in r)
    assert "20,000원" in dues_rule
    assert "회비 20,000원" in draft.notes
    assert "제안값" not in draft.notes
    assert _verify(draft, force=50_000) is None


async def test_no_dues_means_no_dues_article():
    """회비를 입력하지 않으면 회칙에 회비 조를 만들지 않는다 (2026-08-11).

    한때 유형별 기본값으로 제안했으나 되돌렸다 — 관리자가 정한 적 없는 금액을
    회칙이 단정하게 되고, 확정된 회칙은 심사 근거로 인덱싱되기 때문이다.
    """
    for dues in (None, 0):
        draft = await _draft_for(initial_budget=600_000, dues=dues)
        assert not any("회비는 1인당 " in r for r in draft.rules)
        assert "회비" not in draft.notes
        assert _verify(draft, force=50_000) is None


async def test_dues_amount_matches_between_rule_and_notes():
    """조항과 notes가 다른 금액을 말하면 조립 버그 — verify가 잡아야 한다."""
    draft = await _draft_for(initial_budget=600_000, dues=20_000)
    broken = draft.model_copy(update={"notes": draft.notes.replace("20,000원", "99,000원")})
    assert _verify(broken, force=50_000) is not None


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


@pytest.mark.parametrize("spelling", ["동아리_학생회", "동아리학생회"])
def test_team_type_accepts_backend_underscore_spelling(spelling):
    """백엔드 ENUM은 언더바 표기(2026-08-06 확정) — 경계에서 내부 표기로 접는다.

    변환 없이는 템플릿·카탈로그 조회가 조용히 기본 유형으로 fallback한다."""
    ok = PolicyDraftRequest(**{**BASE_KW, "team_type": spelling, "rule_source": "ai"})
    assert ok.team_type == "동아리/학생회"


def test_team_type_unknown_value_still_rejected():
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**{**BASE_KW, "team_type": "밴드", "rule_source": "ai"})


def test_force_escalation_amount_zero_accepted():
    """'모든 지출 직접 확인' 토글이면 백엔드가 0을 보낸다 — 0 = 전건 관리자 확인
    (백엔드 확인 2026-08-06). 심사 쪽 해석(policy_params: 한도 없음→전건 확인)과 동일."""
    ok = PolicyDraftRequest(**{**BASE_KW, "force_escalation_amount": 0, "rule_source": "ai"})
    assert ok.force_escalation_amount == 0


def test_force_escalation_amount_negative_still_rejected():
    with pytest.raises(ValidationError):
        PolicyDraftRequest(**{**BASE_KW, "force_escalation_amount": -1, "rule_source": "ai"})


async def test_ai_draft_with_zero_amount_stays_verified():
    """0원 기준도 조항 금액 정합 검사를 통과한다 — '0원 이상 = 전건 관리자 확인' 조항."""
    draft = await _draft_for(force_escalation_amount=0)
    assert "0원" in "\n".join(draft.rules)
    assert _verify(draft, force=0) is None


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


async def test_verify_report_falls_back_to_mock_text_on_mismatch():
    f = aggregate_pure("2026-06", EXPENSES)
    bad = BudgetReport(figures=f, summary="총 지출 999,999원", recommendations=[], verified=False)
    result = await verify_report({"report": bad, "figures": f})
    report = result["report"]
    assert report.verified is False
    assert report.summary == _mock_report_text(f).summary


async def test_verify_report_keeps_verified_true_on_match():
    f = aggregate_pure("2026-06", EXPENSES)
    text = f"총 지출 {f.total_spent:,}원 (2건). 식비 {80_000:,}원, 도서 {20_000:,}원"
    good = BudgetReport(figures=f, summary=text, recommendations=[], verified=False)
    result = await verify_report({"report": good, "figures": f})
    report = result["report"]
    assert report.verified is True
    assert report.summary == text  # 검증 통과 시 원문 그대로


def test_mock_report_text_passes_its_own_verifier():
    """폴백 텍스트 자체가 verify_report_pure를 통과해야 한다(자기모순 방지)."""
    f = aggregate_pure("2026-06", EXPENSES)
    fallback = BudgetReport(
        figures=f, summary=_mock_report_text(f).summary, recommendations=[], verified=False
    )
    assert verify_report_pure(fallback, f) is True


# ── 금액 모호어 필터 (2026-08-11 저녁) ────────────────────
#
# v5 프롬프트가 "소액"·"고가" 같은 말을 금지하지만 LLM이 지키지 않는 것을 실측으로
# 확인했다(친목 초안에 "소액 선물" 조항이 나왔다). 프롬프트만으로는 못 막는 계열이라
# 조립 단계에서 해당 조를 떨어뜨리고, 템플릿에 섞이면 검증이 잡는다.


def test_vague_terms_are_detected():
    assert vague_terms_in("소액 선물은 인정한다") == ["소액"]
    assert vague_terms_in("적절한 범위에서 집행한다") == ["적절한"]
    assert vague_terms_in("1건 30,000원 이내로 인정한다") == []


def test_vague_terms_do_not_flag_legitimate_wording():
    """우리 템플릿이 정당하게 쓰는 표현은 걸리지 않아야 한다 — 좁게 잡은 이유."""
    assert vague_terms_in("전체 잔액이 충분한 지출은 특별 승인할 수 있다") == []
    assert vague_terms_in("필요한 경우 참가 인원을 제한한다") == []


def test_drop_vague_rules_keeps_the_rest():
    keep, dropped = drop_vague_rules([
        "(경조사) 1건 50,000원 이내로 인정한다.",
        "(선물) 소액 선물은 회비로 지출할 수 있다.",
        "(여행) 재적 회원 과반의 찬성을 얻어 집행한다.",
    ])
    assert len(keep) == 2 and len(dropped) == 1
    assert "소액" in dropped[0]


async def test_llm_clause_with_vague_wording_is_dropped_from_the_draft():
    """LLM이 모호어 조항을 내놓아도 초안에는 실리지 않는다 — 초안 전체는 살린다."""
    vague = ExtraRules(extra_rules=[
        ExtraRule(title="선물", text="소액 선물은 회비로 지출할 수 있다."),
        ExtraRule(title="장비", text="공용 장비는 사용 후 지정된 장소에 보관한다."),
    ])
    with patch("app.graphs.writers.policy_draft.chat_structured",
               AsyncMock(return_value=(vague, None))):
        draft = await _draft_for(description="선물과 장비를 다루는 모임")
    joined = "\n".join(draft.rules)
    assert "소액" not in joined
    assert "공용 장비는 사용 후" in joined      # 멀쩡한 조항은 남는다
    assert _verify(draft, force=50_000) is None


def test_verify_catches_vague_wording_in_rules():
    """템플릿에 모호어가 섞이면(우리 쪽 결함) 검증이 불통과시킨다."""
    err = _verify(_draft(rules=["제1조(선물) 소액 선물은 인정한다."]))
    assert err is not None and "모호어" in err
