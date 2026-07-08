"""classify_category — 예산 카테고리 자동 분류 (팀 합의 사항, ADR-1 '분류=gpt-4o-mini').

카테고리가 비어 있는 청구만 분류해서 채운다 — 사용자가 직접 고른 카테고리는
존중하고 건드리지 않는다(분류 결과와 다르더라도 판정은 회칙·예산 심사가 가린다).

분류 실패는 심사를 막지 않는다: '기타'로 채우고 진행 — 예산 심사에서 해당
카테고리 한도가 없으면 어차피 보수적으로 처리된다.

목 모드: 키워드 규칙 기반 결정적 분류 (classify_by_keywords — 단위 테스트 대상).
실모드: gpt-4o-mini 구조화 출력.
"""
import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured

logger = logging.getLogger(__name__)

PROMPT_VERSION = "classifier/v1"

CATEGORIES = ["식비", "다과", "도서", "교육", "대관", "비품", "용품",
              "교통", "행사", "홍보", "여가", "기타"]

# 키워드 → 카테고리 (목 모드·폴백용 결정적 규칙, 먼저 매칭되는 것 우선)
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("회식", "식사", "점심", "저녁", "밥", "치킨"), "식비"),
    (("간식", "다과", "커피", "음료", "케이크"), "다과"),
    (("교재", "책", "도서", "서적"), "도서"),
    (("강의", "수강", "구독", "인강", "강좌"), "교육"),
    (("대관", "스터디룸", "회의실", "코트", "펜션"), "대관"),
    (("마커", "포스트잇", "문구", "사무", "프린트", "제본", "비품"), "비품"),
    (("셔틀콕", "라켓", "유니폼", "장비", "공"), "용품"),
    (("택시", "버스", "교통", "주차", "톨게이트", "기차"), "교통"),
    (("MT", "엠티", "행사", "대회", "축제", "참가비"), "행사"),
    (("현수막", "포스터", "홍보", "배너"), "홍보"),
    (("보드게임", "영화", "노래방", "게임"), "여가"),
]


class CategoryPrediction(BaseModel):
    category: str
    confidence: float = 1.0


def classify_by_keywords(text: str) -> str:
    """결정적 키워드 분류 — 순수 함수 (단위 테스트 대상). 미매칭 시 '기타'."""
    lowered = text.lower()
    for keywords, category in _KEYWORD_RULES:
        if any(k.lower() in lowered for k in keywords):
            return category
    return "기타"


async def classify_category(state: ReviewState) -> dict:
    claim = state["claim"]
    if claim.category:
        return {"category_source": "user"}

    text = f"{claim.title} {claim.description}"
    try:
        pred = await chat_structured(
            agent="classifier",
            system="(prompts/classifier/v1.yaml에서 로드)",
            user=f"카테고리 후보: {', '.join(CATEGORIES)}\n\n지출 내용: {text}",
            schema=CategoryPrediction,
            mock_response=CategoryPrediction(category=classify_by_keywords(text)),
        )
        category = pred.category if pred.category in CATEGORIES else "기타"
    except Exception:
        logger.exception("classify_category failed — '기타'로 폴백")
        category = "기타"

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai"}
