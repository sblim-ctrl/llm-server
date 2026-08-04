"""GET /v1/categories — 마법사 1단계 카테고리 조회.

목록 자체는 AI 생성이 아니라 templates/category_catalog.yaml의 고정값이다. 이 API의
값어치는 '원본이 하나'라는 데 있다 — 심사 때 분류기(classify_category)가 쓰는 카탈로그와
화면이 같은 곳을 본다. 그래서 여기서 검증할 것은 응답 형태보다 '분류기와 같은 목록을
주는가'다.
"""
from app.api.categories import read_categories
from app.graphs.writers.policy_draft import all_categories as draft_categories
from app.tools.category_catalog import all_categories, fallback_category


async def test_returns_the_global_nine():
    result = await read_categories()
    assert len(result.categories) == 9
    assert result.categories == all_categories()


async def test_fallback_is_other_and_inside_the_list():
    result = await read_categories()
    assert result.fallback == "기타"
    assert result.fallback in result.categories


async def test_exposes_version_so_backend_can_cache():
    """고정값이라 매번 부를 필요가 없다 — 캐시 갱신 판단용 판 번호를 함께 준다."""
    result = await read_categories()
    assert isinstance(result.version, int) and result.version >= 1


async def test_same_source_as_classifier_and_draft():
    """화면·심사·초안이 같은 원본을 본다 — 목록이 갈리면 조용히 망가진다."""
    result = await read_categories()
    assert result.categories == all_categories() == draft_categories()
    assert fallback_category() in result.categories


async def test_no_duplicates():
    result = await read_categories()
    assert len(set(result.categories)) == len(result.categories)
