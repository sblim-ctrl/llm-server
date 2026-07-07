"""escalate — 에스컬레이션 수렴 노드. 상태 변경 API는 호출하지 않는다 (콜백만, §7.1).

모든 실패·불일치·저신뢰의 기본 수렴처 (§8 fail-safe).
"""
from app.graphs.review.state import ReviewState
from app.schemas.common import Reasons


async def escalate(state: ReviewState) -> dict:
    gate = state.get("gate_result")
    mismatch = state.get("mismatch", [])

    if mismatch:
        detail = "영수증-청구 불일치: " + ", ".join(
            f"{m.field}(청구 {m.claimed} / 영수증 {m.receipt})" for m in mismatch)
    elif gate is not None and gate.triggered_rules:
        detail = "가드레일: " + ", ".join(gate.triggered_rules)
    else:
        detail = "판정 신뢰도 미달 또는 심사 실패"

    return {
        "verdict": "escalate",
        "reasons": Reasons(
            requester="관리자 확인이 필요한 건으로 분류되었습니다.",
            admin=f"에스컬레이션 사유 — {detail}",
        ),
    }
