"""HITL 사람 개입 (강의 06-02) — escalate interrupt 분기·ADMIN 전파 단위 테스트.

interrupt()는 그래프 런타임(체크포인터) 안에서만 동작하므로 여기서는 monkeypatch로
대체해 분기 로직만 검증한다. 멈춤→재개 E2E는 데모 경로(/ui)에서 수동 검증
(reviews_stream.py docstring 참조 — SSE와 동일한 관례).
"""
import pytest

from app.graphs.review.nodes import escalate as esc_mod
from app.graphs.review.nodes import persist_precedent as pp_mod
from app.graphs.review.nodes.callback import build_callback_payload
from app.schemas.common import ExpenseClaim, GateResult, Mismatch, Reasons


def _state(**extra) -> dict:
    return {
        "job_id": "job-1", "expense_id": 4821, "team_id": 11,
        "opinions": {}, "mismatch": [],
        "claim": ExpenseClaim(title="회식 2차", amount=66_000, category="식비",
                              date="2026-07-15"),
        **extra,
    }


async def test_without_hitl_flag_behaves_as_before(monkeypatch):
    """워커 경로(플래그 없음): interrupt를 부르지 않고 기존 escalate 확정."""
    def _boom(_):
        raise AssertionError("interrupt가 호출되면 안 됨")
    monkeypatch.setattr(esc_mod, "interrupt", _boom)
    out = await esc_mod.escalate(_state())
    assert out["verdict"] == "escalate"
    assert "admin_decision" not in out


@pytest.mark.parametrize("decision,expected", [("approve", "approve"),
                                               ("reject", "reject")])
async def test_hitl_admin_decision_resumes_with_verdict(monkeypatch, decision, expected):
    """HITL: interrupt가 반환한 관리자 결정이 최종 verdict가 된다."""
    monkeypatch.setattr(esc_mod, "interrupt",
                        lambda payload: {"decision": decision, "reason": "원본 확인"})
    out = await esc_mod.escalate(_state(hitl_enabled=True))
    assert out["verdict"] == expected
    assert out["admin_decision"] == {"decision": expected, "reason": "원본 확인"}
    # 요청자용 사유엔 관리자 메모(내부 정보 가능)를 싣지 않는다
    assert "원본 확인" not in out["reasons"].requester
    assert "원본 확인" in out["reasons"].admin


async def test_hitl_invalid_decision_stays_escalated(monkeypatch):
    """이상값(승인/반려 아님) → 안전 방향: 보류 유지 (§8)."""
    monkeypatch.setattr(esc_mod, "interrupt", lambda payload: {"decision": "ㅋㅋ"})
    out = await esc_mod.escalate(_state(hitl_enabled=True))
    assert out["verdict"] == "escalate"


def test_callback_processed_by_admin_when_admin_decided():
    state = _state(verdict="approve", confidence=None, reasons=None,
                   admin_decision={"decision": "approve", "reason": ""})
    assert build_callback_payload(state).processed_by == "ADMIN"
    state.pop("admin_decision")
    assert build_callback_payload(state).processed_by == "AI"


async def test_precedent_decided_by_admin(monkeypatch):
    """관리자 결정 건은 decided_by='ADMIN' 판례로 저장 — 학습 루프의 사람 축."""
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(pp_mod, "save_precedent", _capture)
    await pp_mod.persist_precedent(
        _state(verdict="approve", admin_decision={"decision": "approve", "reason": ""}))
    assert captured["decided_by"] == "ADMIN"

    captured.clear()
    await pp_mod.persist_precedent(_state(verdict="escalate"))
    assert captured["decided_by"] == "AGENT"


# ── 관리자에게 보이는 가드레일 문구 (2026-08-07) ──────────────────────────
#
# 종전에는 `가드레일: over_auto_approve_limit, rule_ambiguous`처럼 영문 식별자가
# 그대로 관리자 화면에 나갔다. 규칙 식별자는 골든셋 `expected_gate_includes`와
# Trajectory 채점이 쓰므로 못 바꾼다 — 보여주는 자리에서만 옮긴다.

from app.graphs.review.nodes.escalate import describe_rules  # noqa: E402


def test_rules_are_shown_in_korean():
    """관리자 화면에 영문 식별자가 그대로 나가지 않는다."""
    out = describe_rules(["budget_insufficient", "rule_ambiguous"])
    assert out == "예산 잔액 부족, 회칙 해석이 애매함"
    assert "_" not in out


def test_same_amount_rule_is_not_repeated():
    """한도·기준액은 2026-08-05 화면 개편 이후 같은 금액이라 한 줄로 접는다."""
    assert describe_rules(
        ["over_auto_approve_limit", "over_force_escalation_amount"]
    ) == "관리자 승인이 필요한 금액"


def test_auditor_scoped_rules_name_the_auditor():
    """`missing_opinion:rule`처럼 대상이 붙는 규칙도 읽히게 옮긴다."""
    assert describe_rules(["missing_opinion:rule"]) == "심사관 소견 누락(회칙)"
    assert describe_rules(["auditor_failed:budget"]) == "심사관 실행 실패(예산)"


def test_unknown_rule_is_kept_as_is():
    """모르는 규칙을 숨기면 새로 생긴 규칙이 조용히 사라진다 — 식별자를 그대로 남긴다."""
    assert describe_rules(["some_new_rule"]) == "some_new_rule"


def test_order_is_preserved():
    """규칙이 걸린 순서가 곧 심사 단계 순서라 보존한다."""
    assert describe_rules(["auto_approve_disabled", "budget_insufficient"]) == (
        "AI 자동 판정이 꺼져 있음, 예산 잔액 부족"
    )


# ── 요청자용 문구 3종화 + adjudicate LLM 사유 보존 (2026-08-10) ──────────
#
# 종전에는 mismatch/gate/저신뢰 세 트리거를 구분하지 않고 요청자에게 항상 같은
# 문구를 보냈고, 저신뢰 경로에서는 adjudicate가 만든 LLM 사유(state["reasons"])를
# escalate()가 무조건 새 Reasons로 덮어써 사라졌다.

from app.graphs.review.nodes.escalate import _requester_message  # noqa: E402


def test_requester_message_differs_by_trigger():
    """mismatch/gate/기본 세 트리거에서 서로 다른 요청자용 문구를 반환한다."""
    mismatch_msg = _requester_message(
        _state(mismatch=[Mismatch(field="amount", claimed="1000", receipt="2000")])
    )
    gate_msg = _requester_message(
        _state(gate_result=GateResult(decision="escalate", triggered_rules=["rule_ambiguous"]))
    )
    default_msg = _requester_message(_state())

    assert len({mismatch_msg, gate_msg, default_msg}) == 3


async def test_low_confidence_preserves_llm_admin_reason(monkeypatch):
    """저신뢰 경로: adjudicate가 만든 LLM 사유(admin)가 escalate 후에도 남는다."""
    def _boom(_):
        raise AssertionError("interrupt가 호출되면 안 됨")
    monkeypatch.setattr(esc_mod, "interrupt", _boom)

    out = await esc_mod.escalate(_state(
        confidence=0.62,
        reasons=Reasons(
            requester="...",
            admin="LLM 판단: 3개 심사관 전원 통과, 승인 후 잔액 118,000원",
        ),
    ))

    assert out["verdict"] == "escalate"
    assert "118,000원" in out["reasons"].admin
    assert out["reasons"].requester == _requester_message(_state())


async def test_mismatch_and_gate_triggers_use_escalation_detail_admin_message(monkeypatch):
    """mismatch/gate 트리거(reasons=None, confidence=None)에서는 여전히 _escalation_detail
    기반 admin 문구가 나온다 — adjudicate를 거치지 않은 경로라 LLM 사유가 없다."""
    def _boom(_):
        raise AssertionError("interrupt가 호출되면 안 됨")
    monkeypatch.setattr(esc_mod, "interrupt", _boom)

    mismatch = [Mismatch(field="amount", claimed="1000", receipt="2000")]
    mismatch_state = _state(mismatch=mismatch)
    out = await esc_mod.escalate(mismatch_state)
    expected = f"에스컬레이션 사유 — {esc_mod._escalation_detail(mismatch_state)}"
    assert out["reasons"].admin == expected
    assert "LLM 판단" not in out["reasons"].admin

    gate = GateResult(decision="escalate", triggered_rules=["rule_ambiguous"])
    gate_state = _state(gate_result=gate)
    out = await esc_mod.escalate(gate_state)
    expected = f"에스컬레이션 사유 — {esc_mod._escalation_detail(gate_state)}"
    assert out["reasons"].admin == expected
    assert "LLM 판단" not in out["reasons"].admin
