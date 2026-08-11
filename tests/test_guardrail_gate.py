"""guardrail_gate 순수 함수 단위 테스트 — 100% 커버 목표 (§4.2).

핵심 불변식: 어떤 실패도 자동 승인(proceed)으로 이어지지 않는다 (§8).
"""
import pytest

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


def test_lone_rule_ambiguous_with_budget_fail_becomes_reject_candidate():
    """정책(2026-07-20 실측): 회칙 애매 '단독' + 예산 부족 명확 → 반려 후보.

    회칙이 애매해도 잔액이 없으면 지출 불가 결론은 같다 — 반려는 안전 방향(§8)이고
    adjudicate가 백스톱. 실모드 골든셋에서 lowbudget 반려 케이스가 rule_ambiguous로
    선점 에스컬레이션되던 문제의 해소."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="해석 애매")
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], POLICY, amount=5_000)
    assert result.decision == "reject_candidate"
    assert "budget_insufficient" in result.triggered_rules
    assert "rule_ambiguous" in result.triggered_rules


def test_rule_ambiguous_with_other_triggers_still_escalates():
    """회칙 애매 + 다른 규칙(판례 의심 등) 동반이면 기존대로 escalate — 정책은 '단독'일 때만."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="해석 애매")
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    opinions["precedent"] = Opinion(auditor="precedent", verdict="warn", summary="유사 반려 판례")
    result = evaluate_guardrails(opinions, [], POLICY, amount=5_000)
    assert result.decision == "escalate"


def test_lone_rule_ambiguous_without_budget_fail_still_escalates():
    """예산이 멀쩡하면 회칙 애매는 기존대로 escalate — 정책은 예산 부족 명확 시에만."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="해석 애매")
    result = evaluate_guardrails(opinions, [], POLICY, amount=5_000)
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


# ── 예산 부족은 금액 임계값을 이긴다 (2026-08-11 정책 변경) ──────────────────
#
# 종전에는 "잔액 부족 + 금액 초과 → 에스컬레이션 우선"이었다. 그 결과 **금액이 클수록
# 반려가 안 되는** 역전이 생겼다(배포 데모에서 확인). 금액 임계값은 '승인'을 사람에게
# 넘기는 장치지, 잔액이 없다는 확정 사실을 뒤집는 장치가 아니다.


def test_budget_insufficient_beats_auto_approve_limit():
    """잔액 부족 + 자동승인 상한 초과 → 반려 (배포 데모의 9만원 건).

    auto_approve_limit은 AI의 자동 '승인' 권한을 제한하는 선이지 반려를 막는
    장치가 아니다. 종전에는 여기서 에스컬레이션이 나와, 금액이 클수록 반려가
    안 되는 역전이 있었다.
    """
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], POLICY, amount=90_000)  # 5만 초과·30만 미만
    assert result.decision == "reject_candidate"
    # 왜 반려인지 + 금액도 상한을 넘었다는 사실이 둘 다 남아야 관리자가 맥락을 안다
    assert "budget_insufficient" in result.triggered_rules
    assert "over_auto_approve_limit" in result.triggered_rules


def test_budget_insufficient_beats_rule_violation():
    """회칙 위반도 예산 부족을 막지 못한다 — 둘 다 '쓰면 안 된다' 방향이다.

    실측 근거(골든 company-boundary-001): 잔액 182,000 < 청구 280,000이면서 1인당
    회칙 한도까지 초과한 건이 종전에는 escalate로 갔다 — 거절 사유가 하나 더 붙었더니
    거절이 안 되는 역전이다. 반려 근거는 산술로 확정된 예산이고, 회칙 위반은
    관리자에게 전달되는 맥락으로 triggered에 남는다.
    """
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    opinions["rule"] = Opinion(auditor="rule", verdict="fail", summary="1인당 한도 초과")
    result = evaluate_guardrails(opinions, [], POLICY, amount=280_000)
    assert result.decision == "reject_candidate"
    assert "budget_insufficient" in result.triggered_rules
    assert "rule_violation" in result.triggered_rules


def test_rule_violation_alone_still_escalates():
    """예산이 멀쩡하면 회칙 위반만으로는 여전히 관리자 확인 — AI가 회칙 해석으로
    자동 반려하지 않는다는 원칙(§9.2)은 그대로다."""
    opinions = _ok_opinions()
    opinions["rule"] = Opinion(auditor="rule", verdict="fail", summary="1인당 한도 초과")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"
    assert "rule_violation" in result.triggered_rules


def test_budget_insufficient_beats_force_escalation_amount():
    """절대 상한도 예산 부족을 막지 못한다 (2026-08-11 팀 결정 — 팀장 위임).

    종전에는 "이 금액 이상은 무조건 사람"이 우선이었으나, 잔액 부족은 수치로 확정된
    사실이고 반려는 안전 방향이라 결론(지출 불가)이 금액과 무관하게 같다. 관리자가
    살리고 싶은 건은 반려 후 HITL로 뒤집는 경로가 있다. 골든 재라벨 9건과 짝이다.
    """
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    result = evaluate_guardrails(opinions, [], POLICY, amount=999_999)  # 30만(절대 상한) 초과
    assert result.decision == "reject_candidate"
    # 반려 사유 + 절대 상한도 넘었다는 사실이 둘 다 남아야 관리자가 맥락을 안다
    assert "budget_insufficient" in result.triggered_rules
    assert "over_force_escalation_amount" in result.triggered_rules


def test_budget_insufficient_beats_rule_ambiguous():
    """회칙이 애매해도 잔액이 없으면 결론은 같다 (2026-07-20부터의 기존 규칙 유지)."""
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    opinions["rule"] = Opinion(auditor="rule", verdict="warn", summary="해석 애매")
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "reject_candidate"


@pytest.mark.parametrize("mutate,label", [
    (lambda o, p, m: (o, p, m, False), "영수증 판독 불가 — 청구 금액 자체가 의심스럽다"),
    (lambda o, p, m: (o, p, [Mismatch(field="amount", claimed="50000", receipt="45000")], True),
     "영수증 불일치 — 얼마가 부족한지도 못 믿는다"),
    (lambda o, p, m: (o, p.model_copy(update={"auto_approve": False}), m, True),
     "자동판정 OFF — AI에게 판정 권한이 없다(반려도 판정이다)"),
    (lambda o, p, m: ({**o, "precedent": Opinion(auditor="precedent", verdict="warn",
                                                 summary="중복 의심")}, p, m, True),
     "판례 의심 — 예산과 별개 사안이라 사람이 봐야 한다"),
])
def test_budget_insufficient_does_not_beat_these(mutate, label):
    """예산 부족이 이기지 못하는 규칙들 — 잔액 계산의 전제·권한이 흔들리거나
    예산과 무관한 별도 조사가 필요한 경우."""
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    ops, policy, mismatch, parse_ok = mutate(opinions, POLICY, [])
    result = evaluate_guardrails(ops, mismatch, policy, amount=30_000,
                                 receipt_parse_ok=parse_ok)
    assert result.decision == "escalate", label


def test_missing_auditor_still_escalates_even_when_budget_fails():
    """파이프라인이 불완전하면 예산 부족이어도 사람에게 — 부분 소견으로 판정하지 않는다."""
    opinions = _ok_opinions()
    opinions["budget"] = Opinion(auditor="budget", verdict="fail", summary="잔액 부족")
    del opinions["precedent"]
    result = evaluate_guardrails(opinions, [], POLICY, amount=30_000)
    assert result.decision == "escalate"


def test_amount_thresholds_still_escalate_when_budget_is_fine():
    """예산이 멀쩡한데 금액만 큰 건은 종전대로 에스컬레이션 — 이 변경의 사정권 밖이다."""
    result = evaluate_guardrails(_ok_opinions(), [], POLICY, amount=999_999)
    assert result.decision == "escalate"


# (test_category_mismatch_escalates는 T7로 규칙과 함께 제거 — 사용자 카테고리 선택이
#  사라져 비교 대상이 없다. 2026-08-06 팀장 승인)
