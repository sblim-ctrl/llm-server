"""GET /v1/categories — 모임 유형별 지출 카테고리 조회 (마법사 1단계).

마법사 1단계 화면이 "모임 유형 ㅇㅇ에 맞는 지출 카테고리를 AI가 자동으로 추천해
드려요"라고 안내하는데, 그 목록을 줄 통로가 없었다. 종전에는 3단계 AI 초안
(`POST /v1/policy-draft`) 응답에만 실려 있어서 1단계에서는 보여줄 수가 없었다.

백엔드가 목록을 따로 갖고 있어도 화면은 뜨지만, 같은 목록이 두 곳에 생겨 어긋난다.
이 카탈로그는 심사 때 AI 분류기(classify_category)가 쓰는 것과 같은 원본이라,
여기서 조회하면 화면과 심사 기준이 항상 일치한다.

목록은 유형당 6개 고정이며 AI가 새로 만들지 않는다(팀 확정 2026-07-10). 카탈로그
수정은 `templates/category_catalog.yaml`만 고치면 되고 코드는 건드리지 않는다.
"""
from fastapi import APIRouter, HTTPException

from app.schemas.categories import CategoryCatalog, TeamCategories
from app.tools.category_catalog import categories_for, fallback_for, team_types

router = APIRouter(prefix="/v1", tags=["categories"])


@router.get("/categories", response_model=CategoryCatalog,
            summary="모임 유형별 지출 카테고리 조회")
async def read_categories(team_type: str | None = None) -> CategoryCatalog:
    """유형별 카테고리 6개를 돌려준다.

    `team_type`을 주면 해당 유형 하나만, 생략하면 5개 유형 전부 준다. 마법사 1단계는
    유형이 이미 정해진 시점이므로 보통 하나만 조회하면 되고, 전체 조회는 백엔드가
    캐시해 두고 쓰실 때를 위한 것이다.

    `fallback`은 지출 분류가 어느 카테고리에도 안 걸릴 때 쓰는 기본값이다. 화면에
    노출하지 않으셔도 되지만, 저희가 그 값으로 분류할 수 있다는 점은 알고 계시는 편이
    좋다.
    """
    known = team_types()
    if team_type is not None and team_type not in known:
        raise HTTPException(
            status_code=404,
            detail=f"알 수 없는 모임 유형: {team_type} (가능한 값: {', '.join(known)})",
        )
    targets = [team_type] if team_type else known
    return CategoryCatalog(teams=[
        TeamCategories(team_type=t, categories=categories_for(t), fallback=fallback_for(t))
        for t in targets
    ])
