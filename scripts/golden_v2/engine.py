"""골든 v2 기대값 계산 엔진 — 결정적 순수 함수.

app/graphs/review/nodes/{guardrail_gate,budget_auditor,mismatch_gate,adjudicate}.py의
목 모드 동작을 그대로 재현한다. 기대값을 손으로 적지 않고 이 엔진으로 유도하는 것이
scripts/generate_golden_v2.py의 핵심 취지다 — 실제 코드와 어긋난 기대값을 원천 차단한다.

목 모드에서 항상 성립하는 전제(2026-09 코드 정독으로 확인):
- 골든 팀은 로컬 DB에 회칙이 인덱싱되어 있지 않다(rule_version=None) → rule_auditor는
  항상 _audit_by_default_policy 경로(no_rules)를 타고, 그 mock_response는 항상
  verdict="pass"다. 즉 목 모드에서는 rule_violation·rule_ambiguous가 절대 발동하지 않는다.
- precedent_auditor의 mock_response도 판례가 없으면(또는 위험 신호가 없으면) 항상
  verdict="pass"다 — precedent_suspicion은 실제로 위험 판례를 시딩한 경우만 발동한다.
- 두 심사관 모두 opinions에 항상 값을 채우므로 missing_opinion:*·auditor_failed:*는
  발동하지 않는다.

이 전제가 깨지는 유일한 축(회칙 충돌·판례 유사)은 실모드 전용이라 이 엔진은 목 모드
기대값만 계산한다 — 실모드 기대값은 손으로 판단해 케이스에 직접 적는다(하드 케이스).
"""

from dataclasses import dataclass

# app/graphs/review/nodes/guardrail_gate.py의 _BUDGET_OVERRIDES와 동일 — 예산 부족이
# 이기는 트리거 화이트리스트.
BUDGET_OVERRIDES = frozenset(
    {"over_auto_approve_limit", "over_force_escalation_amount", "rule_ambiguous", "rule_violation"}
)


@dataclass(frozen=True)
class ExpectedOutcome:
    verdict: str  # approve | reject | escalate
    gate_includes: list[str]


def evaluate(
    *,
    amount: int,
    auto_approve: bool,
    auto_approve_limit: int,
    force_escalation_amount: int,
    budget_total: int,
    budget_spent: int,
    receipt_state: str,  # "match" | "mismatch" | "missing"
) -> ExpectedOutcome:
    """목 모드 기대 판정을 계산한다 (순수 함수).

    receipt_state="mismatch"는 mismatch_gate가 guardrail_gate보다 먼저 escalate로
    직행시키는 경로를 재현한다(app/graphs/review/graph.py route_after_mismatch) —
    이 경로는 budget/rule 심사관 자체를 거치지 않으므로 아래 가드레일 로직과 완전히
    분리된 반환이다.
    """
    if receipt_state == "mismatch":
        return ExpectedOutcome(verdict="escalate", gate_includes=["receipt_mismatch"])

    triggered: list[str] = []
    if not auto_approve:
        triggered.append("auto_approve_disabled")
    if receipt_state == "missing":
        triggered.append("receipt_unreadable")
    if amount >= force_escalation_amount:
        triggered.append("over_force_escalation_amount")
    if amount >= auto_approve_limit:
        triggered.append("over_auto_approve_limit")

    remaining_before = budget_total - budget_spent
    budget_fail = (remaining_before - amount) < 0

    if budget_fail and triggered and set(triggered) <= BUDGET_OVERRIDES:
        return ExpectedOutcome(verdict="reject", gate_includes=["budget_insufficient", *triggered])
    if triggered:
        return ExpectedOutcome(verdict="escalate", gate_includes=triggered)
    if budget_fail:
        return ExpectedOutcome(verdict="reject", gate_includes=["budget_insufficient"])
    return ExpectedOutcome(verdict="approve", gate_includes=[])
