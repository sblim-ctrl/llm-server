"""escalate — 에스컬레이션 수렴 노드. 상태 변경 API는 호출하지 않는다 (콜백만, §7.1).

모든 실패·불일치·저신뢰의 기본 수렴처 (§8 fail-safe).

HITL(사람 개입, 강의 06-02): 데모·관측 경로(hitl_enabled=True, 체크포인터 필수)에선
여기서 interrupt()로 그래프를 멈추고, 관리자 결정(승인/반려)이 오면 같은 지점부터
재개해 콜백·판례 저장까지 이어간다 — 관리자 결정은 decided_by='ADMIN' 판례로
저장돼 다음 심사의 유사판례 검색에 학습된다(REQ-042 루프의 사람 축).
워커 경로는 hitl_enabled가 없으므로 기존과 동일(멈춤 없이 escalate 확정).
AI는 여전히 실행 주체가 아니다 — 결정은 사람이 내리고, 그래프는 그 결정을
기록·전달할 뿐이다 (C2 추천만 원칙과 정합).
"""
from langgraph.types import interrupt

from app.graphs.review.state import ReviewState
from app.schemas.common import Reasons


def _escalation_detail(state: ReviewState) -> str:
    gate = state.get("gate_result")
    mismatch = state.get("mismatch", [])
    if mismatch:
        return "영수증-청구 불일치: " + ", ".join(
            f"{m.field}(청구 {m.claimed} / 영수증 {m.receipt})" for m in mismatch)
    if gate is not None and gate.triggered_rules:
        return "가드레일: " + ", ".join(gate.triggered_rules)
    return "판정 신뢰도 미달 또는 심사 실패"


async def escalate(state: ReviewState) -> dict:
    detail = _escalation_detail(state)

    if state.get("hitl_enabled"):
        claim = state.get("claim")
        # 그래프가 여기서 멈춘다 — 재개 시 interrupt()가 관리자 결정을 반환
        decision = interrupt({
            "reason": detail,
            "claim": {"title": claim.title, "amount": claim.amount,
                      "category": claim.category} if claim else None,
            "confidence": state.get("confidence"),
            "opinions": {k: {"verdict": o.verdict, "summary": o.summary}
                         for k, o in (state.get("opinions") or {}).items()},
        })
        d = (str(decision.get("decision", "")).lower()
             if isinstance(decision, dict) else "")
        if d in ("approve", "reject"):
            note = (str(decision.get("reason") or "").strip()
                    if isinstance(decision, dict) else "")
            label = "승인" if d == "approve" else "반려"
            return {
                "verdict": d,
                "admin_decision": {"decision": d, "reason": note},
                "reasons": Reasons(
                    # 요청자용엔 관리자 메모를 싣지 않는다 — 내부 수치 노출 방지 (§3.3)
                    requester=f"관리자 검토 결과 {label}되었습니다.",
                    admin=f"관리자 직접 결정({label}) — 사유: {note or '기재 없음'}"
                          f" / 원 에스컬레이션: {detail}",
                ),
            }
        # 이상값(승인/반려 아님) → 안전 방향: 보류 유지 (§8)

    return {
        "verdict": "escalate",
        "reasons": Reasons(
            requester="관리자 확인이 필요한 건으로 분류되었습니다.",
            admin=f"에스컬레이션 사유 — {detail}",
        ),
    }
