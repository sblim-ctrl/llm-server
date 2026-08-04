"""마법사 2단계 값 → 심사 파라미터 매핑 계약 (풀스택 협의 대상).

2단계 화면에는 LLM 서버 API가 없지만, 백엔드 team_settings에 저장된 값이 매 심사마다
load_context를 거쳐 PolicyParams가 되고 guardrail_gate 판정을 가른다. 이 경로가 조용히
어긋나면 화면에서 설정한 대로 심사가 되지 않고 그 사실이 화면에 드러나지 않는다 —
2026-07-31에 실제로 그 상태였다(화면_대조_2026-07-29.md §7):

  - escalation_threshold(금액)를 confidence_threshold(0~1 θ)에 대입 → 실연동 시
    θ=200000.0이 되어 adjudicate의 임계 비교가 상시 거짓 → 전건 에스컬레이션
  - force_escalation_amount는 백엔드 값을 아예 안 읽어 항상 모델 기본값 200,000 고정
    → 관리자가 2단계에서 10만·30만을 골라도 심사는 20만으로 동작

PR #8이 고친 그 매핑을 여기서 잠근다. 명세: docs/마법사_API_명세.md '2단계 승인 정책'.
"""
from unittest.mock import AsyncMock, patch

from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails
from app.graphs.review.nodes.load_context import load_context
from app.schemas.common import ExpenseClaim, Opinion, PolicyParams
from app.tools.policy_params import map_team_settings

CLEAN = {
    "rule": Opinion(auditor="rule", verdict="pass", summary="이상 없음"),
    "budget": Opinion(auditor="budget", verdict="pass", summary="잔액 충분"),
    "precedent": Opinion(auditor="precedent", verdict="pass", summary="판례 없음"),
}


async def _policy_from(settings: dict | Exception) -> PolicyParams:
    """team_settings 응답 하나만 바꿔가며 load_context가 만드는 PolicyParams를 얻는다."""
    settings_mock = (AsyncMock(side_effect=settings) if isinstance(settings, Exception)
                     else AsyncMock(return_value=settings))
    with patch("app.graphs.review.nodes.load_context.get_team_settings", settings_mock), \
         patch("app.graphs.review.nodes.load_context.get_team_profile",
               AsyncMock(return_value={"team_type": "스터디"})), \
         patch("app.graphs.review.nodes.load_context.get_team_members",
               AsyncMock(return_value=[])):
        updates = await load_context({
            "team_id": 9001,
            "expense_id": 90001,
            "claim": ExpenseClaim(title="교재", amount=32_000, category="교재/자료비",
                                  date="2026-07-01", description=""),
        })
    return updates["policy_params"]


async def test_escalation_threshold_is_an_amount_not_a_confidence():
    """백엔드 escalation_threshold(금액)는 force_escalation_amount로 간다.

    θ(confidence_threshold)에 들어가면 실연동에서 전건 에스컬레이션이 된다.
    """
    policy = await _policy_from({
        "auto_approve": True, "auto_approve_limit": 50_000,
        "escalation_threshold": 300_000,
    })
    assert policy.force_escalation_amount == 300_000
    assert policy.confidence_threshold == 0.8   # θ는 백엔드에서 받지 않는다


async def test_admin_chosen_amount_actually_reaches_the_gate():
    """관리자가 2단계에서 고른 금액이 판정을 바꾼다 — 모델 기본값에 묻히지 않는다."""
    policy = await _policy_from({
        "auto_approve": True, "auto_approve_limit": 150_000,
        "escalation_threshold": 200_000,
    })
    assert policy.auto_approve_limit == 150_000
    # 12만원은 한도 15만 이내라 자동 진행 — 기본값 5만이었다면 대기로 갔을 금액
    gate = evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=policy, amount=120_000)
    assert gate.decision == "proceed"


async def test_null_auto_approve_limit_becomes_zero_full_manual():
    """DB상 null이 정상 케이스 — 0으로 읽어 전건 관리자 확인(안전 방향)."""
    policy = await _policy_from({
        "auto_approve": True, "auto_approve_limit": None,
        "escalation_threshold": 200_000,
    })
    assert policy.auto_approve_limit == 0
    gate = evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=policy, amount=1_000)
    assert gate.decision == "escalate"
    assert "over_auto_approve_limit" in gate.triggered_rules


async def test_toggle_on_means_auto_approve_false_and_blocks_every_amount():
    """'모든 지출을 직접 확인할래요' 토글 = auto_approve false (문구와 값이 반대 방향)."""
    policy = await _policy_from({
        "auto_approve": False, "auto_approve_limit": 50_000,
        "escalation_threshold": 200_000,
    })
    assert policy.auto_approve is False
    gate = evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=policy, amount=1_000)
    assert gate.decision == "escalate"
    assert "auto_approve_disabled" in gate.triggered_rules


async def test_settings_lookup_failure_is_fail_safe():
    """조회 실패 시 자동판정 권한 미확인 → 판정하지 않는다."""
    policy = await _policy_from(RuntimeError("backend down"))
    assert policy.auto_approve is False


def test_limit_boundary_is_strictly_greater_than():
    """경계는 '초과'다 — 한도와 같은 금액은 자동 승인 대상.

    화면 문구가 '50,000원 미만 자동 승인'이면 1원 어긋난다(회의 확정 항목 1번).
    """
    policy = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                          force_escalation_amount=200_000)
    assert evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=policy,
                               amount=50_000).decision == "proceed"
    assert evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=policy,
                               amount=50_001).decision == "escalate"


async def test_status_endpoint_agrees_with_review_path():
    """GET /v1/policy-params/status와 심사 경로가 같은 해석을 내놓는다.

    화면이 보는 값과 심사가 쓰는 값이 갈리면 2026-07-31 사고가 재현된다. 지금은
    load_context가 자기 사본을 갖고 있어 해석이 두 벌이라(브랜치 통합 후 일원화 예정)
    이 테스트가 유일한 안전장치다 — 한쪽만 바뀌면 여기서 잡힌다.
    """
    cases = [
        {"auto_approve": True, "auto_approve_limit": 50_000, "escalation_threshold": 200_000},
        {"auto_approve": True, "auto_approve_limit": None, "escalation_threshold": 200_000},
        {"auto_approve": False, "auto_approve_limit": 150_000, "escalation_threshold": 300_000},
        {"auto_approve": True, "auto_approve_limit": 90_000},          # 고액 기준 누락
    ]
    for raw in cases:
        assert map_team_settings(raw) == await _policy_from(raw), f"해석이 갈렸다: {raw}"

    # 조회 실패 경로도 같아야 한다
    assert map_team_settings(None) == await _policy_from(RuntimeError("down"))


async def test_missing_limit_key_currently_allows_auto_approval():
    """알려진 분기 — `auto_approve_limit` 키가 아예 없을 때 두 경로가 다르다.

    현행 cowbro `load_context`는 `.get(key, 기본값 50_000)`이라 **키 자체가 없으면**
    5만원까지 자동 승인한다. 키가 있고 값만 `null`인 경우(0으로 처리)와 다르게 동작한다.
    백엔드가 이 필드를 빠뜨리면 조용히 자동 승인이 열리므로 §8("어떤 실패도 자동
    승인으로 이어지지 않는다")에 어긋난다.

    sblim판 load_context는 누락과 null을 똑같이 0으로 본다. 브랜치 통합 시 sblim판이
    채택되므로 이 분기는 머지로 해소된다 — `map_team_settings`는 이미 안전한 쪽이다.
    지금 cowbro 쪽을 고치면 없던 머지 충돌이 생겨 손대지 않았다.

    머지 후 이 테스트는 실패한다. 그때 위 동등성 테스트의 cases에 `{}`를 넣고 이
    테스트를 지우면 된다.
    """
    safe = map_team_settings({"auto_approve": True})
    current = await _policy_from({"auto_approve": True})

    assert safe.auto_approve_limit == 0            # 안전 방향 (sblim·신규 모듈)
    assert current.auto_approve_limit == 50_000    # 현행 cowbro 심사 경로
    assert safe != current, "머지가 끝난 듯하다 — 이 테스트를 제거할 것"


async def test_status_endpoint_exposes_effective_limit():
    """화면이 두 칸을 보여줘도 실제로 자동/대기를 가르는 값은 하나 — 그걸 노출한다."""
    from app.api.policy import read_policy_params_status

    with patch("app.api.policy.get_team_settings", AsyncMock(return_value={
        "auto_approve": True, "auto_approve_limit": 50_000, "escalation_threshold": 300_000,
    })):
        status = await read_policy_params_status(organization_id=9001)

    assert status.available is True
    assert status.auto_approve_limit == 50_000
    assert status.force_escalation_amount == 300_000
    assert status.effective_auto_approve_limit == 50_000    # min(둘)
    assert status.auto_approved_up_to == 50_000
    assert "50,000원 이하" in status.summary


async def test_status_endpoint_reports_full_manual_modes():
    """토글 켬·한도 0 — 자동 승인 구간이 없으면 auto_approved_up_to는 null."""
    from app.api.policy import read_policy_params_status

    with patch("app.api.policy.get_team_settings", AsyncMock(return_value={
        "auto_approve": False, "auto_approve_limit": 50_000, "escalation_threshold": 200_000,
    })):
        toggled = await read_policy_params_status(organization_id=9001)
    assert toggled.auto_approved_up_to is None
    assert "모든 지출을 관리자가 확인" in toggled.summary

    with patch("app.api.policy.get_team_settings", AsyncMock(return_value={
        "auto_approve": True, "auto_approve_limit": None, "escalation_threshold": 200_000,
    })):
        zero = await read_policy_params_status(organization_id=9001)
    assert zero.auto_approved_up_to is None


async def test_status_endpoint_fail_safe_when_backend_down():
    """백엔드 조회 실패 → available=false, 자동판정 없음으로 보고한다."""
    from app.api.policy import read_policy_params_status

    with patch("app.api.policy.get_team_settings", AsyncMock(side_effect=RuntimeError("down"))):
        status = await read_policy_params_status(organization_id=9001)

    assert status.available is False
    assert status.auto_approve is False
    assert status.auto_approved_up_to is None


def test_force_escalation_above_limit_changes_nothing():
    """고액 기준이 소액 한도보다 크면 판정을 바꾸지 않는다 — 화면 두 칸이 사실상 하나.

    회의 확정 항목 2번의 근거. min(한도, 고액기준) 초과가 실제 규칙이다.
    """
    base = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                        force_escalation_amount=200_000)
    raised = base.model_copy(update={"force_escalation_amount": 300_000})
    amounts = [10_000, 50_000, 50_001, 120_000, 199_999, 200_001, 500_000]
    for amt in amounts:
        a = evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=base, amount=amt)
        b = evaluate_guardrails(opinions=CLEAN, mismatch=[], policy=raised, amount=amt)
        assert a.decision == b.decision, f"{amt:,}원에서 판정이 갈렸다"
