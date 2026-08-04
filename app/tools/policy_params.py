"""마법사 2단계 설정값 → 심사 파라미터 매핑 (백엔드 team_settings 해석).

`load_context`가 심사 경로에서 하는 것과 같은 해석을 순수 함수로 뽑았다.
`GET /v1/policy-params/status`가 "저장한 값이 심사에 어떻게 적용되는가"를 되돌려
보여줄 때 같은 규칙을 써야 하기 때문이다 — 해석이 두 벌이면 화면과 심사가 갈린다.

주의: 지금은 `load_context.py`가 자기 사본을 갖고 있어 두 벌이다. 브랜치 통합
(`docs/internal/프롬프트_브랜치_통합계획_2026-08-04.md`)에서 sblim판 load_context가
채택되므로, **머지 이후에** load_context가 이 함수를 쓰도록 바꾼다. 지금 바꾸면 없던
머지 충돌이 생긴다. 그동안의 안전장치는 `tests/test_wizard_step2_mapping.py`의
동등성 테스트다 — 두 경로가 어긋나면 즉시 실패한다.

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
                           아니다 — θ는 백엔드가 모르는 LLM 내부 파라미터라 분리한다
    """
    if settings is None:
        return PolicyParams(auto_approve=False)

    defaults = PolicyParams()
    limit = settings.get("auto_approve_limit")
    force = settings.get("escalation_threshold")
    return PolicyParams(
        auto_approve=bool(settings.get("auto_approve", False)),
        auto_approve_limit=int(limit) if limit is not None else 0,
        force_escalation_amount=(
            int(force) if force is not None else defaults.force_escalation_amount
        ),
    )


def effective_auto_approve_limit(policy: PolicyParams) -> int:
    """실제로 자동/대기를 가르는 금액.

    `auto_approve_limit` 초과와 `force_escalation_amount` 초과가 **둘 다** 관리자
    확인으로 귀결되므로(guardrail_gate 4번), 실효 한도는 항상 둘 중 작은 쪽이다.
    화면이 두 칸을 독립 설정처럼 보여줘도 판정을 가르는 것은 이 값 하나다.
    """
    return min(policy.auto_approve_limit, policy.force_escalation_amount)


def describe(policy: PolicyParams) -> str:
    """화면에 그대로 띄울 수 있는 한 줄 설명."""
    if not policy.auto_approve:
        return "자동 심사를 사용하지 않습니다 — 모든 지출을 관리자가 확인합니다."
    limit = effective_auto_approve_limit(policy)
    if limit <= 0:
        return "자동 승인 한도가 0원이라 모든 지출을 관리자가 확인합니다."
    return (f"{limit:,}원 이하는 AI가 자동 판정하고, "
            f"{limit:,}원을 넘으면 관리자가 확인합니다.")
