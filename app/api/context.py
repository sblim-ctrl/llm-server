"""컨텍스트 갱신 (REQ-041) — 회칙 변경 수신과 반영 상태 조회.

회칙이 바뀌면 백엔드가 `/refresh`로 알려 주고, 우리는 원문을 조회해 조항 단위로 쪼개
임베딩한 뒤 인덱스를 갈아끼운다(fetch→chunk→embed→upsert). 인덱싱은 잡으로 비동기
처리한다.

`/status`가 있는 이유: 인덱싱은 202로 접수만 하고 끝나서, 실패해도 백엔드가 알 방법이
없었다. 그 상태로 두면 관리자는 마법사에서 회칙을 등록하고 "설정 완료"까지 눌렀는데
심사는 회칙 없이(기본 정책 모드로) 돌아가고, 아무도 눈치채지 못한다. 조용한 실패라
더 나쁘다.
"""
from fastapi import APIRouter

from app.db.pool import get_context_status, insert_job
from app.schemas.analyze import AnalyzeAccepted, ContextRefreshRequest
from app.schemas.context import ContextStatus
from app.schemas.ids import BigIntId

router = APIRouter(prefix="/v1", tags=["context"])


@router.post("/context/refresh", response_model=AnalyzeAccepted, status_code=202)
async def refresh_context(req: ContextRefreshRequest) -> AnalyzeAccepted:
    """회칙 변경을 알린다. 접수만 하고 인덱싱은 비동기로 처리한다.

    반환된 `job_id`로 `GET /v1/jobs/{job_id}`를 조회하면 인덱싱 성공 여부를 볼 수 있고,
    아래 `/context/status`로 팀 단위 현재 상태를 볼 수도 있다.
    """
    job_id = await insert_job(
        team_id=req.team_id,
        job_type="context_refresh",
        payload=req.model_dump(mode="json"),
    )
    return AnalyzeAccepted(job_id=job_id)


@router.get("/context/status", response_model=ContextStatus,
            summary="팀 회칙 인덱싱 상태 조회")
async def read_context_status(team_id: BigIntId) -> ContextStatus:
    """이 팀 회칙이 실제로 심사에 반영될 수 있는 상태인지 알려준다.

    `indexed=false`면 회칙 기준 심사가 되지 않는다. 그 경우 심사는 모임 유형별 기본
    정책으로 진행되며(반려는 하지 않고 관리자 확인으로 보낸다), 예산·판례 심사는 정상
    동작한다.

    마법사 3단계에서 회칙을 등록하신 뒤 이 값을 확인해 "AI가 회칙 N개 조항을 읽었어요"
    처럼 보여주시면 관리자가 반영 여부를 알 수 있다.
    """
    row = await get_context_status(team_id)
    return ContextStatus(
        team_id=team_id,
        indexed=row["chunk_count"] > 0,
        chunk_count=row["chunk_count"],
        version=row["version"],
        indexed_at=row["indexed_at"].isoformat() if row["indexed_at"] else None,
    )
