"""mismatch_gate — 영수증-청구 대조 (REQ-028). 순수 비교, 부수효과 없음."""
from app.graphs.review.state import ReviewState
from app.schemas.common import Mismatch


async def mismatch_gate(state: ReviewState) -> dict:
    receipt = state.get("receipt_data")
    claim = state["claim"]
    mismatches: list[Mismatch] = []

    if receipt is None or not receipt.parse_ok:
        # 판독 불능은 mismatch가 아니라 가드레일에서 에스컬레이션 처리 (§8)
        return {"mismatch": mismatches}

    if receipt.amount is not None and receipt.amount != claim.amount:
        mismatches.append(Mismatch(field="amount",
                                   claimed=str(claim.amount), receipt=str(receipt.amount)))
    if receipt.date is not None and receipt.date != claim.date:
        mismatches.append(Mismatch(field="date", claimed=claim.date, receipt=receipt.date))

    return {"mismatch": mismatches}


AUDITORS = ["rule_auditor", "budget_auditor", "precedent_auditor"]


def route_after_mismatch(state: ReviewState) -> str | list[str]:
    """조건부 엣지: 불일치 → escalate로 직행, 일치 → 3-심사관 병렬 fan-out (§3.2)."""
    return "escalate" if state.get("mismatch") else AUDITORS
