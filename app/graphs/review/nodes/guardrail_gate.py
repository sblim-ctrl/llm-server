"""guardrail_gate — 결정적 가드레일 (§3.3 1단계). LLM 개입 불가.

evaluate_guardrails는 순수 함수 — 단위 테스트 100% 커버 대상 (§4.2).
대원칙: 어떤 실패도 자동 승인으로 이어지지 않는다 (§8).
"""
from app.graphs.review.state import ReviewState
from app.schemas.common import GateResult, Mismatch, Opinion, PolicyParams

REQUIRED_AUDITORS = ("rule", "budget", "precedent")


def evaluate_guardrails(
    opinions: dict[str, Opinion],
    mismatch: list[Mismatch],
    policy: PolicyParams,
    amount: int,
    receipt_parse_ok: bool = True,
) -> GateResult:
    triggered: list[str] = []

    # 1. 심사관 누락·실패 → ESCALATED (부분 소견으로 판정하지 않음)
    for name in REQUIRED_AUDITORS:
        op = opinions.get(name)
        if op is None:
            triggered.append(f"missing_opinion:{name}")
        elif op.verdict == "error":
            triggered.append(f"auditor_failed:{name}")

    # 2. 영수증 판독 불능 / 불일치 (REQ-028)
    if not receipt_parse_ok:
        triggered.append("receipt_unreadable")
    if mismatch:
        triggered.append("receipt_mismatch")

    # 3. 회칙 위반·해석 애매 또는 중복 의심 → 금액 무관 ESCALATED
    rule_op = opinions.get("rule")
    if rule_op is not None and rule_op.verdict == "fail":
        triggered.append("rule_violation")
    elif rule_op is not None and rule_op.verdict == "warn":
        # 근거 불충분·해석 애매 — 경계 케이스의 정답은 escalate (§9.2)
        triggered.append("rule_ambiguous")
    prec_op = opinions.get("precedent")
    if prec_op is not None and prec_op.verdict in ("warn", "fail"):
        triggered.append("precedent_suspicion")

    # 4. 금액 가드레일
    if amount > policy.force_escalation_amount:
        triggered.append("over_force_escalation_amount")
    if amount > policy.auto_approve_limit:
        triggered.append("over_auto_approve_limit")

    if triggered:
        return GateResult(decision="escalate", triggered_rules=triggered)

    # 5. 예산 잔액 부족 → AI_REJECTED 후보 (2단계 LLM 합성으로)
    budget_op = opinions.get("budget")
    if budget_op is not None and budget_op.verdict == "fail":
        return GateResult(decision="reject_candidate", triggered_rules=["budget_insufficient"])

    return GateResult(decision="proceed")


async def guardrail_gate(state: ReviewState) -> dict:
    receipt = state.get("receipt_data")
    return {"gate_result": evaluate_guardrails(
        opinions=state.get("opinions", {}),
        mismatch=state.get("mismatch", []),
        policy=state["policy_params"],
        amount=state["claim"].amount,
        receipt_parse_ok=(receipt is not None and receipt.parse_ok),
    )}


def route_after_guardrail(state: ReviewState) -> str:
    gate = state["gate_result"]
    return "escalate" if gate.decision == "escalate" else "adjudicate"
