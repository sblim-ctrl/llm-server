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
from app.schemas.ids import BigIntId


class CallbackPayload(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str
    expense_id: BigIntId
    team_id: BigIntId
    verdict: Verdict  # → API-046 finalVerdict
    suggested_category: str | None = None  # → API-046 suggestedCategory (classify_category 결과)
    # → API-046 processedBy. '최종 처리를 누가 했는가'를 뜻한다.
    # escalate는 아직 최종 처리자가 없는 상태이므로 null을 보낸다 — 그 시점에 "AI"를
    # 보내면 관리자 확인 대기 건이 화면에 'AI가 처리함'으로 뜬다. 관리자가 승인·반려하면
    # 백엔드가 그때 "ADMIN"을 기입한다(우리는 그 시점을 알 수 없다).
    # 이 규칙 덕에 프론트의 'AI 자동처리' 배지 조건이 processedBy == "AI" 한 줄이 된다
    # (AI가 처음부터 끝까지 판단한 건만 AI로 남으므로). 팀 결정 2026-07-31.
    processed_by: str | None = "AI"
    confidence: float | None = None
    opinions: list[Opinion] = []               # → API-045 detail의 근거 재료 (백엔드가 조합)
    mismatch: list[Mismatch] = []
    reasons: Reasons | None = None             # → API-045 detail의 근거 재료
    model_version: str = "mock"
    prompt_version: str = "review/v1"
    cost_usd: float = 0.0
    latency_ms: int = 0
    # dry-run 기능은 Sprint 1 범위 외(P2) — 콜백 필드만 선반영 (업무분장 C5·§4)
    dry_run: bool = False
