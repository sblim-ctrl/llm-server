"""카테고리 조회 계약 — GET /v1/categories (마법사 1단계).

전역 9종으로 통일되면서(풀스택 협의 2026-08-04) 모임 유형 축이 없어졌다. 종전
응답은 `teams[]` 배열에 유형별 6종을 담았는데, 이제 목록이 하나뿐이라 평평해졌다.
"""

from pydantic import BaseModel


class CategoryCatalog(BaseModel):
    # 전역 9종 고정 — AI가 새 값을 만들지 않는다. 백엔드 expenses.category ENUM과
    # 같은 값이며, 정렬 순서는 분류 우선순위(카탈로그 정의 순서)다.
    categories: list[str]
    # 분류가 어느 카테고리에도 안 걸릴 때 쓰는 값. 항상 '기타'이며 categories 안에 있다.
    fallback: str
    # 카탈로그 판 번호 — 백엔드가 목록을 캐시할 때 갱신 필요 여부를 이 값으로 판단한다.
    version: int
