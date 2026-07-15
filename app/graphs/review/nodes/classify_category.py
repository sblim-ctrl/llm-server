"""classify_category — 유형별 카테고리 자동 분류 (팀 확정 2026-07-10).

사용자가 지출 등록 시 카테고리를 선택하지 않으면, **그 모임 유형에 지정된
6개 카테고리 안에서만** AI가 골라 채운다. 카테고리 동적 추가 금지(백엔드 협의) —
후보 목록 밖의 값은 절대 만들지 않는다.

- 카탈로그: templates/category_catalog.yaml (tools/category_catalog.py가 로드)
- 사용자가 직접 고른 카테고리는 존중하고 건드리지 않는다
- 분류 실패는 심사를 막지 않는다: 유형별 fallback 카테고리로 채우고 진행

목 모드: 카탈로그의 키워드 규칙 기반 결정적 분류.
실모드: gpt-4o-mini 구조화 출력 — 후보 6개를 프롬프트에 강제하고,
        목록 밖 답변은 코드가 키워드 분류로 교정 (환각 카테고리 차단).
"""
import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.tools.category_catalog import (
    DEFAULT_TEAM_TYPE, categories_for, classify_by_keywords,
)

logger = logging.getLogger(__name__)


class CategoryPrediction(BaseModel):
    category: str
    confidence: float = 1.0


async def classify_category(state: ReviewState) -> dict:
    claim = state["claim"]
    if claim.category:
        return {"category_source": "user"}

    team_type = state.get("team_type") or DEFAULT_TEAM_TYPE
    candidates = categories_for(team_type)
    text = f"{claim.title} {claim.description}"

    try:
        pred = await chat_structured(
            agent="classifier",
            system=load_prompt("classifier").system_with_few_shot(),
            user=f"모임 유형: {team_type}\n카테고리 후보(이 중에서만 선택): "
                 f"{', '.join(candidates)}\n\n지출 내용: {text}",
            schema=CategoryPrediction,
            mock_response=CategoryPrediction(category=classify_by_keywords(text, team_type)),
        )
        category = pred.category if pred.category in candidates \
            else classify_by_keywords(text, team_type)
    except Exception:
        logger.exception("classify_category failed — 유형 fallback으로 폴백")
        category = classify_by_keywords("", team_type)  # 미매칭 → fallback 반환

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai"}
