"""컨텍스트 반영 상태 계약 — GET /v1/context/status."""

from pydantic import BaseModel

from app.schemas.ids import BigIntId


class ContextStatus(BaseModel):
    team_id: BigIntId
    # false면 회칙 기준 심사가 되지 않는다 — 유형별 기본 정책으로 진행된다
    indexed: bool
    chunk_count: int          # 인덱싱된 조항 수
    version: int | None       # 반영된 회칙 버전 (policies.version)
    indexed_at: str | None    # ISO8601. 미인덱싱이면 null
