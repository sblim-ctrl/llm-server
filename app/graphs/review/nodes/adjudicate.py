"""adjudicate — LLM 판정 합성 (§3.3 2단계). 가드레일 통과 건만 도달.

confidence < threshold → escalate. 사유 2종(요청자용/관리자용) 생성.
목 모드: 소견이 전부 pass면 approve(0.95), reject_candidate면 reject.
"""

import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import Opinion, Reasons

logger = logging.getLogger(__name__)

# 소견별 근거 블록 상한 — 프롬프트 비대 방어 (RAG top-k·판례 검색 상한보다 여유 있게)
_MAX_LIST_ITEMS = 5
_MAX_ITEM_CHARS = 300


def build_adjudication_user(opinions: dict[str, Opinion], threshold: float) -> str:
    """심사관 소견 → adjudicator user 메시지 (순수 함수).

    verdict·summary 외에 각 소견의 evidence(조항)·figures(수치)·similar_cases(판례)를
    있는 것만 들여쓰기 블록으로 전달한다 — 프롬프트의 "제공된 근거만 인용" 규칙이
    실제로 충족 가능하려면 근거가 입력에 있어야 한다. 임계값은 팀별 가변
    (policy_params.confidence_threshold)이라 첫 줄로 주입한다 (로더에 템플릿 치환 없음).
    adjudicator/v3+ few_shot의 input이 이 형식을 미러링한다 — 형식 변경 시 함께 갱신.
    """
    lines = [
        f"판정 임계값: {threshold:g} — confidence가 이 값 미만이면 시스템이 자동 에스컬레이션합니다.",
        "",
    ]
    for name, op in opinions.items():
        lines.append(f"[{name}] {op.verdict}: {op.summary}")
        if op.evidence:
            lines.append("  근거 조항:")
            lines += [f"  - {e[:_MAX_ITEM_CHARS]}" for e in op.evidence[:_MAX_LIST_ITEMS]]
        if op.figures:
            lines.append("  수치: " + " / ".join(f"{k}={v:,}" for k, v in op.figures.items()))
        if op.similar_cases:
            lines.append("  유사 판례:")
            lines += [f"  - {c[:_MAX_ITEM_CHARS]}" for c in op.similar_cases[:_MAX_LIST_ITEMS]]
    return "\n".join(lines)


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
            verdict="reject",
            confidence=0.95,
            reason_requester="예산 잔액이 부족하여 승인이 어렵습니다.",
            reason_admin=f"예산 잔액 부족: {figures} (가드레일 reject 후보를 LLM이 확정, mock)",
        )
    return AdjudicationResult(
        verdict="approve",
        confidence=0.95,
        reason_requester=f"'{claim.title}' 지출이 회칙과 예산 기준을 충족하여 승인되었습니다.",
        reason_admin=(
            f"3개 심사관 전원 통과. 금액 {claim.amount:,}원, "
            f"승인 후 잔액 {figures.get('remaining_after', '?')}원 (mock)"
        ),
    )


async def adjudicate(state: ReviewState) -> dict:
    opinions = state["opinions"]
    threshold = state["policy_params"].confidence_threshold
    spec = load_prompt("adjudicator")
    result, meta = await chat_structured(
        agent="adjudicator",
        system=spec.system_with_few_shot(),
        user=build_adjudication_user(opinions, threshold),
        schema=AdjudicationResult,
        mock_response=_mock_result(state),
        mask_with=state.get("team_members") or [],
        prompt_version=spec.version,
    )

    verdict = result.verdict if result.confidence >= threshold else "escalate"
    if verdict not in ("approve", "reject", "escalate"):  # LLM 출력 방어
        verdict = "escalate"

    return {
        "verdict": verdict,
        "confidence": result.confidence,
        "reasons": Reasons(requester=result.reason_requester, admin=result.reason_admin),
        "llm_meta": {"adjudicator": meta},
    }


def route_after_adjudicate(state: ReviewState) -> str:
    return "escalate" if state["verdict"] == "escalate" else "execute_decision"
