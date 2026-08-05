"""지출 카테고리 카탈로그 — 전역 9종 (풀스택 협의 2026-08-04 확정).

classify_category(지출 분류)와 PolicyDrafter(카테고리 추천), GET /v1/categories가
같은 원본을 본다. 카탈로그 수정은 templates/category_catalog.yaml만 — 코드 무수정.

**모임 유형 축이 사라졌다.** 종전에는 유형별 6종(5유형 30종)이었으나 백엔드
expenses.category ENUM과 교집합이 0이라 저장이 안 됐고, 협의로 전역 9종에 맞췄다.
유형은 회칙 초안 템플릿(policy_templates.yaml)에서는 여전히 쓰이므로 없어진 게
아니라 **카테고리 선택에서만 빠진 것**이다.

**카탈로그 name = ENUM 저장값**이다(2026-08-05 확정). 백엔드가 ENUM에 2종을 더해
9종으로 확장해 주기로 하면서 양쪽 목록이 같아졌다. 슬래시를 ENUM에 넣을 수 없어
`IT_인프라`·`장소_대관`·`행사_활동`은 밑줄로 적고, 화면의 슬래시 표기는 프론트가
출력할 때 만든다 — 서버·프롬프트·콜백은 전부 밑줄 값 하나만 쓴다.
"""
from functools import lru_cache
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "templates" / "category_catalog.yaml"


@lru_cache
def load_catalog() -> dict:
    import yaml
    return yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))


def all_categories() -> list[str]:
    """카테고리 9종 이름 목록 — YAML 정의 순서(분류 우선순위)를 그대로 따른다."""
    return [c["name"] for c in load_catalog()["categories"]]


def fallback_category() -> str:
    """분류가 어느 카테고리에도 안 걸렸을 때 쓰는 값 — '기타'.

    실제 카테고리가 아니라 '기타'인 것이 중요하다. 못 알아본 지출을 실제 카테고리에
    섞으면 통계가 조용히 오염되는데, '기타'로 두면 미분류가 눈에 보인다.
    """
    return load_catalog()["fallback"]


def keyword_category_or_none(text: str) -> str | None:
    """키워드가 실제로 적중한 경우에만 카테고리 반환 — 미적중이면 None.

    사용자 지정 카테고리와의 불일치 비교용(가드레일 category_mismatch): fallback을
    돌려주면 키워드가 안 잡히는 모든 청구가 '불일치'로 오탐되므로, 확신(키워드
    적중)이 있을 때만 비교 대상이 된다. 순수 함수 (단위 테스트 대상).

    매칭은 부분 문자열이고 YAML에 적힌 순서대로 먼저 걸리는 카테고리가 이긴다.
    """
    lowered = text.lower()
    for cat in load_catalog()["categories"]:
        if any(k.lower() in lowered for k in cat.get("keywords", [])):
            return cat["name"]
    return None


def classify_by_keywords(text: str) -> str:
    """카탈로그 키워드 기반 결정적 분류 — 순수 함수. 미매칭 시 '기타'."""
    return keyword_category_or_none(text) or fallback_category()
