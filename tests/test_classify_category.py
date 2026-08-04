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

EXPECTED = ["식비", "교통", "IT/인프라", "교육", "회의", "장소/대관", "행사/활동", "비품", "기타"]


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
    ("노션 팀 구독", "IT/인프라"),
    ("알고리즘 교재 2권", "교육"),
    ("스터디룸 4시간 대관", "장소/대관"),
    ("펜션 2박 예약", "장소/대관"),
    ("축제 부스 현수막 제작", "행사/활동"),
    ("지역 리그 참가비", "행사/활동"),
    ("셔틀콕 1박스", "비품"),
    ("사무용품 구입", "비품"),
])
def test_keyword_classification(text, expected):
    assert classify_by_keywords(text) == expected


def test_meeting_room_goes_to_meeting_not_venue():
    """'회의실 대관'은 회의로 본다 — 회의가 장소/대관보다 위에 있기 때문 (의도된 순서)."""
    assert classify_by_keywords("회의실 대관") == "회의"
    assert classify_by_keywords("스터디룸 대관") == "장소/대관"


@pytest.mark.parametrize("text", ["기술 서적", "미술 재료", "예술 공연 관람"])
def test_short_keyword_traps_are_avoided(text):
    """부분 문자열 매칭 함정 — '술'이 있었다면 기술·미술·예술이 전부 식비가 된다."""
    assert classify_by_keywords(text) != "식비"


def test_desk_is_supplies_not_education():
    """'책'을 키워드에서 뺀 이유 — 넣으면 '책상'이 교육으로 간다."""
    assert classify_by_keywords("책상 구입") == "비품"


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
    assert result["claim"].category == "장소/대관"
    assert result["claim"].category in all_categories()


async def test_user_category_is_respected():
    result = await classify_category(_state("장소/대관"))
    assert result["category_source"] == "user"
    assert "claim" not in result  # claim 미변경


async def test_confident_disagreement_flags_mismatch():
    """숙박 지출을 식비로 등록 → 확신 있는 불일치 → 가드레일 보류 대상."""
    result = await classify_category(_state("식비"))
    assert result["category_source"] == "user"
    assert "claim" not in result                     # 라벨은 사용자 것 유지
    assert result["category_mismatch"] is True
    assert result["ai_suggested_category"] == "장소/대관"


async def test_agreeing_category_is_not_flagged():
    state = {"claim": ExpenseClaim(title="회식 저녁", amount=40_000, category="식비",
                                   date="2026-07-10", description="정기 모임 식사")}
    result = await classify_category(state)
    assert result["category_mismatch"] is False
    assert result["ai_suggested_category"] is None


async def test_no_keyword_hit_is_not_flagged():
    """키워드 미적중(확신 없음) → 비교하지 않음 — 과잉 보류 방지."""
    state = {"claim": ExpenseClaim(title="정체불명 지출", amount=10_000, category="식비",
                                   date="2026-07-10", description="")}
    result = await classify_category(state)
    assert result["category_mismatch"] is False


async def test_category_outside_catalog_is_skipped():
    """후보 밖 카테고리(구 어휘 체계) → 비교 불가, 건너뜀 — 오탐 회귀 방지."""
    result = await classify_category(_state("숙박/여행비"))   # 구 30종 시절 라벨
    assert result == {"category_source": "user"}


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
