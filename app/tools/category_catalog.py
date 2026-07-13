"""모임 유형별 카테고리 카탈로그 (팀 확정 2026-07-10 — 유형당 6개 고정).

classify_category(지출 분류)와 PolicyDrafter(카테고리 추천)가 공유.
카탈로그 수정은 templates/category_catalog.yaml만 — 코드 무수정.
"""
from functools import lru_cache
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "templates" / "category_catalog.yaml"
DEFAULT_TEAM_TYPE = "동아리/학생회"


@lru_cache
def load_catalog() -> dict:
    import yaml
    return yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))


def _entry(team_type: str) -> dict:
    catalog = load_catalog()
    return catalog.get(team_type) or catalog[DEFAULT_TEAM_TYPE]


def categories_for(team_type: str) -> list[str]:
    """유형별 카테고리 6개 이름 목록. 미지의 유형이면 기본 유형으로."""
    return [c["name"] for c in _entry(team_type)["categories"]]


def classify_by_keywords(text: str, team_type: str) -> str:
    """카탈로그 키워드 기반 결정적 분류 — 순수 함수 (단위 테스트 대상).

    yaml에 적힌 순서대로 먼저 매칭되는 카테고리 우선. 미매칭 시 유형별 fallback.
    """
    entry = _entry(team_type)
    lowered = text.lower()
    for cat in entry["categories"]:
        if any(k.lower() in lowered for k in cat.get("keywords", [])):
            return cat["name"]
    return entry["fallback"]
