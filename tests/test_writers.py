"""문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계."""

import re
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.graphs.writers.policy_draft import (
    ExtraRule,
    ExtraRules,
    _AUTO_RULE_HINT,
    article_text,
    LIMIT_LABELS,
    extra_rules_cap,
    drop_vague_rules,
    round_bylaw_amount,
    round_bylaw_amount_down,
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


@pytest.mark.parametrize("team_type", TEAM_TYPES)
@pytest.mark.parametrize("key", ["venue", "supplies", "event"])
def test_scale_limits_keep_growing_at_large_budgets(team_type, key):
    """모임 규모에 비례하는 한도는 큰 예산에서도 계속 올라야 한다.

    상한이 일찍 포화되면 예산이 3배가 돼도 한도가 그대로다 — 실측(2026-08-12)에서
    대관비가 예산 1,000만과 3,000만에서 같은 값이었다. 그러면 큰 모임은 정상 지출마다
    한도를 넘겨 에스컬레이션이 쌓인다.

    **1인 단가 항목은 여기서 보지 않는다.** 식비(1인 1회)·경조사비(1건)·교통비(1인당)·
    여행(1인 1박)은 예산과 무관하게 상식적인 상한이 있어 포화되는 것이 정상이다.
    실제로 친목 경조사비는 예산 500만에서 이미 상한(400,000원)에 닿는다.
    여기서 보는 것은 `basis: total`이면서 모임 규모를 반영하는 세 항목이다.
    """
    tpl = load_templates()[team_type]
    if key not in tpl["limits"]:
        # 2026-08-12부터 `limits`는 유형에 필요한 항목만 정의한다(유형에 없는 지출 축은
        # 회칙이 인용하지도 않으므로 검사 대상이 아니다).
        pytest.skip(f"{team_type}에는 {key} 한도가 없다")
    # 1,000만↔3,000만 — 실측 증상과 같은 구간이어야 그물이 된다. 500만을 쓰면
    # 동아리·스터디는 500만에서 아직 포화 전이라 종전 max로도 통과했다 (#80 리뷰).
    small = int(suggested_limits(tpl, 10_000_000, 20)[key].replace(",", ""))
    large = int(suggested_limits(tpl, 30_000_000, 20)[key].replace(",", ""))
    assert large > small, (
        f"[{team_type}] {key}: 예산 1,000만→3,000만인데 한도가 {small:,}원에서 안 움직인다"
    )


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_limit_maxes_sit_on_the_rounding_grid(team_type):
    """모든 한도 `max`는 round_bylaw_amount 격자 위의 값이어야 한다.

    suggested_limits는 "반올림이 상한을 넘지 않게" `round_bylaw_amount(max)`와
    비교하는데, max 자체가 격자 밖이면 그 가드가 오히려 상한을 키운다 —
    meal.max 75,000이 10,000원 격자 반올림(round(7.5)=8)으로 80,000이 되어
    포화 구간에서 회칙에 선언보다 큰 금액이 적혔다 (#80 리뷰). min은 올림 짝
    함수(round_bylaw_amount_up)가 따로 지키므로 여기서는 max만 본다.
    """
    for key, cfg in load_templates()[team_type]["limits"].items():
        assert round_bylaw_amount(cfg["max"]) == cfg["max"], (
            f"[{team_type}] {key}.max={cfg['max']:,}가 반올림 격자 밖이다 — "
            f"회칙에는 {round_bylaw_amount(cfg['max']):,}원이 적힌다"
        )


def test_prohibition_clauses_are_not_open_ended_relevance_tests():
    """금지 조항을 '목적과 무관한 지출'만으로 쓰지 않는다 — 개인성 같은 확인 가능한 기준을 함께 둔다.

    허용 조항은 열거식인데 금지가 포괄적이면, 열거에서 빠진 카테고리가 전부 금지 쪽으로
    쏠린다. "회칙이 금지하지 않는 것은 허용"이라는 원칙(2026-08-11)이 무력화되는 자리다.
    실제로 6인이 함께 이용한 보드게임 카페 이용료가 스터디 유형의 "학습과 무관한 지출"
    항으로 부적합 판정을 받았다(2026-08-12).

    "무관한가"는 심사관이 주관으로 답하지만 "개인이 사적으로 썼는가"는 증빙으로 확인된다.
    회칙 작성 원칙 4번(모호한 표현을 쓰지 않는다)의 연장이다.

    **트립와이어지 보증이 아니다** (#80 리뷰): '개인' 글자가 같은 항에 있는지만 보므로
    포괄 금지가 개인성 기준으로 실제로 좁혀졌는지까지는 증명하지 못한다. 포괄 표현이
    새로 들어오는 것을 잡는 회귀 그물로만 읽을 것.
    """
    OPEN_ENDED = ("무관", "관련성이 확인되지")
    for team_type, tpl in load_templates().items():
        for article in tpl["bylaw_articles"]:
            # text_no_auto(기준 금액 0원일 때의 대체 본문, #75)도 같은 규범을 지켜야 한다
            texts = [article["text"], article.get("text_no_auto") or ""]
            for clause in (c for t in texts for c in re.split(r"[①-⑨]", t)):
                if not any(w in clause for w in OPEN_ENDED):
                    continue
                assert "개인" in clause, (
                    f"[{team_type}] '{article['title']}' 항이 목적 관련성만으로 금지한다 — "
                    f"개인성 등 확인 가능한 기준을 함께 둘 것: {clause.strip()[:70]}"
                )


# ── 유형별 회칙 분량 (2026-08-12 차등화) ─────────────────
#
# 사용자 피드백: "친목 같은 모임에 회사와 같은 분량의 회칙이 나올 필요가 없다."
# 종전에는 5유형이 16~18조 · 2,032~2,111자로 **글자 수 편차가 3.9%뿐**이었고, 오히려
# 친목이 가장 길었다. 아래 표가 새 기준이며, 이 표를 어기면 테스트가 실패한다.
#
#   유형          기본 조  AI 추가 상한  총 최대   글자 상한
#   친목             7         2          9      1,180
#   스터디            8         3         11      1,240
#   동아리/학생회       9         4         13      1,380
#   동호회            9         4         13      1,500
#   회사             11         4         15      1,820
#
# **글자 상한은 규칙이 늘면 함께 올린다.** 처음 잡은 값(1,000/1,150/1,300/1,300/1,600)은
# '대외 활동 참가비' 조항(PR #82 흡수)이 들어오기 전 기준이었다. 그 항이 유형당 약
# 50~60자를 더하므로 상한도 그만큼 올렸다 — 상한을 고정한 채 두면 **새 규칙을 넣을 때
# 멀쩡한 다른 규칙을 깎아내게** 된다. 줄일 것은 문장이지 규범이 아니다.
# 친목 1,060→1,180 (#83 리뷰 HIGH1): 지웠던 교통비·비품·여행숙박 한도 규범을 항으로
# 복원하며 +112자. 같은 원칙의 적용이다 — 서열(친목 < 스터디)은 유지된다.
BYLAW_BUDGET = {
    "친목": (7, 2, 1_180),
    "스터디": (8, 3, 1_240),
    "동아리/학생회": (9, 4, 1_380),
    "동호회": (9, 4, 1_500),
    "회사": (11, 4, 1_820),
}
#: 글자 수 허용 오차. 유형마다 고유 조항(동호회 장비·안전, 회사 사전 승인 등)이 있어
#: 정확히 맞출 수 없다 — 방향(유형별로 갈린다)이 지켜지는지를 본다.
LENGTH_TOLERANCE = 1.10


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_bylaw_article_count_by_team_type(team_type):
    """유형별 기본 조 수가 표와 일치해야 한다."""
    expected, _, _ = BYLAW_BUDGET[team_type]
    assert len(load_templates()[team_type]["bylaw_articles"]) == expected


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_extra_rules_cap_by_team_type(team_type):
    """AI 맞춤 조항 상한도 유형별이다 — 종전에는 전 유형 10개 공통이었다."""
    _, expected, _ = BYLAW_BUDGET[team_type]
    assert extra_rules_cap(load_templates()[team_type]) == expected


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_total_article_ceiling_never_exceeds_18(team_type):
    """기본 조 + AI 추가 상한이 18조를 넘지 않는다 (전 유형 공통 천장)."""
    base, cap, _ = BYLAW_BUDGET[team_type]
    assert base + cap <= 18


def test_bylaw_length_ordering_is_preserved():
    """친목 < 스터디 < 동아리 = 동호회 < 회사 서열이 유지돼야 한다.

    유형을 고치다 서열이 뒤집히면 "유형에 따라 무게가 다르다"는 설계가 무너진다.
    실제로 개편 전에는 **친목이 가장 길어** 의도와 정반대였다.
    """
    n = {t: len(load_templates()[t]["bylaw_articles"]) for t in TEAM_TYPES}
    assert n["친목"] < n["스터디"] < n["동아리/학생회"] == n["동호회"] < n["회사"]


@pytest.mark.parametrize("team_type", TEAM_TYPES)
async def test_bylaw_length_by_team_type(team_type):
    """생성된 회칙의 글자 수가 유형별 상한 안에 있어야 한다.

    **조 수만 검사하면 못 잡는다.** 조를 합치기만 하고 문장을 안 줄이면 조 하나가
    비대해져 체감 분량이 그대로다 — 실제로 통합 직후 친목이 1,293자였다(목표 1,000).
    """
    _, _, limit = BYLAW_BUDGET[team_type]
    draft = await _draft_for(
        team_type=team_type, initial_budget=3_000_000, member_count=15, dues=20_000
    )
    length = len("".join(draft.rules))
    assert length <= limit * LENGTH_TOLERANCE, (
        f"[{team_type}] {length}자 (상한 {limit}자, 허용 {int(limit * LENGTH_TOLERANCE)}자)"
    )


#: 심사에 쓰이는 조항 — 유형별로 조를 통합·삭제해도 **이 규범은 전 유형에 남아야** 한다.
#: 각 항목은 가드레일 대응표(인수인계 §4)의 한 줄에 대응한다. 이게 없으면 회칙이
#: 짧아지는 대신 심사 근거가 사라져 보류만 늘어난다.
#:
#: 형식: (규범 문구 대안, 같은 조에 함께 있어야 하는 귀결 문구 대안, no_auto 필수, 설명)
#: · 귀결까지 보는 이유 (#83 리뷰): 조를 통합하며 "다시 청구하지 아니한다"가
#:   "정산받은 지출"로 줄면 금지가 아니라 **화제어만** 검사하게 된다 — 규범(금지 동사·
#:   귀결·한정)이 소실돼도 통과한다. 귀결이 문구 안에 이미 있으면 빈 튜플.
#: · no_auto: 기준 금액 0원 렌더링(text_no_auto)에서도 살아야 하는 규범이면 True.
#:   잔액 부족 반려가 0원 경로에서만 빠졌던 사고(#83 리뷰 HIGH2)를 막는 유일한 그물.
#:   자동 심사·에스컬레이션 규범은 전건 관리자 확인 모드에서는 성립하지 않아 False.
#:
#: 표현이 여럿인 항목은 대안을 함께 둔다 — 회사 유형은 "회칙"이 아니라 "규정"을 쓰고
#: (전편 일관), 청구의 진실성을 별도 조로 두어 문장이 길다. **문구가 아니라 규범이
#: 살아 있는지**를 보는 검사다.
AUDIT_CRITICAL_RULES = [
    (("보유 잔액이 부족한 지출은",), ("승인하지 아니한다",), True, "잔액 부족 → 반려"),
    (("AI가 자동 심사하고", "AI가 자동 심사한다"), (), False, "기준 금액 미만 → 자동 판정"),
    (("관리자 승인을 받는다",), (), True, "기준 금액 이상 → 관리자 승인"),
    (
        ("금액과 관계없이 회칙 해석이 불명확", "금액과 관계없이 규정 해석이 불명확"),
        ("관리자가 확인", "관리자 확인을 거친다"),
        False,
        "해석 불명확(금액 무관) → 관리자 확인",
    ),
    (("증빙이 불충분",), ("관리자가 확인", "관리자 확인을 거친다"), False, "증빙 불충분 → 관리자 확인"),
    (("중복 청구가 의심",), ("관리자가 확인", "관리자 확인을 거친다"), False, "중복 의심 → 관리자 확인"),
    (("확인될 때까지 승인을 보류",), (), True, "증빙 미확인 → 보류"),
    (("사유서만으로는 지출을 인정하지 아니한다",), (), True, "사유서 불인정"),
    (("전체 잔액이 충분한 지출",), ("집행할 수 있다",), True, "한도 초과 + 잔액 충분 → 예외 승인"),
    (("예외 승인의 대상이 되지 아니한다",), (), True, "예외로도 열 수 없는 것"),
    (
        ("정산받은 지출의 재청구", "정산받은 지출을 다시 청구하지 아니한다"),
        ("인정하지 아니한다", "청구하지 아니한다"),
        True,
        "재청구 금지",
    ),
    (
        ("분할 청구", "나누어 청구"),
        ("인정하지 아니한다", "청구하지 아니한다"),
        True,
        "분할 청구 금지",
    ),
    (
        ("실제 거래와 다른",),
        ("인정하지 아니한다", "청구하지 아니한다"),
        True,
        "허위 청구 금지",
    ),
]


@pytest.mark.parametrize("phrases,consequences,required_no_auto,why", AUDIT_CRITICAL_RULES)
@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_audit_critical_rules_survive_in_every_type(team_type, phrases, consequences, required_no_auto, why):
    """분량을 줄이다 심사 근거를 떨어뜨리지 않았는지 — 유형 × 규범 × 렌더링 모드 전수.

    종전에는 이 검사가 문구별 테스트 5개에 흩어져 있었다. 유형별 재구성으로 조 제목과
    문장이 바뀌자 한꺼번에 깨져서, 규범 단위로 모으고 표현 차이를 허용하게 바꿨다.
    #83 리뷰 반영으로 두 가지를 더 본다: ① 규범이 있는 조에 귀결(금지·확인)이 함께
    있는지 ② 기준 금액 0원 렌더링(text_no_auto 적용)에서도 규범이 사는지.
    """
    articles = load_templates()[team_type]["bylaw_articles"]
    for has_auto in [True] + ([False] if required_no_auto else []):
        texts = [article_text(a, has_auto_range=has_auto) for a in articles]
        hits = [t for t in texts if any(p in t for p in phrases)]
        mode = "기본" if has_auto else "기준 금액 0원"
        assert hits, f"[{team_type}] {mode} 렌더링에서 누락 — {why} (기대 {phrases})"
        if consequences:
            assert any(any(c in t for c in consequences) for t in hits), (
                f"[{team_type}] {mode} 렌더링에 '{why}' 문구는 있는데 귀결이 같은 조에 "
                f"없다 (기대 {consequences})"
            )


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_limits_and_articles_agree_both_ways(team_type):
    """`limits`에 정의한 한도는 반드시 어떤 조가 인용하고, 그 반대도 성립해야 한다.

    종전에는 한쪽만 있었다 — 동아리·동호회의 `gift`·`travel`, 스터디의 `event`·`gift`·
    `travel`이 **계산만 되고 인용하는 조항이 없었다**(2026-08-12 발견). 그 카테고리
    지출은 회칙 근거 없이 심사된다.

    개수는 검사하지 않는다 — 유형별로 몇 개여야 한다는 규율은 두지 않는다.
    """
    tpl = load_templates()[team_type]
    defined = set(tpl["limits"])
    body = " ".join(a["text"] for a in tpl["bylaw_articles"])
    used = {k for k in LIMIT_LABELS if "{" + k + "}" in body}
    assert defined == used, (
        f"[{team_type}] 정의만 하고 안 쓰는 것: {sorted(defined - used) or '없음'} / "
        f"정의 없이 인용하는 것: {sorted(used - defined) or '없음'}"
    )


#: 유형별로 반드시 정의돼 있어야 하는 한도 축 (#90, #83 리뷰 MEDIUM 후속).
#:
#: 위 both_ways 검사는 정의↔인용 **일치**만 보므로, 조항과 limits를 **함께** 지우면
#: 전 테스트가 통과한다 — #83 초판에서 친목 supplies·transport·travel이 그렇게
#: 소리 없이 빠졌다(리뷰 HIGH1). 이 상수는 그 경로를 막는다.
#:
#: **개수 규율이 아니다** (기존 결정: 한도 항목 개수를 유형별로 못박지 않는다).
#: 검사는 ⊇(포함)만 보므로 **추가는 자유**고, 삭제할 때만 이 상수를 함께 고치게 되어
#: 삭제가 diff에 정책 변경으로 드러난다. 상수를 고치는 PR은 "이 유형에서 이 한도
#: 규범을 없앤다"는 팀 승인 대상이다.
REQUIRED_LIMITS = {
    "동아리/학생회": {"meal", "venue", "supplies", "transport", "education", "event"},
    "스터디": {"meal", "venue", "supplies", "transport", "education", "event"},
    "친목": {"meal", "venue", "supplies", "transport", "event", "gift", "travel"},
    "동호회": {"meal", "venue", "supplies", "transport", "education", "event", "travel"},
    "회사": {"meal", "venue", "supplies", "transport", "education", "event", "gift", "travel"},
}


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_required_limit_axes_stay_defined(team_type):
    """합의된 한도 축을 지우면 테스트가 소리를 내야 한다 — 조항·limits 동반 삭제 방어.

    both_ways와 짝이다: 저쪽이 '정의한 것은 인용한다'를, 여기가 '합의한 것은 정의돼
    있다'를 지킨다. 둘이 함께 있어야 "조항만 삭제"(both_ways가 잡음)와 "조항+limits
    동반 삭제"(여기가 잡음)가 모두 그물에 걸린다.
    """
    defined = set(load_templates()[team_type]["limits"])
    missing = REQUIRED_LIMITS[team_type] - defined
    assert not missing, (
        f"[{team_type}] 필수 한도 축이 정의에서 빠졌다: {sorted(missing)} — 의도한 "
        f"정책 변경이면 REQUIRED_LIMITS를 함께 고치고 PR 본문에 근거를 밝힐 것"
    )


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


@pytest.mark.parametrize("team_type", TEAM_TYPES)
@pytest.mark.parametrize(
    "force,budget",
    [
        (0, 1_000_000),        # '모든 지출 직접 확인' 토글
        (50_000, 1_000_000),
        (70_000, 1_000_000),
        (70_000, 5_000_000),   # 예산이 커지면 한도도 커진다
        (300_000, 20_000_000),
    ],
)
async def test_all_team_types_draft_verifies(team_type, force, budget):
    """5유형 × 기준 금액·예산 조합 전부에서 초안이 검증을 통과해야 한다.

    이 테스트가 없어서 **회사 유형은 초안 생성이 계속 500이었다**(2026-08-12 발견).
    경조사비 조가 'AI 자동 심사'라는 말과 `{gift}` 한도를 함께 담고 있어,
    verify_draft_pure가 그 조의 금액을 승인 기준 금액으로 한정하는 검사에 걸렸다 —
    승인 기준 금액과 경조사비 한도가 **우연히 같은 조합에서만** 통과했다.

    놓친 경로가 둘이었다. 유형별 실측(§실측 3종)은 동아리·동호회·친목만 돌렸고,
    단위 테스트는 대부분 BASE_KW의 스터디 하나만 봤다. 회사 유형을 쓰는 테스트는
    조항 **개수**만 세고 verify를 부르지 않았다.

    예산을 함께 흔드는 이유: 한도는 예산에서 산출되므로 예산이 바뀌면 조항 금액도
    바뀐다. 고정 예산 하나로는 '우연히 같아서 통과'와 '정말 맞아서 통과'를 구분하지
    못한다 — 실제로 기준 50,000 + 예산 100만에서는 회사 유형도 통과했다.
    """
    draft = await _draft_for(
        team_type=team_type, initial_budget=budget,
        force_escalation_amount=force, dues=20_000,
    )
    assert _verify(draft, force=force) is None
    assert "{" not in "\n".join(draft.rules)


def test_no_article_mixes_auto_review_wording_with_limit_amounts():
    """'자동 심사'·'관리자 승인'을 말하는 조에는 한도 placeholder를 같이 쓰지 않는다.

    verify_draft_pure가 그런 조의 금액을 승인 기준 금액 하나로 한정하므로, 한도를
    같이 담으면 두 금액이 우연히 같을 때만 초안이 나온다(회사 경조사비 조가 그랬다).
    위 매트릭스 테스트는 결과가 깨졌을 때 잡고, 이 테스트는 **조합 자체**를 템플릿
    단계에서 막는다 — 새 조항을 쓰는 사람이 실패 이유를 바로 알 수 있게.
    """
    limit_placeholders = (
        "{meal}", "{venue}", "{supplies}", "{transport}",
        "{education}", "{event}", "{gift}", "{travel}",
    )
    for team_type, template in load_templates().items():
        for article in template["bylaw_articles"]:
            for key in ("text", "text_no_auto"):
                text = article.get(key)
                if not text or not _AUTO_RULE_HINT.search(text):
                    continue
                mixed = [p for p in limit_placeholders if p in text]
                assert not mixed, (
                    f"[{team_type}] '{article['title']}' 조({key})가 자동 심사·관리자 승인을 "
                    f"말하면서 한도 {mixed}를 함께 인용한다 — 조를 나누거나 문구를 바꿀 것"
                )


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
    assert "AI가 자동 심사" in approval  # 근거를 밝힌 표현 — "AI가 승인한다"가 아니다
    assert "{" not in "\n".join(draft.rules)
    assert _verify(draft, force=70_000) is None


async def test_bylaw_separates_insufficient_balance_from_over_limit():
    """잔액 부족(반려)과 항목 한도 초과(예외 승인)를 회칙이 **다른 조에서** 구분한다.

    가드레일 동작과 대응한다 — 잔액 부족은 budget_insufficient → 반려, 한도 초과 +
    잔액 충분은 rule 축 → escalate. 둘이 한 조에 섞이면 회칙만 읽고는 구분되지 않는다.

    2026-08-12 유형별 재구성으로 '예산 집행 원칙' 조가 '지출 심사' 조 ①항으로
    들어갔다 — 조 이름이 아니라 **두 규범이 서로 다른 조에 있는지**를 본다.
    """
    draft = await _draft_for()
    balance_rule = next(r for r in draft.rules if "보유 잔액이 부족한 지출" in r)
    assert "금액과 관계없이 승인하지 아니한다" in balance_rule
    assert "전체 잔액이 충분한" not in balance_rule  # 예외 승인 조로 갈라져 있어야 한다

    exception_rule = next(r for r in draft.rules if "전체 잔액이 충분한" in r)
    assert exception_rule != balance_rule, "잔액 부족과 예외 승인이 한 조에 섞여 있다"
    # 예외 승인으로도 허용하지 않는 것이 명시돼야 한다
    assert "예외 승인의 대상이 되지 아니한다" in exception_rule


# 해석 불명확·증빙 불충분·중복 의심 → 관리자 확인, 사유서 불인정, 보류 —
# 이 셋은 `test_audit_critical_rules_survive_in_every_type`이 유형 × 규범 전수로 본다.
# 종전에는 여기에 문구별 테스트로 흩어져 있었다(2026-08-12 통합).


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


def test_bylaw_amount_rounding_never_raises_declared_cap():
    """반올림이 한도의 상한(max)을 키우면 안 된다 — min 보호와 대칭 (#91, #80 리뷰 후속).

    격자 밖 max(75,000)를 가까운 쪽 반올림에 태우면 80,000이 되어, "반올림이 상한을
    넘지 않게" 두었던 가드가 오히려 상한을 키웠다(meal.max 사고). 상한은 내림으로
    맞춘다. 격자 위 값은 내려가지 않아 동작 불변이다.

    데이터 쪽 규율(test_limit_maxes_sit_on_the_rounding_grid — max는 격자 위의 값만)은
    그대로 유지한다. 이 테스트는 그 규율이 뚫려 격자 밖 max가 들어와도 **코드가**
    상한을 지키는지를 본다(이중 방어).
    """
    assert round_bylaw_amount(75_000) == 80_000        # 범용 반올림은 그대로
    assert round_bylaw_amount_down(75_000) == 70_000   # 상한은 내림
    assert round_bylaw_amount_down(80_000) == 80_000   # 격자 위 값은 불변
    assert round_bylaw_amount_down(120_000) == 120_000
    assert round_bylaw_amount_down(230_000) == 200_000  # 50,000원 단위 내림

    # 격자 밖 max를 가진 합성 템플릿 — 포화 구간에서도 선언한 상한을 넘지 않아야 한다
    synthetic = {"limits": {"meal": {"basis": "per_person", "ratio": 0.5, "min": 10_000, "max": 75_000}}}
    got = int(suggested_limits(synthetic, initial_budget=10_000_000, member_count=2)["meal"].replace(",", ""))
    assert got <= 75_000, f"선언한 상한 75,000을 넘는 {got:,}이 나왔다"
    assert got == 70_000  # 내림 격자 위의 최대값


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


# 중복·분할·허위 청구 금지도 `test_audit_critical_rules_survive_in_every_type`으로
# 옮겼다 — 유형별 재구성으로 회사만 '청구의 진실성'을 별도 조로 두고 나머지는
# '인정하지 않는 지출'에 항으로 흡수해, 문구가 갈렸기 때문이다 (2026-08-12).


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


async def test_zero_threshold_says_all_expenses_not_zero_won():
    """'모든 지출 직접 확인'(기준 금액 0)이면 금액 없이 '모든 지출'로 쓴다.

    종전에는 기본 문구를 그대로 치환해 **"1건 0원 미만의 지출은 AI가 자동 심사한다"**가
    나왔다(2026-08-12 발견). 0원 미만은 존재하지 않으므로 ①항이 통째로 공집합을
    가리키는 공허한 조항인데 verified=True로 통과했고, 관리자가 그대로 확정하면
    인덱싱되어 심사 근거가 된다.

    종전 테스트는 `"0원" in rules`와 verify 통과만 봐서 이 자리를 그대로 지나쳤다 —
    '0원이 적혔는가'가 아니라 '말이 되는가'를 봐야 했다.
    """
    draft = await _draft_for(force_escalation_amount=0)
    text = "\n".join(draft.rules)
    # 앞자리 숫자가 없는 '0원'만 본다 — 40,000원·200,000원 같은 정상 한도도 "0원"으로
    # 끝나므로 단순 부분 문자열 검사로는 구분되지 않는다.
    assert not re.search(r"(?<![\d,])0원", text), f"기준 금액 0이 조항에 숫자로 인용됨: {text}"
    approval = next(r for r in draft.rules if "관리자 승인" in r)
    assert "모든 지출은 금액과 관계없이 관리자 승인을 받는다" in approval
    assert _verify(draft, force=0) is None


def test_verify_rejects_any_amount_when_threshold_is_zero():
    """기준 금액 0인데 조항이 금액을 인용하면 불통과 — LLM이 '0원 이상' 조를 써도 막는다.

    프롬프트에도 쓰지 말라고 적었지만, 이 저장소에서 반복 확인된 것은 '프롬프트로
    금지한 것은 코드로 한 번 더 막아야 한다'이다(모호어·한도 밖 금액이 같은 계열).
    """
    err = _verify(
        _draft(rules=["제1조(지출 심사) 1건 0원 이상의 지출은 관리자 승인을 받는다."]), force=0
    )
    assert err is not None and "0" in err


def test_article_text_falls_back_when_no_override():
    """`text_no_auto`가 없는 조는 기준 금액 0이어도 기본 본문을 그대로 쓴다."""
    plain = {"title": "목적", "text": "이 회칙은 …"}
    assert article_text(plain, has_auto_range=False) == "이 회칙은 …"
    both = {"title": "지출 심사", "text": "기본", "text_no_auto": "대체"}
    assert article_text(both, has_auto_range=True) == "기본"
    assert article_text(both, has_auto_range=False) == "대체"


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
