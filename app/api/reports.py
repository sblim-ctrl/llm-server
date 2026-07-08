"""POST /v1/reports/summary — 정산 리포트 잡 생성 (§7.2). 결과는 GET /v1/jobs/{id}."""
from fastapi import APIRouter

from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.writers import ReportRequest

router = APIRouter(prefix="/v1", tags=["reports"])


@router.post("/reports/summary", response_model=AnalyzeAccepted, status_code=202)
async def create_report_job(req: ReportRequest) -> AnalyzeAccepted:
    job_id = await insert_job(team_id=req.team_id, job_type="report",
                              payload=req.model_dump(mode="json"))
    return AnalyzeAccepted(job_id=job_id)
