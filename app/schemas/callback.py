"""백엔드 콜백 스키마 (§7.2). 필드 대조 근거: `기획/bravo_API명세서.xlsx`
API-045(GET /expenses/{id}/review-result) 응답 review{finalVerdict, detail,
suggestedCategory, processedBy, createdAt} — 실제 필드명·타입 확정판(2026-07-15
수령). 계약 변경 시 풀스택 팀 리뷰 필수.

백엔드 전체 API가 camelCase이므로(§ 위 명세서 전 API 공통) 이 페이로드도
직렬화 시 camelCase로 나가야 한다 — `model_dump(mode="json", by_alias=True)`로
호출할 것(snake_case로 내보내면 백엔드가 필드를 못 찾는다).
"""
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas.common import Mismatch, Opinion, Reasons, Verdict


class CallbackPayload(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str
    expense_id: str
    team_id: str
    verdict: Verdict                          # → API-045 finalVerdict
    suggested_category: str | None = None      # → API-045 suggestedCategory (classify_category 결과)
    processed_by: str = "AI"                   # → API-045 processedBy (관리자 override 시 백엔드가 갱신)
    confidence: float | None = None
    opinions: list[Opinion] = []               # → API-045 detail의 근거 재료 (백엔드가 조합)
    mismatch: list[Mismatch] = []
    reasons: Reasons | None = None             # → API-045 detail의 근거 재료
    model_version: str = "mock"
    prompt_version: str = "review/v1"
    cost_usd: float = 0.0
    latency_ms: int = 0
