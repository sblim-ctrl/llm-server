"""POST /v1/digests — AI 총무 주간 브리핑 잡 생성 (§4.4-c, A-4). 결과는 GET /v1/jobs/{id}.

주간 스케줄 트리거는 백엔드 소관(설계 §7.2) — LLM 서버는 수동 트리거만 구현.
"""
from fastapi import APIRouter

from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.writers import DigestRequest

router = APIRouter(prefix="/v1", tags=["digests"])


@router.post("/digests", response_model=AnalyzeAccepted, status_code=202)
async def create_digest_job(req: DigestRequest) -> AnalyzeAccepted:
    job_id = await insert_job(team_id=req.team_id, job_type="digest",
                              payload=req.model_dump(mode="json"))
    return AnalyzeAccepted(job_id=job_id)
