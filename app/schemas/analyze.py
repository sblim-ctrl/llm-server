"""/v1/analyze 및 잡 조회 API 계약 (§7.2)."""
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import ExpenseClaim

JobStatus = Literal["queued", "running", "succeeded", "failed", "dead"]


class AnalyzeRequest(BaseModel):
    expense_id: str
    team_id: str
    claim: ExpenseClaim
    receipt_signed_url: str | None = None


class AnalyzeAccepted(BaseModel):
    job_id: str
    status: JobStatus = "queued"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    attempts: int
    result: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ContextRefreshRequest(BaseModel):
    """REQ-041 컨텍스트 갱신 이벤트."""
    team_id: str
    change_type: Literal["rule", "category", "params"]
    version: int
