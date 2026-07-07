"""백엔드 콜백 스키마 (§7.2 — 회의 합의 필드). 계약 변경 시 풀스택 팀 리뷰 필수."""
from pydantic import BaseModel

from app.schemas.common import Mismatch, Opinion, Reasons, Verdict


class CallbackPayload(BaseModel):
    job_id: str
    expense_id: str
    team_id: str
    verdict: Verdict
    confidence: float | None = None
    opinions: list[Opinion] = []
    mismatch: list[Mismatch] = []
    reasons: Reasons | None = None
    model_version: str = "mock"
    prompt_version: str = "review/v1"
    cost_usd: float = 0.0
    latency_ms: int = 0
