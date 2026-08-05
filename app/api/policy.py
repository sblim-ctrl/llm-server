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
from app.tools.policy_params import describe, effective_auto_approve_limit, map_team_settings

router = APIRouter(prefix="/v1", tags=["policy"])


@router.get("/policy-params/status", response_model=PolicyParamsStatus,
            summary="마법사 2단계 승인 정책이 심사에 어떻게 적용되는지 조회")
async def read_policy_params_status(organization_id: BigIntId) -> PolicyParamsStatus:
    """2단계에서 저장한 값이 실제 심사에 어떤 기준으로 적용되는지 돌려준다.

    마법사 2단계나 관리자 설정 화면에서 저장 직후 호출해 `summary`를 그대로 보여주면,
    관리자가 "내가 설정한 대로 동작하는가"를 확인할 수 있다.

    `effective_auto_approve_limit`을 함께 보는 것이 중요하다. 화면의 소액 한도와 고액
    기준은 둘 다 '관리자 확인'으로 귀결되므로 **실제로 자동/대기를 가르는 것은 둘 중
    작은 쪽 하나**다. 고액 기준을 소액 한도보다 크게 잡으면 그 칸은 판정에 영향을 주지
    않는다.

    경계는 '초과'다 — 한도가 50,000원이면 50,000원은 자동 판정, 50,001원부터 관리자
    확인이다.

    `available=false`면 백엔드 team-settings 조회에 실패한 것이고, 그때 심사는
    자동판정 없이(전건 관리자 확인) 진행된다.
    """
    try:
        raw = await get_team_settings(organization_id)
        available = True
    except Exception:
        raw, available = None, False

    policy = map_team_settings(raw)
    limit = effective_auto_approve_limit(policy)
    return PolicyParamsStatus(
        team_id=organization_id,
        available=available,
        auto_approve=policy.auto_approve,
        auto_approve_limit=policy.auto_approve_limit,
        force_escalation_amount=policy.force_escalation_amount,
        effective_auto_approve_limit=limit,
        auto_approved_up_to=(limit if policy.auto_approve and limit > 0 else None),
        summary=describe(policy),
    )
