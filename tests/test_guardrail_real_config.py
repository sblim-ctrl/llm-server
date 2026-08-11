"""guardrail_gate — **실서비스 구성**에서의 판정 고정 (2026-08-11 리뷰 Blocking 대응).

## 왜 이 파일이 따로 있나

`tests/test_guardrail_gate.py`의 공용 상수는 `auto_approve_limit=50_000` ·
`force_escalation_amount=300_000`이다. **이 조합은 실서비스에서 나올 수 없다.**
2026-08-05 화면 개편으로 금액 칸이 하나가 되면서 백엔드가 `escalation_threshold`
컬럼을 삭제했고(backend_client.get_team_settings docstring), 키가 없으면
`map_team_settings`가 `force = limit`으로 읽기 때문이다.

그 간극이 실제 결함을 통과시켰다. 예산 부족이 `over_auto_approve_limit`만 이기게 한
직전 변경은 단위 테스트·골든 73건을 모두 통과했지만 **실서비스에서는 한 번도 동작하지
않았다** — 한도를 넘으면 `over_force_escalation_amount`가 항상 함께 걸려서,
`set(triggered) <= _BUDGET_OVERRIDES`가 영원히 False였다. 갈린 임계값 위에서만
테스트했기 때문에 아무도 못 봤다(팀장 리뷰에서 사람이 손으로 찾았다).

그래서 여기서는 `PolicyParams`를 직접 만들지 않는다. **백엔드가 실제로 보내는 형태의
dict를 `map_team_settings`에 통과시켜 얻은 값으로만** 판정을 고정한다.
"""

import json
from pathlib import Path

import pytest

from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails
from app.schemas.common import Opinion
from app.tools.policy_params import map_team_settings

_FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "mock_backend.json"

# 백엔드가 실제로 보내는 team_settings 형태 — escalation_threshold 키는 없다.
REAL_SETTINGS = {"auto_approve": True, "auto_approve_limit": 50_000}


def _opinions(budget: str = "pass", rule: str = "pass") -> dict[str, Opinion]:
    return {
        "rule": Opinion(auditor="rule", verdict=rule, summary="-"),
        "budget": Opinion(auditor="budget", verdict=budget, summary="-"),
        "precedent": Opinion(auditor="precedent", verdict="pass", summary="-"),
    }


def _fixture_settings() -> list[tuple[str, dict]]:
    orgs = json.loads(_FIXTURES.read_text(encoding="utf-8"))["organizations"]
    return [(oid, o) for oid, o in orgs.items() if o.get("auto_approve_limit") is not None]


# ── 전제 고정 ────────────────────────────────────────────


def test_real_settings_collapse_both_thresholds():
    """실서비스 형태에서는 두 금액 임계값이 같은 값이 된다.

    이 전제가 깨지면(백엔드가 escalation_threshold를 다시 보내기 시작하면) 아래
    판정 고정들의 의미가 달라지므로, 전제 자체를 테스트로 세워 둔다.
    """
    policy = map_team_settings(REAL_SETTINGS)
    assert policy.force_escalation_amount == policy.auto_approve_limit == 50_000


@pytest.mark.parametrize("org_id,settings", _fixture_settings())
def test_every_fixture_org_collapses_thresholds(org_id, settings):
    """목 fixture의 모든 조직도 같아야 한다 — 목이 실제와 다르면 목 모드에서만 통과한다."""
    policy = map_team_settings(settings)
    assert policy.force_escalation_amount == policy.auto_approve_limit, (
        f"조직 {org_id}({settings.get('label')})의 임계값이 갈렸다 — fixture에 "
        f"escalation_threshold가 들어왔는지 확인할 것"
    )


# ── 실서비스 구성에서의 판정 ─────────────────────────────


def test_budget_fail_over_limit_rejects_in_real_config():
    """배포 데모의 그 건: 잔액 부족 + 한도(=절대 상한) 초과 → 반려.

    **이 테스트가 없어서 직전 변경의 무동작을 못 잡았다.** 갈린 임계값(5만/30만)
    위에서는 통과하던 것이, 실서비스 구성(5만/5만)에서는 에스컬레이션으로 남았다.
    """
    policy = map_team_settings(REAL_SETTINGS)
    result = evaluate_guardrails(_opinions(budget="fail"), [], policy, amount=90_000)

    assert result.decision == "reject_candidate"
    assert "budget_insufficient" in result.triggered_rules
    # 관리자가 맥락을 알 수 있게 함께 걸린 금액 규칙도 남는다
    assert "over_auto_approve_limit" in result.triggered_rules
    assert "over_force_escalation_amount" in result.triggered_rules


def test_budget_ok_over_limit_still_escalates_in_real_config():
    """잔액이 멀쩡하면 금액 초과는 종전대로 사람에게 간다 — 반려 확대가 여기까지 오면 안 된다."""
    policy = map_team_settings(REAL_SETTINGS)
    result = evaluate_guardrails(_opinions(), [], policy, amount=90_000)

    assert result.decision == "escalate"
    assert "over_auto_approve_limit" in result.triggered_rules


def test_budget_fail_with_receipt_mismatch_still_escalates_in_real_config():
    """잔액 계산의 전제가 흔들리면(영수증 불일치) 실서비스 구성에서도 반려하지 않는다."""
    from app.schemas.common import Mismatch

    policy = map_team_settings(REAL_SETTINGS)
    result = evaluate_guardrails(
        _opinions(budget="fail"),
        [Mismatch(field="amount", claimed="90000", receipt="50000")],
        policy,
        amount=90_000,
    )

    assert result.decision == "escalate"
    assert "receipt_mismatch" in result.triggered_rules


def test_auto_approve_off_escalates_even_with_budget_fail():
    """판정 권한이 없으면 반려도 못 한다 — 실서비스 기본값(auto_approve=False) 경로."""
    policy = map_team_settings({"auto_approve": False, "auto_approve_limit": 50_000})
    result = evaluate_guardrails(_opinions(budget="fail"), [], policy, amount=10_000)

    assert result.decision == "escalate"
    assert "auto_approve_disabled" in result.triggered_rules
