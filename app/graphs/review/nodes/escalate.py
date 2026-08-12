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

from app.graphs.review.nodes.mismatch_gate import FIELD_LABELS
from app.graphs.review.state import ReviewState
from app.schemas.common import Reasons
from app.tools.policy_params import effective_auto_approve_limit


# 가드레일 규칙 → 관리자 화면 문구.
#
# **규칙 식별자 자체는 바꾸지 않는다.** 골든셋의 `expected_gate_includes`와 Trajectory
# 채점이 이 이름으로 매칭하므로 바꾸면 평가 계약이 깨진다 — 2026-08-10 기준 골든 케이스
# 50건이 규칙 이름 6종을 직접 못박고 있다(골든셋이 늘면 같이 는다. 인용 전에 셀 것).
# 사람이 읽는 자리에서만 옮긴다.
#
# `over_auto_approve_limit`과 `over_force_escalation_amount`가 **같은 문구**인 것은
# 의도다. 2026-08-05 마법사 2단계 화면 개편으로 금액 칸이 하나가 되면서 두 값은 같은
# 금액이 됐다(`policy_params.effective_auto_approve_limit`의 min은 컬럼 삭제 전 저장된
# 값이 남은 팀을 위한 안전망일 뿐이다). 둘이 함께 걸려도 관리자에게는 한 줄이어야
# 하므로 아래에서 같은 문구를 접는다.
_RULE_LABELS = {
    "auto_approve_disabled": "AI 자동 판정이 꺼져 있음",
    "receipt_unreadable": "영수증 판독 실패",
    "receipt_mismatch": "영수증과 청구 내용 불일치",
    "rule_violation": "회칙 위반",
    "rule_ambiguous": "회칙 해석이 애매함",
    "precedent_suspicion": "유사 판례에 의심 신호",
    "budget_insufficient": "예산 잔액 부족",
    "over_auto_approve_limit": "관리자 승인이 필요한 금액",
    "over_force_escalation_amount": "관리자 승인이 필요한 금액",
}
_RULE_PREFIX_LABELS = {
    "missing_opinion": "심사관 소견 누락",
    "auditor_failed": "심사관 실행 실패",
}
_AUDITOR_LABELS = {"rule": "회칙", "budget": "예산", "precedent": "판례", "evidence": "증빙"}

# 청구 금액이 자동 승인 기준 이상이라 걸리는 두 규칙. 이것만으로 보류된 건은
# 회칙·예산 위반이 아니라 '금액이 커서'가 유일한 사유라, 사용자에게 그 사실을
# 그대로 밝힌다(guardrail_gate에서 이 둘은 항상 마지막에 append되고 같은 라벨로 접힌다).
_AMOUNT_RULES = frozenset({"over_auto_approve_limit", "over_force_escalation_amount"})


def _amount_context(state: ReviewState) -> str:
    """금액 규칙으로 걸린 건의 청구액·기준액을 관리자용 괄호 문구로 (순수 함수).

    청구/설정 정보가 없으면 빈 문자열, 실효 한도가 0 이하(전건 수동 모드)면
    '0원 이상' 대신 팀 설정 안내를 준다.
    """
    claim = state.get("claim")
    policy = state.get("policy_params")
    if claim is None or policy is None:
        return ""
    limit = effective_auto_approve_limit(policy)
    if limit <= 0:
        return "(팀 설정: 모든 지출 관리자 확인)"
    return f"(청구 {claim.amount:,}원, 기준 {limit:,}원 이상)"


def describe_rules(rules: list[str]) -> str:
    """가드레일 규칙 목록 → 관리자가 읽는 한 줄 (순수 함수).

    종전에는 `", ".join(triggered_rules)`라 관리자 화면에
    `가드레일: over_auto_approve_limit, rule_ambiguous`처럼 영문 식별자가 그대로
    나갔고, 같은 금액을 가리키는 규칙 둘이 함께 걸리면 같은 말이 두 번 적혔다.
    """
    out: list[str] = []
    for rule in rules:
        prefix, _, arg = rule.partition(":")
        if arg and prefix in _RULE_PREFIX_LABELS:
            label = f"{_RULE_PREFIX_LABELS[prefix]}({_AUDITOR_LABELS.get(arg, arg)})"
        else:
            # 모르는 규칙은 식별자를 그대로 남긴다 — 숨기면 새 규칙이 조용히 사라진다
            label = _RULE_LABELS.get(rule, rule)
        if label not in out:
            out.append(label)
    return ", ".join(out)


def _escalation_detail(state: ReviewState) -> str:
    gate = state.get("gate_result")
    mismatch = state.get("mismatch", [])
    if mismatch:
        return "영수증-청구 불일치: " + ", ".join(
            f"{FIELD_LABELS.get(m.field, m.field)}(청구 {m.claimed} / 영수증 {m.receipt})"
            for m in mismatch
        )
    if gate is not None and gate.triggered_rules:
        detail = describe_rules(gate.triggered_rules)
        # 금액 규칙이 걸렸으면 그 라벨(둘은 같은 라벨로 접힘) 뒤에 청구·기준액을 병기해
        # 관리자가 근거 금액을 바로 본다. 위치 의존 없이 라벨 문자열을 찾아 붙인다.
        if _AMOUNT_RULES & set(gate.triggered_rules):
            label = _RULE_LABELS["over_auto_approve_limit"]
            detail = detail.replace(label, label + _amount_context(state), 1)
        return "자동 심사 결과: " + detail
    return "판정 신뢰도 미달 또는 심사 실패"


def _requester_message(state: ReviewState) -> str:
    """요청자용 에스컬레이션 사유 — 트리거 종류별 4종. 내부 수치·LLM 원문은 담지 않는다
    (요청자에게 승인/반려로 오인될 수 있는 문구를 보이면 안 되므로 adjudicate의 LLM 원문은
    쓰지 않는다)."""
    if state.get("mismatch"):
        return "영수증과 신청 내용이 일치하지 않아 관리자가 다시 확인합니다."
    gate = state.get("gate_result")
    if gate is not None and gate.triggered_rules:
        # 금액 규칙만 걸린 건은 금액이 유일한 사유이므로 그 사실을 밝힌다(수치는 담지 않음).
        # 다른 규칙과 섞이면 금액 문구가 그 사유를 가리므로 일반 문구를 유지한다.
        if set(gate.triggered_rules) <= _AMOUNT_RULES:
            return "청구 금액이 팀에서 정한 자동 승인 기준 이상이라 관리자 승인이 필요한 건으로 분류되었습니다."
        return "회칙·예산 기준에 따라 관리자 확인이 필요한 건으로 분류되었습니다."
    return "판정 결과에 대한 추가 확인이 필요하여 관리자가 검토합니다."


def _admin_message(state: ReviewState, detail: str) -> str:
    """관리자용 에스컬레이션 사유. adjudicate가 이미 LLM 사유를 만들어 둔 상태(저신뢰
    경로 — state에 confidence와 reasons가 둘 다 있음)면 그 내용을 이어 붙인다. 그냥
    버리면(종전 동작) LLM이 판단한 근거가 사라진다."""
    prior = state.get("reasons")
    if state.get("confidence") is not None and prior is not None:
        return f"{detail} — LLM 판단: {prior.admin}"
    return f"에스컬레이션 사유 — {detail}"


async def escalate(state: ReviewState) -> dict:
    detail = _escalation_detail(state)

    if state.get("hitl_enabled"):
        claim = state.get("claim")
        # 그래프가 여기서 멈춘다 — 재개 시 interrupt()가 관리자 결정을 반환
        decision = interrupt(
            {
                "reason": detail,
                "claim": {"title": claim.title, "amount": claim.amount, "category": claim.category}
                if claim
                else None,
                "confidence": state.get("confidence"),
                "opinions": {
                    k: {"verdict": o.verdict, "summary": o.summary}
                    for k, o in (state.get("opinions") or {}).items()
                },
            }
        )
        d = str(decision.get("decision", "")).lower() if isinstance(decision, dict) else ""
        if d in ("approve", "reject"):
            note = str(decision.get("reason") or "").strip() if isinstance(decision, dict) else ""
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
            requester=_requester_message(state),
            admin=_admin_message(state, detail),
        ),
    }
