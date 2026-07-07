"""precedent_auditor — 판례·이상탐지 심사관 (병렬).

TODO(4주차): search_precedents(pgvector) + get_expense_history로 중복 청구 탐지.
목 모드: 판례 없음 → 통과 소견.
"""
import logging

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.schemas.common import Opinion

logger = logging.getLogger(__name__)

PROMPT_VERSION = "precedent_auditor/v1"


async def precedent_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        # TODO: cases = await search_precedents(state["team_id"], embed(claim))
        # TODO: history = await get_expense_history(state["team_id"], ...)  # 중복 청구 탐지
        opinion = await chat_structured(
            agent="precedent_auditor",
            system="(prompts/precedent_auditor/v1.yaml에서 로드)",
            user=claim.model_dump_json(),
            schema=Opinion,
            mock_response=Opinion(
                auditor="precedent", verdict="pass",
                summary="유사 판례 없음, 중복 청구 패턴 미탐지 (mock)",
            ),
        )
        opinion.auditor = "precedent"
        return {"opinions": {"precedent": opinion}}
    except Exception:
        logger.exception("precedent_auditor failed")
        return {"opinions": {"precedent": Opinion(
            auditor="precedent", verdict="error", summary="판례 심사 실패",
        )}}
