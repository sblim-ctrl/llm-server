"""classify_category — 유형별 카테고리 자동 분류 (팀 확정 2026-07-10).

사용자가 지출 등록 시 카테고리를 선택하지 않으면, **그 모임 유형에 지정된
6개 카테고리 안에서만** AI가 골라 채운다. 카테고리 동적 추가 금지(백엔드 협의) —
후보 목록 밖의 값은 절대 만들지 않는다.

- 카탈로그: templates/category_catalog.yaml (tools/category_catalog.py가 로드)
- 사용자가 직접 고른 카테고리는 존중한다 — 라벨은 바꾸지 않는다. 단(2026-07-28
  결정) AI 분류가 **확신을 갖고 다르게 판단**하면 category_mismatch를 세워
  가드레일이 관리자 확인으로 보류시킨다 — 카테고리 위장으로 카테고리별 회칙
  한도를 회피하거나 지출 통계를 오염시키는 경로 차단. AI가 라벨을 고치는 게
  아니라(추천만 원칙, C2) 사람 확인으로 넘기는 것. AI 의견은 콜백
  suggestedCategory로 관리자에게 전달된다.
- 분류 실패는 심사를 막지 않는다: 유형별 fallback 카테고리로 채우고 진행,
  불일치 검사 실패는 비교 생략(사용자 분류 유지)

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
    DEFAULT_TEAM_TYPE, categories_for, classify_by_keywords, keyword_category_or_none,
)

logger = logging.getLogger(__name__)

# 사용자 카테고리와의 불일치를 인정하는 최소 확신도 — 이 미만이면 사용자가 맥락을
# 더 안다고 보고 비교하지 않는다 (과잉 보류 방지, adjudicate θ와 같은 값)
CATEGORY_MISMATCH_MIN_CONFIDENCE = 0.8


class CategoryPrediction(BaseModel):
    category: str
    confidence: float = 1.0


async def _check_category_mismatch(state: ReviewState, team_type: str,
                                   candidates: list[str], text: str) -> dict:
    """사용자 지정 카테고리 vs AI 분류 — 확신 있는 불일치만 표식.

    목 모드: 키워드 적중 시에만 비교(미적중 = 사용자와 일치 취급 — 오탐 방지).
    실모드: gpt-4o-mini 분류가 confidence≥0.8이고 후보 안의 값일 때만 비교.
    실패는 비교 생략(fail-open) — 이 검사가 심사를 막아선 안 된다.
    """
    claim = state["claim"]
    # 카탈로그 후보 밖의 카테고리는 다른 어휘 체계(구 백엔드 명칭 등) — 비교 자체가
    # 무의미하므로 건너뛴다(오탐 방지, 골든셋 실측으로 확인된 결함). 실서비스는
    # 카테고리가 유형별 고정 6개 드롭다운(동적 추가 금지)이라 항상 후보 안 = 검사 활성.
    if claim.category not in candidates:
        return {"category_source": "user"}
    kw = keyword_category_or_none(text, team_type)
    try:
        spec = load_prompt("classifier")
        pred, meta = await chat_structured(
            agent="classifier",
            system=spec.system_with_few_shot(),
            user=f"모임 유형: {team_type}\n카테고리 후보(이 중에서만 선택): "
                 f"{', '.join(candidates)}\n\n지출 내용: {text}",
            schema=CategoryPrediction,
            mock_response=CategoryPrediction(category=kw or claim.category,
                                             confidence=1.0 if kw else 0.0),
            mask_with=state.get("team_members") or [],
            prompt_version=spec.version,
        )
        ai_cat = pred.category if pred.category in candidates else kw
        confident = ai_cat is not None and pred.confidence >= CATEGORY_MISMATCH_MIN_CONFIDENCE
        mismatch = bool(confident and ai_cat != claim.category)
        return {"category_source": "user",
                "ai_suggested_category": ai_cat if mismatch else None,
                "category_mismatch": mismatch,
                "llm_meta": {"classifier": meta}}
    except Exception:
        logger.exception("category mismatch check failed — 비교 생략(사용자 분류 유지)")
        return {"category_source": "user"}


async def classify_category(state: ReviewState) -> dict:
    claim = state["claim"]
    team_type = state.get("team_type") or DEFAULT_TEAM_TYPE
    candidates = categories_for(team_type)
    if claim.category:
        # 사용자 선택 존중(라벨 불변) — 단 확신 있는 불일치면 가드레일이 보류
        return await _check_category_mismatch(
            state, team_type, candidates, f"{claim.title} {claim.description}")
    text = f"{claim.title} {claim.description}"

    llm_meta = {}
    try:
        spec = load_prompt("classifier")
        pred, meta = await chat_structured(
            agent="classifier",
            system=spec.system_with_few_shot(),
            user=f"모임 유형: {team_type}\n카테고리 후보(이 중에서만 선택): "
                 f"{', '.join(candidates)}\n\n지출 내용: {text}",
            schema=CategoryPrediction,
            mock_response=CategoryPrediction(category=classify_by_keywords(text, team_type)),
            mask_with=state.get("team_members") or [],
            prompt_version=spec.version,
        )
        llm_meta = {"classifier": meta}
        category = pred.category if pred.category in candidates \
            else classify_by_keywords(text, team_type)
    except Exception:
        logger.exception("classify_category failed — 유형 fallback으로 폴백")
        category = classify_by_keywords("", team_type)  # 미매칭 → fallback 반환

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai", "llm_meta": llm_meta}
