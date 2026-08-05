"""GET /v1/categories — 지출 카테고리 조회 (마법사 1단계).

마법사 1단계 화면이 "AI가 지출 카테고리를 추천해 드려요"라고 안내하는데, 그 목록을
줄 통로다. 종전에는 3단계 AI 초안(`POST /v1/policy-draft`) 응답에만 실려 있어서
1단계에서는 보여줄 수가 없었다.

목록은 **전역 9종 고정**이며 AI가 새로 만들지 않는다(풀스택 협의 2026-08-04).
그럼에도 API로 여는 이유는 심사 때 지출을 분류하는 카탈로그와 같은 원본이기
때문이다. 백엔드가 목록을 따로 갖고 있어도 화면은 뜨지만, 같은 목록이 두 곳에
생기면 어긋난다. 어긋나도 조용히 망가진다 — 카탈로그 밖 카테고리가 오면 심사 쪽
분류 검증(category_mismatch)이 에러 없이 건너뛴다.

카탈로그 수정은 `templates/category_catalog.yaml`만 고치면 되고 코드는 안 건드린다.
"""
from fastapi import APIRouter

from app.schemas.categories import CategoryCatalog
from app.tools.category_catalog import all_categories, fallback_category, load_catalog

router = APIRouter(prefix="/v1", tags=["categories"])


@router.get("/categories", response_model=CategoryCatalog,
            summary="지출 카테고리 조회 (전역 9종)")
async def read_categories() -> CategoryCatalog:
    """카테고리 9종을 돌려준다. 모임 유형과 무관하게 항상 같은 목록이다.

    계산이 없는 고정값이라 **매번 부르실 필요가 없다.** 서버 기동 시나 배포 시 한 번
    받아 캐시하시면 된다. 다만 캐시도 사본이라 목록이 바뀌면 어긋나므로, 응답의
    `version`을 함께 저장해 두시고 값이 달라졌을 때만 갱신하시면 된다.

    `fallback`은 지출 분류가 어느 카테고리에도 안 걸릴 때 저희가 쓰는 값이다
    (항상 `기타`). 화면에 노출하지 않으셔도 되지만, 저희가 그 값으로 분류할 수
    있다는 점은 알고 계시는 편이 좋다.

    정렬 순서는 저희 분류 우선순위다 — 화면에서는 원하시는 순서로 바꾸셔도 된다.
    """
    return CategoryCatalog(
        categories=all_categories(),
        fallback=fallback_category(),
        version=load_catalog()["version"],
    )
