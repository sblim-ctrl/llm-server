"""POST /v1/analyze — 심사 잡 생성 (202 + job_id). LLM 호출 없음 — 그래프 실행은 워커 몫 (§2.2)."""
from fastapi import APIRouter

from app.config import get_settings
from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted, AnalyzeRequest

router = APIRouter(prefix="/v1", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeAccepted, status_code=202)
async def create_analyze_job(req: AnalyzeRequest) -> AnalyzeAccepted:
    job_id = await insert_job(
        team_id=req.team_id,
        job_type="review",
        payload=req.model_dump(mode="json"),
        expense_id=req.expense_id,
        max_attempts=get_settings().job_max_attempts,
    )
    return AnalyzeAccepted(job_id=job_id)
