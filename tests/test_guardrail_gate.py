"""guardrail_gate 순수 함수 단위 테스트 — 100% 커버 목표 (§4.2).

핵심 불변식: 어떤 실패도 자동 승인(proceed)으로 이어지지 않는다 (§8).
"""
from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails
from app.schemas.common import Mismatch, Opinion, PolicyParams

POLICY = PolicyParams(auto_approve_limit=50_000, force_escalation_amount=300_000,
                      confidence_threshold=0.8)


def _ok_opinions() -> dict[str, Opinion]:
    return {
        "rule": Opinion(auditor="rule", verdict="pass", summary="ok"),
        "budget": Opinion(auditor="budget", verdict="pass", summary="ok"),
        "precedent": Opinion(auditor="precedent", verdict="pass", summary="ok"),
    }


def test_all_pass_proceeds():
    result = evaluate_guardrails(_ok_opinions(), [], POLICY, amount=30_000)
    assert result.decision == "proceed"


def test_missing_opinion_escalates():
    opinions = _ok_opinions()
    del opinions["precedent"]
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"
    assert "missing_opinion:precedent" in result.triggered_rules


def test_auditor_error_escalates():
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="error", summary="failed")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"


def test_mismatch_escalates():
    mismatch = [Mismatch(field="amount", claimed="50000", receipt="45000")]
    result = evaluate_guardrails(_ok_opinions(), mismatch, POLICY, amount=30_000)
    assert result.decision == "escalate"
    assert "receipt_mismatch" in result.triggered_rules


def test_unreadable_receipt_escalates():
    result = evaluate_guardrails(_ok_opinions(), [], POLICY, amount=30_000,
                                 receipt_parse_ok=False)
    assert result.decision == "escalate"
    assert "receipt_unreadable" in result.triggered_rules


def test_auto_approve_disabled_escalates_everything():
    """team_settings.auto_approve=False → 소견·금액 무관 무조건 ESCALATED (실계약 기본값)."""
    policy = PolicyParams(auto_approve=False)
    result = evaluate_guardrails(_ok_opinions(), [], policy, amount=1_000)
    assert result.decision == "escalate"
    assert "auto_approve_disabled" in result.triggered_rules


def test_auto_approve_disabled_beats_reject_candidate():
    """auto_approve OFF면 반려 후보(잔액 부족)도 escalate — 판정 권한 자체가 없다."""
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], PolicyParams(auto_approve=False),
                                 amount=1_000)
    assert result.decision == "escalate"


def test_rule_violation_escalates_regardless_of_amount():
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="fail", summary="금지 항목")
    result = evaluate_guardrails(opinions, [], POLICY, amount=1_000)  # 소액이어도
    assert result.decision == "escalate"
    assert "rule_violation" in result.triggered_rules


def test_rule_warn_ambiguous_escalates():
    """회칙 해석 애매(CRAG 근거 불충분) → 경계 케이스 정답은 escalate (§9.2)."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="근거 조항 못 찾음")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"
    assert "rule_ambiguous" in result.triggered_rules


def test_rule_warn_with_admin_approve_precedent_proceeds():
    """회칙 애매 + 동일 사안 관리자 승인 판례 → 판례가 회칙 공백을 메워 자동 경로 유지 (§4.4-b)."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="근거 조항 못 찾음")
    opinions["precedent"] = Opinion(auditor="precedent", verdict="pass",
                                    summary="관리자 승인 판례 1건",
                                    figures={"admin_approve_support": 1})
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "proceed"


def test_precedent_warn_escalates():
    opinions = _ok_opinions()
    opinions["precedent"] = Opinion(auditor="precedent", verdict="warn", summary="중복 의심")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"


def test_over_auto_approve_limit_escalates():
    result = evaluate_guardrails(_ok_opinions(), [], POLICY, amount=50_001)
    assert result.decision == "escalate"
    assert "over_auto_approve_limit" in result.triggered_rules


def test_zero_auto_approve_limit_means_full_manual_mode():
    """관리자가 limit=0 설정 시 전건 수동 모드 (§3.3 합의 사항)."""
    policy = POLICY.model_copy(update={"auto_approve_limit": 0})
    result = evaluate_guardrails(_ok_opinions(), [], policy, amount=1)
    assert result.decision == "escalate"


def test_budget_insufficient_becomes_reject_candidate():
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "reject_candidate"


def test_escalation_wins_over_reject_candidate():
    """잔액 부족 + 금액 초과가 동시면 에스컬레이션이 우선."""
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], POLICY, amount=999_999)
    assert result.decision == "escalate"
