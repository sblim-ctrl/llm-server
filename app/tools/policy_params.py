"""마법사 2단계 설정값 → 심사 파라미터 매핑 (백엔드 team_settings 해석).

`load_context`가 심사 경로에서 하는 것과 같은 해석을 순수 함수로 뽑았다.
`GET /v1/policy-params/status`가 "저장한 값이 심사에 어떻게 적용되는가"를 되돌려
보여줄 때 같은 규칙을 써야 하기 때문이다 — 해석이 두 벌이면 화면과 심사가 갈린다.

브랜치 통합(2026-08-05 PR #9) 이후 `load_context.py`가 자기 사본을 버리고 이 함수를
쓴다 — 해석은 이제 한 벌이다. `tests/test_wizard_step2_mapping.py`의 동등성 테스트는
그대로 두어 사본이 다시 생기는 것을 막는다.

계약 문서: docs/마법사_API_명세.md '2단계 승인 정책'
"""

from typing import Any

from app.schemas.common import PolicyParams


def map_team_settings(settings: dict[str, Any] | None) -> PolicyParams:
    """백엔드 team_settings 응답 → PolicyParams.

    `None`(조회 실패)이면 auto_approve=False로 fail-safe — 자동판정 권한이 확인되지
    않으면 판정하지 않는다(§8).

    필드별 해석:
      auto_approve         2단계 토글의 반대. 키가 없으면 False (안전 방향)
      auto_approve_limit   DB상 NULL 허용(자동승인 미사용 팀). None → 0 = 전건 관리자 확인
      escalation_threshold **금액**이다(2026-07-27 DB 스키마 확정). 0~1 확신도 θ가
                           아니다 — θ는 백엔드가 모르는 LLM 내부 파라미터라 분리한다.
                           2026-08-05 화면 개편(금액 칸 2개 → 1개)에 맞춰 백엔드가 이
                           컬럼을 삭제하기로 했다. 없으면 auto_approve_limit과 같은
                           값으로 읽는다 — 모델 기본값 200,000이 관리자가 명시한 한도를
                           덮어 축소하는 것을 막기 위해서다. 관리자가 50만을 설정해도
                           min(500000, 200000)=200000이 되던 경로가 이 분기로 닫힌다.
    """
    if settings is None:
        return PolicyParams(auto_approve=False)

    defaults = PolicyParams()
    limit_raw = settings.get("auto_approve_limit")
    force_raw = settings.get("escalation_threshold")

    limit = int(limit_raw) if limit_raw is not None else 0
    if force_raw is not None:
        force = int(force_raw)
    elif limit_raw is not None:
        force = limit
    else:
        force = defaults.force_escalation_amount

    return PolicyParams(
        auto_approve=bool(settings.get("auto_approve", False)),
        auto_approve_limit=limit,
        force_escalation_amount=force,
    )


def effective_auto_approve_limit(policy: PolicyParams) -> int:
    """실제로 자동/대기를 가르는 금액.

    `auto_approve_limit` 이상과 `force_escalation_amount` 이상이 **둘 다** 관리자
    확인으로 귀결되므로(guardrail_gate 4번), 실효 한도는 항상 둘 중 작은 쪽이다.
    2026-08-05 화면 개편으로 금액 칸이 하나가 되어 두 값이 갈릴 경로는 사라졌지만,
    컬럼 삭제 전 저장된 값이 남아 있을 수 있어 min은 그대로 둔다.
    """
    return min(policy.auto_approve_limit, policy.force_escalation_amount)


def auto_approved_up_to(policy: PolicyParams) -> int | None:
    """이 금액까지는 자동 판정으로 진행된다. 자동 승인 구간이 없으면 None.

    경계가 '이상'이라(2026-08-05 확정) 실효 한도와 **같은** 금액부터 관리자 확인이다.
    따라서 자동 판정 상한은 한도보다 1원 낮다 — 한도 50,000이면 49,999원까지다.
    한도가 1원 이하면 자동으로 처리되는 금액 구간이 없으므로 None.
    """
    if not policy.auto_approve:
        return None
    limit = effective_auto_approve_limit(policy)
    return limit - 1 if limit > 1 else None


def describe(policy: PolicyParams) -> str:
    """화면에 그대로 띄울 수 있는 한 줄 설명."""
    if not policy.auto_approve:
        return "자동 심사를 사용하지 않습니다 — 모든 지출을 관리자가 확인합니다."
    up_to = auto_approved_up_to(policy)
    if up_to is None:
        return "자동 승인 구간이 없어 모든 지출을 관리자가 확인합니다."
    limit = effective_auto_approve_limit(policy)
    return f"{up_to:,}원까지는 AI가 자동 판정하고, {limit:,}원부터 관리자가 확인합니다."
