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
    # dry-run 기능은 Sprint 1 범위 외(P2) — 콜백 필드만 선반영 (업무분장 C5·§4)
    dry_run: bool = False

    # model_version·prompt_version·cost_usd·latency_ms는 2026-08-03 제거했다.
    # 지출 상세 화면 4종 어디에도 표시되지 않는 관측 전용값이라 백엔드로 보낼 이유가
    # 없었다 (`docs/internal/화면_대조_2026-08-03.md` §4). 값 자체는 worker가
    # jobs.result에 남기므로 GET /v1/jobs/{job_id}로 되짚을 수 있다.
