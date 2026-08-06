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

    # 0. AI 자동판정 권한 스위치 (bravo 설계서: team_settings.auto_approve, 기본 FALSE)
    #    — 꺼져 있으면 금액·소견과 무관하게 무조건 ESCALATED. 심사관 소견은 그대로
    #    수집해 관리자 참고용 detail로 콜백에 실린다 (판정 권한만 없는 것).
    if not policy.auto_approve:
        triggered.append("auto_approve_disabled")

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

    # (구 2.5 `category_mismatch` 규칙은 T7로 제거 — 사용자 카테고리 선택이 화면에서
    #  사라져 "사용자 vs AI 불일치"라는 비교 자체가 성립하지 않는다. 2026-08-06 팀장 승인)

    # 3. 회칙 위반·해석 애매 또는 중복 의심 → 금액 무관 ESCALATED
    rule_op = opinions.get("rule")
    if rule_op is not None and rule_op.verdict == "fail":
        triggered.append("rule_violation")
    elif rule_op is not None and rule_op.verdict == "warn":
        # 근거 불충분·해석 애매 — 기본은 escalate (§9.2 경계 케이스).
        # 단, 동일 사안 관리자 승인 판례가 있으면 판례가 회칙 공백을 메운다 (§4.4-b)
        prec = opinions.get("precedent")
        admin_support = bool(prec and prec.figures.get("admin_approve_support"))
        if not admin_support:
            triggered.append("rule_ambiguous")
    prec_op = opinions.get("precedent")
    if prec_op is not None and prec_op.verdict in ("warn", "fail"):
        triggered.append("precedent_suspicion")

    # 4. 금액 가드레일 — 경계는 '이상'이다(2026-08-05 마법사 2단계 화면 개편으로 확정).
    #    화면이 "N원 이상은 관리자 승인 필수"로 표시하므로 한도와 같은 금액도 관리자
    #    확인이다. 그전에는 '초과'라 한도와 같은 금액이 자동 판정으로 갈라져 화면과
    #    1원 어긋났다 (docs/마법사_API_명세.md '경계는 이상이다').
    if amount >= policy.force_escalation_amount:
        triggered.append("over_force_escalation_amount")
    if amount >= policy.auto_approve_limit:
        triggered.append("over_auto_approve_limit")

    budget_op = opinions.get("budget")
    budget_fail = budget_op is not None and budget_op.verdict == "fail"

    # 4.5 정책(2026-07-20 실모드 실측 근거): 걸린 게 '회칙 해석 애매' 하나뿐이고
    # 예산 부족이 수치로 명확하면 에스컬레이션 대신 반려 후보로 넘긴다 — 회칙이
    # 애매해도 잔액이 없으면 지출 불가라는 결론은 같고, 반려는 자동 승인이 아니라
    # 안전 방향이다(§8 유지). 최종 판단은 adjudicate가 백스톱(저신뢰면 escalate).
    # 다른 규칙(불일치·판례 의심·한도 초과 등)이 함께 걸리면 기존대로 escalate.
    if triggered == ["rule_ambiguous"] and budget_fail:
        return GateResult(
            decision="reject_candidate", triggered_rules=["budget_insufficient", "rule_ambiguous"]
        )

    if triggered:
        return GateResult(decision="escalate", triggered_rules=triggered)

    # 5. 예산 잔액 부족 → AI_REJECTED 후보 (2단계 LLM 합성으로)
    if budget_fail:
        return GateResult(decision="reject_candidate", triggered_rules=["budget_insufficient"])

    return GateResult(decision="proceed")


async def guardrail_gate(state: ReviewState) -> dict:
    receipt = state.get("receipt_data")
    return {
        "gate_result": evaluate_guardrails(
            opinions=state.get("opinions", {}),
            mismatch=state.get("mismatch", []),
            policy=state["policy_params"],
            amount=state["claim"].amount,
            receipt_parse_ok=(receipt is not None and receipt.parse_ok),
        )
    }


def route_after_guardrail(state: ReviewState) -> str:
    gate = state["gate_result"]
    return "escalate" if gate.decision == "escalate" else "adjudicate"
