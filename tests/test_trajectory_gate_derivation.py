"""Trajectory 채점용 가드레일 도출 — 하니스 두 벌이 갈리지 않게 고정.

2026-08-12에 실제로 갈렸다. `run_case`(로컬 CSV)에는 "영수증 불일치는 mismatch_gate가
가드레일 앞에서 escalate로 직행하므로 mismatch에서 도출한다"는 보정이 있었는데
`eval/run_eval_langsmith.py`의 target에는 없었다. 그래서 LangSmith `gate_includes_hit`이
영수증 불일치 케이스 8건을 계속 미달로 셌다(42/50 = 84%, 2회 연속 동일 수치).
**판정은 8건 모두 정답이었으므로 시스템이 아니라 채점 하니스의 결함이었다.**
"""

from pathlib import Path

from app.eval_support import gate_rules_from_state
from app.schemas.common import GateResult, Mismatch

ROOT = Path(__file__).resolve().parents[1]


def test_gate_result_rules_pass_through():
    state = {"gate_result": GateResult(decision="escalate",
                                       triggered_rules=["auto_approve_disabled"])}
    assert gate_rules_from_state(state) == ["auto_approve_disabled"]


def test_mismatch_without_gate_result_is_receipt_mismatch():
    """mismatch_gate 단락 경로 — gate_result가 없어도 궤적은 남아야 한다."""
    state = {"mismatch": [Mismatch(field="amount", claimed="30000", receipt="25000")]}
    assert gate_rules_from_state(state) == ["receipt_mismatch"]


def test_gate_result_wins_over_mismatch():
    """가드레일까지 도달한 건은 그쪽 규칙이 궤적이다 — mismatch로 덮어쓰지 않는다."""
    state = {
        "gate_result": GateResult(decision="escalate", triggered_rules=["receipt_mismatch"]),
        "mismatch": [Mismatch(field="date", claimed="2026-07-01", receipt="2026-06-01")],
    }
    assert gate_rules_from_state(state) == ["receipt_mismatch"]


def test_empty_state_is_empty_trajectory():
    assert gate_rules_from_state({}) == []


def test_langsmith_target_uses_the_shared_derivation():
    """**배선 그물** — 순수 함수만 검사하면 이 결함을 다시 놓친다.

    LangSmith target이 `gate_result.triggered_rules`를 직접 읽던 것이 원인이었으므로,
    그 패턴이 되살아나지 않는지 소스에서 확인한다. 두 하니스가 같은 함수를 쓰는 한
    보정이 한쪽에만 적용되는 일은 생기지 않는다.
    """
    for name in ("run_eval_langsmith.py", "run_eval_real.py"):
        src = (ROOT / "eval" / name).read_text(encoding="utf-8")
        assert "gate_rules_from_state" in src, f"{name}이 공용 도출 함수를 쓰지 않는다"
        assert "triggered_rules" not in src, (
            f"{name}이 triggered_rules를 직접 읽으면 mismatch 단락 경로 보정이 빠진다"
        )
