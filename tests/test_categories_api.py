"""GET /v1/categories — 마법사 1단계 카테고리 조회.

목록 자체는 AI 생성이 아니라 templates/category_catalog.yaml의 고정값이다. 이 API의
값어치는 '원본이 하나'라는 데 있다 — 심사 때 분류기(classify_category)가 쓰는 카탈로그와
화면이 같은 곳을 본다. 그래서 여기서 검증할 것은 응답 형태보다 '분류기와 같은 목록을
주는가'다.
"""
import pytest

from app.api.categories import read_categories
from app.tools.category_catalog import categories_for, team_types


async def test_single_team_type():
    result = await read_categories(team_type="스터디")
    assert len(result.teams) == 1
    assert result.teams[0].team_type == "스터디"


async def test_all_team_types_when_omitted():
    result = await read_categories()
    assert [t.team_type for t in result.teams] == team_types()
    assert len(result.teams) == 5


@pytest.mark.parametrize("team_type", ["동아리/학생회", "스터디", "친목", "동호회", "회사"])
async def test_six_categories_per_type(team_type):
    """유형당 6개 고정 (팀 확정 2026-07-10)."""
    result = await read_categories(team_type=team_type)
    assert len(result.teams[0].categories) == 6


@pytest.mark.parametrize("team_type", ["동아리/학생회", "스터디", "친목", "동호회", "회사"])
async def test_matches_classifier_catalog(team_type):
    """분류기가 쓰는 목록과 정확히 같아야 한다 — 이 API의 존재 이유다.

    어긋나면 관리자가 화면에서 본 카테고리로 지출을 등록했는데 심사 쪽에서는
    모르는 값이 되는 상황이 생긴다.
    """
    result = await read_categories(team_type=team_type)
    assert result.teams[0].categories == categories_for(team_type)


async def test_fallback_is_one_of_the_categories():
    """분류 미적중 시 쓰는 기본값은 반드시 목록 안에 있어야 한다."""
    for team in (await read_categories()).teams:
        assert team.fallback in team.categories, f"{team.team_type}: fallback이 목록 밖"


async def test_unknown_team_type_is_404():
    """없는 유형은 조용히 기본값을 주지 않고 404로 알린다.

    categories_for()는 미지의 유형에 기본 유형을 돌려주는데(심사 fail-open), 조회
    API에서 그러면 오타를 눈치채지 못한 채 엉뚱한 목록을 화면에 그리게 된다.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await read_categories(team_type="동아리")  # 실제 값은 '동아리/학생회'
    assert exc.value.status_code == 404
    assert "동아리/학생회" in exc.value.detail  # 가능한 값을 알려준다
