"""persist_precedent — 판정 로그를 precedents에 저장 (REQ-042 판례 학습 루프의 입구).

저장 전 PIIMasker 익명화 + 임베딩 생성 (precedent_store 헬퍼가 처리).
"""
import logging

from app.graphs.review.state import ReviewState
from app.tools.precedent_store import save_precedent, summarize_claim

logger = logging.getLogger(__name__)


async def persist_precedent(state: ReviewState) -> dict:
    claim = state["claim"]
    reasons = state.get("reasons")
    try:
        await save_precedent(
            team_id=state["team_id"],
            summary=summarize_claim(claim),
            decision=state.get("verdict") or "escalate",
            decided_by="AGENT",
            reason=reasons.admin if reasons else None,
            confidence=state.get("confidence"),
            rule_version=state.get("rule_version"),
        )
    except Exception as e:
        # 판례 저장 실패가 심사 결과 자체를 무효화하면 안 됨
        logger.warning("persist_precedent skipped (non-fatal): %s", e)
    return {}
