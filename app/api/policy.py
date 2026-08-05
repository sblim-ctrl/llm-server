"""승인 정책 반영 상태 — 마법사 2단계 확인용.

`/context/status`(3단계 회칙 반영 확인)와 같은 이유로 있다. 2단계는 저장이 백엔드
소관이라 우리 쪽 저장 API가 없는데, **저장된 값은 매 심사마다 우리가 조회해 판정에
쓴다.** 그래서 값이 어긋나도 화면에는 드러나지 않는다 — 실제로 2026-07-31에
`escalation_threshold`(금액)를 확신도 θ에 대입하고 `force_escalation_amount`는 아예
읽지 않아, 관리자가 2단계에서 10만·30만을 골라도 심사는 20만으로 동작했다
(`docs/internal/화면_대조_2026-07-29.md` §7). 조용한 실패라 더 나쁘다.

이 엔드포인트는 읽기 전용이다 — 정책을 바꾸지 않는다(저장은 백엔드 소관, 규율 3).
"""

from fastapi import APIRouter

from app.schemas.ids import BigIntId
from app.schemas.policy import PolicyParamsStatus
from app.tools.backend_client import get_team_settings
from app.tools.policy_params import (
    auto_approved_up_to,
    describe,
    effective_auto_approve_limit,
    map_team_settings,
)

router = APIRouter(prefix="/v1", tags=["policy"])


@router.get(
    "/policy-params/status",
    response_model=PolicyParamsStatus,
    summary="마법사 2단계 승인 정책이 심사에 어떻게 적용되는지 조회",
)
async def read_policy_params_status(organization_id: BigIntId) -> PolicyParamsStatus:
    """2단계에서 저장한 값이 실제 심사에 어떤 기준으로 적용되는지 돌려준다.

    마법사 2단계나 관리자 설정 화면에서 저장 직후 호출해 `summary`를 그대로 보여주면,
    관리자가 "내가 설정한 대로 동작하는가"를 확인할 수 있다.

    `effective_auto_approve_limit`이 실제로 자동/대기를 가르는 금액이다. 2026-08-05
    화면 개편으로 금액 칸이 하나가 되어 `auto_approve_limit`과 `force_escalation_amount`는
    같은 값이 되지만, 컬럼 삭제 전 저장된 값이 남은 팀은 둘이 다를 수 있고 그때는 작은
    쪽이 실효 한도다.

    경계는 '이상'이다 — 한도가 50,000원이면 49,999원까지 자동 판정, 50,000원부터
    관리자 확인이다. 화면 표("N원 미만" / "N원 이상")와 같은 기준이다.

    `available=false`면 백엔드 team-settings 조회에 실패한 것이고, 그때 심사는
    자동판정 없이(전건 관리자 확인) 진행된다.
    """
    try:
        raw = await get_team_settings(organization_id)
        available = True
    except Exception:
        raw, available = None, False

    policy = map_team_settings(raw)
    return PolicyParamsStatus(
        team_id=organization_id,
        available=available,
        auto_approve=policy.auto_approve,
        auto_approve_limit=policy.auto_approve_limit,
        force_escalation_amount=policy.force_escalation_amount,
        effective_auto_approve_limit=effective_auto_approve_limit(policy),
        auto_approved_up_to=auto_approved_up_to(policy),
        summary=describe(policy),
    )
