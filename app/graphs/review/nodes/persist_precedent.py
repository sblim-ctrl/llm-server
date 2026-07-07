"""persist_precedent — 판정 로그를 precedents에 저장 (REQ-042 판례 학습 루프의 입구).

TODO(4주차): 익명화(PIIMasker) + 임베딩 생성 후 저장. 지금은 임베딩 NULL.
"""
import logging

from app.db.pool import get_pool
from app.graphs.review.state import ReviewState

logger = logging.getLogger(__name__)


async def persist_precedent(state: ReviewState) -> dict:
    claim = state["claim"]
    summary = f"[{claim.category}] {claim.title} — {claim.amount:,}원"
    reasons = state.get("reasons")
    try:
        async with get_pool().connection() as conn:
            await conn.execute(
                """INSERT INTO precedents
                   (team_id, expense_summary, decision, decided_by, reason,
                    confidence, rule_version, model_version, prompt_version)
                   VALUES (%s, %s, %s, 'AGENT', %s, %s, %s, %s, %s)""",
                (state["team_id"], summary, state.get("verdict") or "escalate",
                 reasons.admin if reasons else None,
                 state.get("confidence"), state.get("rule_version"),
                 "mock", "review/v1"),
            )
    except Exception as e:
        # 판례 저장 실패가 심사 결과 자체를 무효화하면 안 됨
        logger.warning("persist_precedent skipped (non-fatal): %s", e)
    return {}
