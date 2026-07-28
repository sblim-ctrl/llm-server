"""유형별 카테고리 분류 테스트 (팀 확정 2026-07-10 — 유형당 6개 고정)."""
import pytest

from app.graphs.review.nodes.classify_category import classify_category
from app.schemas.common import ExpenseClaim
from app.tools.category_catalog import categories_for, classify_by_keywords, load_catalog

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]


def test_catalog_has_five_types_six_categories_each():
    catalog = load_catalog()
    assert set(catalog.keys()) == set(TEAM_TYPES)
    for team_type, entry in catalog.items():
        assert len(entry["categories"]) == 6, team_type
        names = categories_for(team_type)
        assert entry["fallback"] in names, f"{team_type} fallback이 목록 밖"


@pytest.mark.parametrize("team_type,text,expected", [
    ("동아리/학생회", "축제 부스 현수막 제작", "행사/프로그램비"),  # 축제 키워드 우선
    ("동아리/학생회", "신입생 홍보 포스터", "홍보/콘텐츠비"),
    ("스터디", "파이썬 교재 2권", "교재/자료비"),
    ("스터디", "스터디룸 4시간 대관", "공간/대관비"),
    ("친목", "볼링장 2게임", "레저/액티비티비"),
    ("친목", "생일 선물 구입", "선물/기념비"),
    ("동호회", "셔틀콕 1박스", "장비/용품비"),
    ("동호회", "지역 리그 참가비", "대회/참가비"),
    ("회사", "야근 택시비", "교통/출장비"),
    ("회사", "노션 팀 구독", "업무도구/소프트웨어비"),
])
def test_keyword_classification_per_type(team_type, text, expected):
    assert classify_by_keywords(text, team_type) == expected


def test_same_text_maps_to_type_specific_category():
    """같은 지출이라도 모임 유형에 따라 그 유형의 카테고리로 분류된다."""
    assert classify_by_keywords("회식 저녁", "친목") == "식비/모임비"
    assert classify_by_keywords("회식 저녁", "회사") == "식대/회식비"
    assert classify_by_keywords("회식 저녁", "동호회") == "식비/간식비"


def test_no_match_falls_back_to_type_default():
    assert classify_by_keywords("정체불명 지출", "스터디") == "실습/프로젝트비"
    assert classify_by_keywords("정체불명 지출", "회사") == "비품/소모품비"


def test_unknown_team_type_uses_default_catalog():
    assert classify_by_keywords("현수막", "미지의유형") == "홍보/콘텐츠비"


def _state(category: str, team_type: str = "친목") -> dict:
    return {"team_type": team_type,
            "claim": ExpenseClaim(title="펜션 예약", amount=90_000, category=category,
                                  date="2026-07-10", description="여름 여행 숙소")}


async def test_empty_category_gets_classified_within_team_catalog():
    result = await classify_category(_state(""))
    assert result["category_source"] == "ai"
    assert result["claim"].category == "숙박/여행비"
    assert result["claim"].category in categories_for("친목")


async def test_user_category_is_respected():
    result = await classify_category(_state("장소/예약비"))
    assert result["category_source"] == "user"
    assert "claim" not in result  # claim 미변경


# ── 사용자 카테고리 vs AI 분류 불일치 (2026-07-28 결정 — 가드레일 category_mismatch) ──

from app.tools.category_catalog import keyword_category_or_none  # noqa: E402


def test_keyword_or_none_returns_none_without_hit():
    """확신(키워드 적중) 없으면 None — fallback을 돌려주면 전건 오탐이 된다."""
    assert keyword_category_or_none("정체불명 지출", "친목") is None
    assert keyword_category_or_none("펜션 예약 숙소", "친목") == "숙박/여행비"


async def test_user_category_agreeing_with_ai_passes():
    """사용자 선택과 AI 분류가 일치 → 불일치 아님."""
    state = {"team_type": "친목",
             "claim": ExpenseClaim(title="회식 저녁", amount=40_000, category="식비/모임비",
                                   date="2026-07-10", description="정기 모임 식사")}
    result = await classify_category(state)
    assert result["category_source"] == "user"
    assert result["category_mismatch"] is False
    assert result["ai_suggested_category"] is None


async def test_user_category_confident_disagreement_flags_mismatch():
    """숙박 지출을 식비로 등록 → 확신 있는 불일치 → 가드레일 보류 대상 + AI 의견 전달."""
    state = {"team_type": "친목",
             "claim": ExpenseClaim(title="펜션 예약", amount=90_000, category="식비/모임비",
                                   date="2026-07-10", description="여름 여행 숙소")}
    result = await classify_category(state)
    assert result["category_source"] == "user"       # 라벨은 사용자 것 유지
    assert "claim" not in result                     # claim 미변경 (존중 원칙)
    assert result["category_mismatch"] is True
    assert result["ai_suggested_category"] == "숙박/여행비"


async def test_user_category_without_keyword_hit_not_flagged():
    """키워드 미적중(확신 없음) → 비교하지 않음 — 과잉 보류 방지."""
    state = {"team_type": "친목",
             "claim": ExpenseClaim(title="정체불명 지출", amount=10_000, category="식비/모임비",
                                   date="2026-07-10", description="")}
    result = await classify_category(state)
    assert result["category_source"] == "user"
    assert result["category_mismatch"] is False


async def test_user_category_outside_catalog_vocabulary_skipped():
    """후보 6개 밖의 카테고리(다른 어휘 체계) → 비교 불가, 건너뜀 — 골든셋 오탐 회귀 방지."""
    state = {"team_type": "친목",
             "claim": ExpenseClaim(title="펜션 예약", amount=90_000, category="도서",
                                   date="2026-07-10", description="여름 여행 숙소")}
    result = await classify_category(state)
    assert result == {"category_source": "user"}
