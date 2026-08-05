"""GET /v1/jobs/{job_id} — 잡 상태·결과 조회 (백엔드 폴링 fallback, §7.1)."""
from fastapi import APIRouter, HTTPException

from app.db.pool import get_job
from app.schemas.analyze import JobStatusResponse

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobStatusResponse,
            summary="잡 상태·결과 조회 (콜백 안전망)")
async def read_job(job_id: str) -> JobStatusResponse:
    """심사·생성 잡의 진행 상태와 결과를 조회한다.

    콜백이 유실됐을 때의 **폴링 안전망**(§7.1). `job_id`는 우리 내부 id와 백엔드가
    발급한 jobId **둘 다** 받는다.

    `status`: `queued` → `running` → `succeeded` / `failed` / `dead`.
    `succeeded`면 `result`에 심사 결과(verdict·reasons·opinions 등)가 담긴다.
    """
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=str(job["id"]),
        status=job["status"],
        attempts=job["attempts"],
        result=job["result"],
        created_at=job["created_at"].isoformat(),
        updated_at=job["updated_at"].isoformat(),
    )
