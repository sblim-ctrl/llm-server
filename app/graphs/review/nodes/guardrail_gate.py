"""guardrail_gate — 결정적 가드레일 (§3.3 1단계). LLM 개입 불가.

evaluate_guardrails는 순수 함수 — 단위 테스트 100% 커버 대상 (§4.2).
대원칙: 어떤 실패도 자동 승인으로 이어지지 않는다 (§8).
"""

from app.graphs.review.state import ReviewState
from app.schemas.common import GateResult, Mismatch, Opinion, PolicyParams

REQUIRED_AUDITORS = ("rule", "budget", "precedent")

#: 예산 부족(수치로 확정)이 이기는 규칙들 — 자세한 근거는 evaluate_guardrails §4.5.
#: 여기 없는 규칙이 하나라도 걸리면 예산이 부족해도 에스컬레이션이다.
#:
#: 금액 임계값 **둘 다** 이긴다 (2026-08-11 팀장 승인 — PR #64 리뷰 회신의 결정 1·2.
#: rule_violation 확대는 요청 범위를 넘는 것이라 함께 승인받았다. 직전까지는
#: auto_approve_limit만이었다). 잔액 부족은 수치로 확정된 사실이고 반려는 자동 승인이
#: 아니라 안전 방향이므로, 금액이 얼마든 "지출 불가"라는 결론은 같다. 종전의
#: "절대 상한(force_escalation_amount)은 사람이 결정" 우선순위(2026-07-20 실측 기반,
#: 구 골든 hobby-gate-priority-001 등이 고정)는 이 결정으로 뒤집혔다 — 관리자가
#: 예산을 증액해 살리고 싶은 건은 반려 후 HITL로 뒤집으면 된다(경로 존재).
#: 판단 기준은 **결론의 방향**이다 — "쓰면 안 된다"를 가리키거나 판단을 유보할 뿐인
#: 신호는 잔액 부족이라는 확정 사실을 뒤집지 못한다. 반대로 잔액 계산의 전제나 권한을
#: 흔드는 신호(영수증 불일치·파이프라인 불완전·판정 권한 없음)는 이기지 못한다.
_BUDGET_OVERRIDES = frozenset({
    "over_auto_approve_limit",        # 자동 '승인' 상한 — 반려는 승인이 아니다
    "over_force_escalation_amount",   # 절대 상한도 잔액 부족 앞에서는 결론이 같다
    "rule_ambiguous",                 # 회칙이 애매해도 잔액이 없으면 결론은 같다
    # 회칙 위반은 예산 부족과 **같은 방향**(쓰면 안 된다)이다. 이것 때문에 반려가
    # 보류로 바뀌면 "거절 사유가 하나 더 붙었더니 거절이 안 되는" 역전이 된다
    # (실측: company-boundary-001 — 잔액 182,000 < 청구 280,000 이면서 1인당 한도
    #  초과. 종전 로직은 이 건을 escalate로 보냈다). 반려 근거는 어디까지나 산술로
    # 확정된 예산이고, 회칙 위반은 관리자에게 전달되는 맥락으로 남는다.
    "rule_violation",
})


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

    # 4.5 예산 부족은 '지출 불가'를 가리키거나 판단을 유보하는 신호들을 이긴다
    # (2026-08-11 팀장 승인 — PR #64 리뷰 회신 결정 1·2, 요청 범위 확대 포함.
    #  확대 이력: 2026-07-20 rule_ambiguous 단독 → 08-11 auto_approve_limit →
    #  force_escalation_amount → rule_violation).
    #
    # 왜: 종전 로직은 `triggered`가 비어야만 반려로 갔다. 그래서 잔액이 없는 게
    # 수치로 명확한 건이라도 금액이 임계값을 넘거나 회칙까지 위반하면 에스컬레이션이
    # 됐다 — **거절 사유가 하나 더 붙을수록 거절이 안 되는** 역전이었다(배포 데모의
    # 금액 건, 골든 company-boundary-001의 회칙 위반 건 둘 다 실측으로 확인).
    # 잔액이 없으면 지출 불가라는 결론은 같고, 반려는 자동 승인이 아니라 안전
    # 방향이다(§8 유지). 관리자가 살리고 싶은 건은 반려 후 HITL로 뒤집을 수 있다.
    #
    # 반대로 아래는 **이기지 못한다** — 잔액 계산의 전제나 판정 권한이 흔들리거나,
    # 예산과 무관한 별도 조사가 필요한 경우다:
    #   · auto_approve_disabled — AI에게 판정 권한 자체가 없다(반려도 판정이다)
    #   · missing_opinion/auditor_failed — 파이프라인이 불완전하다
    #   · receipt_unreadable/receipt_mismatch — 청구 금액 자체가 의심스러우면
    #     '얼마가 부족한지'도 못 믿는다
    #   · precedent_suspicion — 중복·분할 청구 의심은 금액이 아니라 사실관계
    #     조사가 필요한 사안이라 사람에게 넘긴다
    # 최종 판단은 adjudicate가 백스톱(저신뢰면 escalate).
    if budget_fail and triggered and set(triggered) <= _BUDGET_OVERRIDES:
        return GateResult(
            decision="reject_candidate", triggered_rules=["budget_insufficient", *triggered]
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
