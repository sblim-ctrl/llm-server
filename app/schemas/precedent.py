"""POST /v1/precedents 계약 — 관리자 결정 수신 (REQ-042, §7.2).

백엔드가 에스컬레이션 건에 대한 관리자 결정을 push하는 방향으로 설계
(§7.2 '협의 가능' 항목 — 확정 시 필드 조정 가능성 있음).
"""
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ExpenseClaim


class PrecedentCreate(BaseModel):
    team_id: str
    expense_id: str
    claim: ExpenseClaim
    decision: Literal["approve", "reject"]
    reason: str
    is_override: bool = False       # AI 추천을 뒤집은 결정인가 (학습 가치 높음)
    rule_version: int | None = None


class PrecedentCreated(BaseModel):
    precedent_id: str
