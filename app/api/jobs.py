"""GET /v1/jobs/{job_id} — 잡 상태·결과 조회 (백엔드 폴링 fallback, §7.1)."""
from fastapi import APIRouter, HTTPException

from app.db.pool import get_job
from app.schemas.analyze import JobStatusResponse

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def read_job(job_id: str) -> JobStatusResponse:
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
