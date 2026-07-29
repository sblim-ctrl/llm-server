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
    # 재현성(§5.3): 판례에 실제 사용한 모델·프롬프트 버전 기록 (adjudicator 미실행 경로는 기본값)
    adj = (state.get("llm_meta") or {}).get("adjudicator")
    try:
        await save_precedent(
            team_id=state["team_id"],
            summary=summarize_claim(claim),
            decision=state.get("verdict") or "escalate",
            # HITL 재개 경로: 관리자 결정은 ADMIN 판례로 저장 — 다음 심사의
            # 유사판례 검색·반복 개입 군집(detect_repeated_overrides)에 학습됨
            decided_by="ADMIN" if state.get("admin_decision") else "AGENT",
            reason=reasons.admin if reasons else None,
            confidence=state.get("confidence"),
            rule_version=state.get("rule_version"),
            model_version=adj.model if adj else "mock",
            prompt_version=(adj.prompt_version if adj and adj.prompt_version
                            else "review/v1"),
        )
    except Exception as e:
        # 판례 저장 실패가 심사 결과 자체를 무효화하면 안 됨
        logger.warning("persist_precedent skipped (non-fatal): %s", e)
    return {}
