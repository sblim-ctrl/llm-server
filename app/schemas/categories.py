"""카테고리 조회 계약 — GET /v1/categories (마법사 1단계)."""

from pydantic import BaseModel


class TeamCategories(BaseModel):
    team_type: str
    categories: list[str]  # 유형당 6개 고정 — AI가 새로 만들지 않는다
    # 지출 분류가 어느 카테고리에도 안 걸릴 때 쓰는 기본값
    fallback: str


class CategoryCatalog(BaseModel):
    teams: list[TeamCategories]
