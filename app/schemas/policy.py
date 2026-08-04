"""승인 정책 반영 상태 계약 — GET /v1/policy-params/status (마법사 2단계).

2단계 화면이 저장한 값이 실제로 심사에 어떻게 적용되는지 되돌려 보여준다.
`ContextStatus`(3단계 회칙 반영 확인)와 같은 목적이다 — 조용한 실패를 화면에 드러낸다.
"""

from pydantic import BaseModel

from app.schemas.ids import BigIntId


class PolicyParamsStatus(BaseModel):
    team_id: BigIntId

    # ── 백엔드 team_settings 원본 (조회 실패 시 available=false) ──
    available: bool           # false면 아래 값은 fail-safe 기본값이다
    auto_approve: bool        # 2단계 토글의 반대 — 토글을 켜면 false
    auto_approve_limit: int   # 소액 자동 승인 한도. 백엔드 null → 0
    force_escalation_amount: int   # 백엔드 escalation_threshold(금액)

    # ── 실제로 심사를 가르는 값 ──
    # 두 금액 규칙 모두 '관리자 확인'으로 귀결되므로 실효 한도는 항상 둘 중 작은 쪽이다.
    # 화면이 두 칸을 독립 설정처럼 보여줘도 자동/대기를 가르는 것은 이 값 하나다.
    effective_auto_approve_limit: int
    # 이 금액 '이하'까지 자동 판정으로 진행된다(초과부터 관리자 확인). auto_approve가
    # 꺼져 있으면 금액과 무관하게 전건 관리자 확인이라 null.
    auto_approved_up_to: int | None
    # 화면에 그대로 띄울 수 있는 한 줄 설명
    summary: str
