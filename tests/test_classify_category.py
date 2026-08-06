"""지출 카테고리 분류 — 전역 9종 (풀스택 협의 2026-08-04 확정).

모임 유형 축이 없어져 어떤 모임이든 같은 9개 중에서 고른다. 키워드 매칭은 부분
문자열이라 짧은 낱말이 엉뚱한 데 걸리기 쉬워, 그 함정도 여기서 고정한다.
"""
import pytest

from app.graphs.review.nodes.classify_category import classify_category
from app.schemas.common import ExpenseClaim
from app.tools.category_catalog import (
    all_categories, classify_by_keywords, fallback_category, keyword_category_or_none,
    load_catalog,
)

EXPECTED = ["식비", "교통", "IT_인프라", "교육", "회의", "장소_대관", "행사_활동", "비품", "기타"]


def test_catalog_is_the_agreed_nine():
    """확정된 9종·순서 그대로여야 한다 — 이 목록이 곧 백엔드 ENUM 값이다."""
    assert all_categories() == EXPECTED
    assert fallback_category() == "기타"
    assert fallback_category() in all_categories()


def test_catalog_has_a_version_for_cache_invalidation():
    """백엔드가 목록을 캐시하므로 판 번호가 있어야 갱신 시점을 안다."""
    assert isinstance(load_catalog()["version"], int)


def test_other_category_has_no_keywords():
    """'기타'는 fallback으로만 도달해야 한다 — 키워드로 걸리면 미분류가 가려진다."""
    other = [c for c in load_catalog()["categories"] if c["name"] == "기타"][0]
    assert other.get("keywords", []) == []


@pytest.mark.parametrize("text,expected", [
    ("정기 모임 뒤풀이 치킨", "식비"),
    ("야근 택시비", "교통"),
    ("노션 팀 구독", "IT_인프라"),
    ("알고리즘 교재 2권", "교육"),
    ("스터디룸 4시간 대관", "장소_대관"),
    ("펜션 2박 예약", "장소_대관"),
    ("축제 부스 현수막 제작", "행사_활동"),
    ("지역 리그 참가비", "행사_활동"),
    ("셔틀콕 1박스", "비품"),
    ("사무용품 구입", "비품"),
])
def test_keyword_classification(text, expected):
    assert classify_by_keywords(text) == expected


def test_meeting_room_goes_to_meeting_not_venue():
    """'회의실 대관'은 회의로 본다 — 회의가 장소_대관보다 위에 있기 때문 (의도된 순서)."""
    assert classify_by_keywords("회의실 대관") == "회의"
    assert classify_by_keywords("스터디룸 대관") == "장소_대관"


@pytest.mark.parametrize("text", ["기술 서적", "미술 재료", "예술 공연 관람"])
def test_short_keyword_traps_are_avoided(text):
    """부분 문자열 매칭 함정 — '술'이 있었다면 기술·미술·예술이 전부 식비가 된다."""
    assert classify_by_keywords(text) != "식비"


def test_desk_is_supplies_not_education():
    """'책'을 키워드에서 뺀 이유 — 넣으면 '책상'이 교육으로 간다."""
    assert classify_by_keywords("책상 구입") == "비품"


def test_meeting_keyword_does_not_steal_supplies():
    """'회의용 마커 구입'은 비품이다 — 맨낱말 '회의'를 빼서 고친 회귀 지점.

    회의가 비품보다 위에 있어서, 맨낱말 '회의'가 있으면 '회의용 ○○ 구입'을 전부
    가로챈다. 실측(키워드 단독 A/B)에서 드러났다.
    """
    assert classify_by_keywords("회의용 마커와 포스트잇 구입") == "비품"
    assert classify_by_keywords("월례 회의실 대관료") == "회의"      # 구체 낱말은 유지


def test_personal_gifts_are_other_not_activity():
    """선물·경조사는 기타다 — 모임 활동이 아니라 개인 대상 지출이라서.

    카탈로그가 행사_활동으로 두고 있었는데 실모드 분류기는 독립적으로 기타로 판단했다.
    둘이 어긋나 있던 것을 맞췄다.
    """
    assert classify_by_keywords("회원 경조사 조화") == "기타"
    assert classify_by_keywords("정기전 참가 등록비") == "행사_활동"   # 활동은 그대로


def test_no_match_falls_back_to_other():
    """못 알아본 지출은 실제 카테고리에 섞지 않고 '기타'로 — 통계 오염 방지."""
    assert classify_by_keywords("정체불명 지출") == "기타"
    assert keyword_category_or_none("정체불명 지출") is None


def test_same_text_maps_to_same_category_regardless_of_team():
    """유형 축이 없어졌다 — 같은 문구는 어떤 모임이든 같은 카테고리다."""
    assert classify_by_keywords("회식 저녁") == "식비"


# ── 노드 동작 ────────────────────────────────────────────────────────────

def _state(category: str) -> dict:
    return {"claim": ExpenseClaim(title="펜션 예약", amount=90_000, category=category,
                                  date="2026-07-10", description="여름 여행 숙소")}


async def test_empty_category_gets_classified():
    result = await classify_category(_state(""))
    assert result["category_source"] == "ai"
    assert result["claim"].category == "장소_대관"
    assert result["claim"].category in all_categories()


# ── T7 (2026-08-06): 분류는 항상 실행된다 ─────────────────────────────────
#
# 종전에는 category에 값이 있으면 분류를 건너뛰고 그 값을 존중했다. 사용자가 화면에서
# 카테고리를 고르던 시절의 동작이다. 8/4 회의로 그 입력 수단이 사라졌고, 백엔드도
# expenses.category를 nullable로 바꿔 항상 빈 값을 보내기로 회신했다(2026-08-06).
# 값이 채워져 와도 라벨은 AI가 확정한다. 채워진 값의 대부분은 우리 콜백이 채운 것이
# 재심사 때 되돌아온 에코라(리뷰 3번), 경고는 AI 판단과 **다를 때만** 남긴다.


async def test_incoming_category_is_overwritten_by_ai():
    """값이 채워져 와도 AI 분류가 라벨을 확정한다 — 입력은 참고되지 않는다."""
    result = await classify_category(_state("식비"))          # 숙박인데 식비로 옴
    assert result["category_source"] == "ai"
    assert result["claim"].category == "장소_대관", "AI 분류가 이겨야 한다"


async def test_differing_incoming_category_logs_warning(caplog):
    """들어온 값과 AI 판단이 갈리면 경고 — 분류 흔들림·구화면 입력은 사람이 봐야 할 신호다."""
    import logging

    with caplog.at_level(logging.WARNING):
        await classify_category(_state("식비"))               # AI는 장소_대관으로 판단
    assert any("다르다" in r.message for r in caplog.records), "불일치 경고가 있어야 한다"


async def test_reecho_of_own_category_is_quiet(caplog):
    """재심사 에코(지난 심사에서 우리가 확정한 값 그대로)는 경고하지 않는다.

    백엔드는 첫 심사 콜백의 suggestedCategory로 expenses.category를 채우므로, 재심사
    경로에서는 채워진 값이 오는 것이 정상이다. 무조건 경고하면 심사할수록 로그가
    잡음이 된다 — normalize_expense_category(0155ad9)와 같은 눈높이."""
    import logging

    with caplog.at_level(logging.WARNING):
        result = await classify_category(_state("장소_대관"))  # AI 판단과 같은 값이 옴
    assert result["claim"].category == "장소_대관"
    assert not caplog.records, "에코 일치에 경고를 찍으면 로그가 신호가 아니라 잡음이 된다"


async def test_stale_vocabulary_category_is_also_overwritten():
    """구 30종 시절 라벨이 와도 덮는다 — 카탈로그 밖 값이 백엔드로 나가면 ENUM 저장이 실패한다."""
    result = await classify_category(_state("숙박/여행비"))
    assert result["claim"].category == "장소_대관"


async def test_result_never_leaves_catalog():
    """어떤 값이 들어와도 결과는 9종 안이다 — 백엔드 ENUM에 닿는 마지막 방어."""
    for incoming in ("", "식비", "숙박/여행비", "존재하지않는카테고리", "IT/인프라"):
        result = await classify_category(_state(incoming))
        assert result["claim"].category in all_categories(), f"입력 {incoming!r}에서 벗어났다"


# ── 저확신 폴백 (카테고리 직접 입력 삭제 대응) ──────────────────────────────

async def _classify_with(pred: "CategoryPrediction") -> str:
    """분류기가 주어진 예측을 냈을 때 최종 확정 카테고리를 얻는다."""
    from unittest.mock import AsyncMock, patch

    state = {"claim": ExpenseClaim(title="정체불명 지출", amount=10_000, category="",
                                   date="2026-07-10", description="")}
    with patch("app.graphs.review.nodes.classify_category.chat_structured",
               AsyncMock(return_value=(pred, {}))):
        result = await classify_category(state)
    return result["claim"].category


async def test_confident_prediction_is_used_as_is():
    from app.graphs.review.nodes.classify_category import CategoryPrediction
    assert await _classify_with(CategoryPrediction(category="교육", confidence=0.9)) == "교육"


async def test_low_confidence_falls_back_to_keywords():
    """AI가 유일한 출처라 저확신 추측을 확정값으로 쓰지 않는다.

    되물어볼 사람이 없으므로 결정적 규칙으로 떨어뜨린다 — 같은 지출이 매번 같은
    카테고리로 가야 카테고리별 집계가 의미를 갖는다.
    """
    from app.graphs.review.nodes.classify_category import CategoryPrediction
    # 키워드가 안 잡히는 문구라 폴백 결과는 '기타'
    assert await _classify_with(CategoryPrediction(category="교육", confidence=0.5)) == "기타"


async def test_out_of_catalog_prediction_is_corrected():
    """환각 카테고리는 확신도와 무관하게 키워드로 교정한다."""
    from app.graphs.review.nodes.classify_category import CategoryPrediction
    assert await _classify_with(CategoryPrediction(category="디자인", confidence=0.99)) == "기타"


async def test_low_confidence_keeps_keyword_hit():
    """저확신이어도 키워드가 잡히면 그 값을 쓴다 — 무조건 기타로 보내지 않는다."""
    from unittest.mock import AsyncMock, patch

    from app.graphs.review.nodes.classify_category import CategoryPrediction
    state = {"claim": ExpenseClaim(title="회식 저녁", amount=40_000, category="",
                                   date="2026-07-10", description="정기 모임 식사")}
    with patch("app.graphs.review.nodes.classify_category.chat_structured",
               AsyncMock(return_value=(CategoryPrediction(category="비품", confidence=0.4), {}))):
        result = await classify_category(state)
    assert result["claim"].category == "식비"


# ── 프롬프트-런타임 정합성 ────────────────────────────────────────────────

def test_prompt_few_shot_matches_runtime_message_format():
    """few_shot이 런타임 user 메시지와 **바이트 단위로** 같은 형식이어야 한다.

    v1이 실패한 지점이다 — few_shot이 실제로 존재하지 않는 후보 라벨을 가르쳐서,
    그걸 충실히 따르는 모델일수록 출력이 폐기되고 키워드 분류로 대체됐다. 형식이
    어긋나도 에러가 아니라 조용한 품질 저하로 나타나므로 테스트로 잡는다.
    """
    import json

    from app.llm.prompts import load_prompt

    spec = load_prompt("classifier")
    candidates = all_categories()
    header = f"카테고리 후보(이 중에서만 선택): {', '.join(candidates)}"

    for i, shot in enumerate(spec.few_shot, 1):
        lines = shot["input"].rstrip("\n").split("\n")
        assert lines[0] == header, f"few_shot {i}의 후보 목록이 카탈로그와 다르다"
        assert lines[1] == "", f"few_shot {i}에 후보-내용 사이 빈 줄이 없다 (런타임은 \\n\\n)"
        assert lines[2].startswith("지출 내용: "), f"few_shot {i}의 내용 줄 형식이 다르다"
        assert json.loads(shot["output"])["category"] in candidates, \
            f"few_shot {i}의 출력이 후보 밖 값이다 — 코드가 폐기한다"


def test_prompt_few_shot_anchors_low_confidence():
    """임계값 0.8 근처 예시가 있어야 모델이 눈금을 맞춘다 (v1에는 없었다)."""
    import json

    from app.llm.prompts import load_prompt

    confidences = [json.loads(s["output"])["confidence"]
                   for s in load_prompt("classifier").few_shot]
    assert any(c < 0.8 for c in confidences), "저확신 예시가 없다"
    assert any(c >= 0.9 for c in confidences), "고확신 예시가 없다"


# ── '기타' 재질의 · OCR 단서 (2026-08-06 실측 발견) ───────────────────────

async def test_etc_answer_is_rechecked_against_keywords():
    """엉성한 제목이 목 모드 끝까지 통과하는지 — 재질의 도입 배경의 회귀 그물.

    배경: '기타'가 카탈로그의 정식 후보라서, 실모드 모델은 모를 때 저확신 대신
    "기타"를 확신 있게 고른다. 엉성한 제목 20건 실측에서 11건이 기타로 갔고 `대관료`·
    `비품 구매`처럼 **카탈로그에 키워드가 버젓이 있는 것들**까지 기타가 됐다
    (확신도 0.85라 폴백 문턱 0.8을 넘어 키워드를 볼 기회조차 없음).

    주의: 목 모드 mock_response는 키워드 분류 결과를 그대로 내므로 "기타인데 키워드는
    안다" 조합이 여기서는 나올 수 없다 — 이 테스트는 재질의 분기를 **직접 타지 못한다**
    (키워드 경로로 같은 답에 도달할 뿐). 분기 자체의 커버는 바로 아래 주입 테스트가
    맡는다(분기를 무력화하면 아래 테스트만 실패한다 — 뮤테이션으로 확인).
    """
    state = {"claim": ExpenseClaim(title="대관료", amount=50_000, category="",
                                   date="2026-07-10", description="")}
    result = await classify_category(state)
    assert result["claim"].category == "장소_대관", "키워드가 아는 것을 기타로 두면 안 된다"


async def test_etc_recheck_fires_even_at_high_confidence():
    """재질의 분기의 실제 커버 — 실모드에서 실측된 답('기타', 0.85)을 직접 주입한다.

    확신도 0.85는 저확신 폴백(0.8 미만)에 안 걸린다. 재질의 분기가 없으면 이 답이
    그대로 확정돼 이 테스트가 실패한다 — 위 테스트와 달리 키워드 경로로는 통과할 수
    없게 만든 것이다.
    """
    from unittest.mock import AsyncMock, patch

    from app.graphs.review.nodes.classify_category import CategoryPrediction

    state = {"claim": ExpenseClaim(title="대관료", amount=50_000, category="",
                                   date="2026-07-10", description="")}
    with patch("app.graphs.review.nodes.classify_category.chat_structured",
               AsyncMock(return_value=(CategoryPrediction(category="기타", confidence=0.85), {}))):
        result = await classify_category(state)
    assert result["claim"].category == "장소_대관", "확신 있는 '기타'도 키워드가 알면 교정돼야 한다"


async def test_etc_recheck_respects_keyword_ignorance():
    """주입된 '기타'라도 키워드가 모르면 그대로 둔다 — 재질의는 아는 것만 고친다."""
    from unittest.mock import AsyncMock, patch

    from app.graphs.review.nodes.classify_category import CategoryPrediction

    state = {"claim": ExpenseClaim(title="알 수 없는 지출", amount=10_000, category="",
                                   date="2026-07-10", description="")}
    with patch("app.graphs.review.nodes.classify_category.chat_structured",
               AsyncMock(return_value=(CategoryPrediction(category="기타", confidence=0.85), {}))):
        result = await classify_category(state)
    assert result["claim"].category == "기타"


async def test_etc_stays_when_keywords_also_dont_know():
    """키워드도 모르면 그때는 기타로 남긴다 — 억지로 8종에 밀어 넣지 않는다."""
    state = {"claim": ExpenseClaim(title="기타 잡비", amount=10_000, category="",
                                   date="2026-07-10", description="")}
    result = await classify_category(state)
    assert result["claim"].category == "기타"


async def test_receipt_merchant_is_used_as_classification_hint():
    """영수증 상호명이 분류 근거에 들어간다 — 제목만으로는 못 맞히는 지출을 살린다.

    사용자 카테고리 입력이 사라진 뒤 제목이 "6월 모임"처럼 엉성하게 오는 것이 실측으로
    확인됐다. 실모드 8건에서 상호명 덕에 5건이 기타를 벗어났다.
    """
    from app.schemas.common import ReceiptData

    claim = ExpenseClaim(title="6월 모임", amount=90_000, category="",
                         date="2026-07-10", description="")
    without = await classify_category({"claim": claim, "expense_id": 1})
    with_receipt = await classify_category({
        "claim": claim, "expense_id": 1,
        "receipt_data": ReceiptData(amount=90_000, date="2026-07-10",
                                    merchant="가평 솔밭펜션", items=[], parse_ok=True),
    })
    assert without["claim"].category == "기타", "제목만으로는 분류 불가한 케이스여야 의미가 있다"
    assert with_receipt["claim"].category == "장소_대관"


async def test_unreadable_receipt_does_not_break_classification():
    """영수증 판독 실패면 제목·설명만으로 분류한다 (fail-open) — 심사를 막지 않는다."""
    from app.schemas.common import ReceiptData

    state = {"claim": ExpenseClaim(title="회식 저녁", amount=40_000, category="",
                                   date="2026-07-10", description="정기 모임"),
             "receipt_data": ReceiptData(parse_ok=False, parse_error="판독 불가")}
    result = await classify_category(state)
    assert result["claim"].category == "식비"
