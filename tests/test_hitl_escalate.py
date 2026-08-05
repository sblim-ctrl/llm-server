"""HITL 사람 개입 (강의 06-02) — escalate interrupt 분기·ADMIN 전파 단위 테스트.

interrupt()는 그래프 런타임(체크포인터) 안에서만 동작하므로 여기서는 monkeypatch로
대체해 분기 로직만 검증한다. 멈춤→재개 E2E는 데모 경로(/ui)에서 수동 검증
(reviews_stream.py docstring 참조 — SSE와 동일한 관례).
"""
import pytest

from app.graphs.review.nodes import escalate as esc_mod
from app.graphs.review.nodes import persist_precedent as pp_mod
from app.graphs.review.nodes.callback import build_callback_payload
from app.schemas.common import ExpenseClaim


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
