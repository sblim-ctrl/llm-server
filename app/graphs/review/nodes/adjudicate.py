"""adjudicate — LLM 판정 합성 (§3.3 2단계). 가드레일 통과 건만 도달.

confidence < threshold → escalate. 사유 2종(요청자용/관리자용) 생성.
목 모드: 소견이 전부 pass면 approve(0.95), reject_candidate면 reject.
"""
import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.schemas.common import Reasons

logger = logging.getLogger(__name__)

PROMPT_VERSION = "adjudicator/v1"


class AdjudicationResult(BaseModel):
    verdict: str  # approve | reject
    confidence: float
    reason_requester: str
    reason_admin: str


def _mock_result(state: ReviewState) -> AdjudicationResult:
    claim = state["claim"]
    gate = state["gate_result"]
    budget = state["opinions"].get("budget")
    figures = budget.figures if budget else {}

    if gate is not None and gate.decision == "reject_candidate":
        return AdjudicationResult(
            verdict="reject", confidence=0.95,
            reason_requester="예산 잔액이 부족하여 승인이 어렵습니다.",
            reason_admin=f"예산 잔액 부족: {figures} (가드레일 reject 후보를 LLM이 확정, mock)",
        )
    return AdjudicationResult(
        verdict="approve", confidence=0.95,
        reason_requester=f"'{claim.title}' 지출이 회칙과 예산 기준을 충족하여 승인되었습니다.",
        reason_admin=(
            f"3개 심사관 전원 통과. 금액 {claim.amount:,}원, "
            f"승인 후 잔액 {figures.get('remaining_after', '?')}원 (mock)"
        ),
    )


async def adjudicate(state: ReviewState) -> dict:
    opinions = state["opinions"]
    result = await chat_structured(
        agent="adjudicator",
        system="(prompts/adjudicator/v1.yaml에서 로드)",
        user="\n".join(f"[{k}] {v.verdict}: {v.summary}" for k, v in opinions.items()),
        schema=AdjudicationResult,
        mock_response=_mock_result(state),
    )

    threshold = state["policy_params"].confidence_threshold
    verdict = result.verdict if result.confidence >= threshold else "escalate"
    if verdict not in ("approve", "reject", "escalate"):  # LLM 출력 방어
        verdict = "escalate"

    return {
        "verdict": verdict,
        "confidence": result.confidence,
        "reasons": Reasons(requester=result.reason_requester, admin=result.reason_admin),
    }


def route_after_adjudicate(state: ReviewState) -> str:
    return "escalate" if state["verdict"] == "escalate" else "execute_decision"
