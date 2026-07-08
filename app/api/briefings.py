"""POST /v1/briefings — 인수인계 브리핑 잡 생성 (§7.2). 결과는 GET /v1/jobs/{id}."""
from fastapi import APIRouter

from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.writers import BriefingRequest

router = APIRouter(prefix="/v1", tags=["briefings"])


@router.post("/briefings", response_model=AnalyzeAccepted, status_code=202)
async def create_briefing_job(req: BriefingRequest) -> AnalyzeAccepted:
    job_id = await insert_job(team_id=req.team_id, job_type="briefing",
                              payload=req.model_dump(mode="json"))
    return AnalyzeAccepted(job_id=job_id)
