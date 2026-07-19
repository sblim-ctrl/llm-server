"""proposals API 계약 모델 (§6, C2) — BudgetPlanner·PolicyDrafter 개정 모드가 공유."""

from typing import Any, Literal

from pydantic import BaseModel


class ProposalAccepted(BaseModel):
    proposal_id: str


class ProposalPatch(BaseModel):
    """관리자 결정 기록 (§9 수락률 지표의 기록 경로)."""

    status: Literal["accepted", "dismissed"]
    decided_by: str


class ProposalOut(BaseModel):
    id: str
    team_id: str
    type: str  # budget | rule_amendment
    payload: dict[str, Any]
    status: str  # proposed | accepted | dismissed
    decided_by: str | None = None
    created_at: str
    decided_at: str | None = None
