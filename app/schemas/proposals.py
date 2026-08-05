"""proposals API 계약 모델 (§6, C2) — BudgetPlanner·PolicyDrafter 개정 모드가 공유."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.ids import BigIntId


class ProposalBudgetRequest(BaseModel):
    team_id: BigIntId
    # "YYYY-MM" — 미지정 시 실행 시점의 당월. 형식 검증 필수: 무검증 시 잘못된
    # 값이 202로 수락된 뒤 워커의 date.fromisoformat에서 ValueError → 3회
    # 재시도 후 dead로 소진된다 (리뷰 발견 — 조기 422 거부로 대체).
    period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class RuleAmendmentRequest(BaseModel):
    team_id: BigIntId


class ProposalAccepted(BaseModel):
    proposal_id: str


class ProposalPatch(BaseModel):
    """관리자 결정 기록 (§9 수락률 지표의 기록 경로)."""

    status: Literal["accepted", "dismissed"]
    decided_by: str


class ProposalOut(BaseModel):
    id: str
    team_id: BigIntId
    type: str  # budget | rule_amendment | rule_draft
    payload: dict[str, Any]
    status: str  # proposed | accepted | dismissed
    decided_by: str | None = None
    created_at: str
    decided_at: str | None = None
