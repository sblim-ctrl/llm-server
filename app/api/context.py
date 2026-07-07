"""POST /v1/context/refresh — REQ-041 컨텍스트 갱신 이벤트 수신.

TODO(2주차): 인덱싱 파이프라인 그래프(fetch→chunk→embed→upsert) 연결.
지금은 잡 등록까지만 (워커의 context_refresh 핸들러는 스텁).
"""
from fastapi import APIRouter

from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted, ContextRefreshRequest

router = APIRouter(prefix="/v1", tags=["context"])


@router.post("/context/refresh", response_model=AnalyzeAccepted, status_code=202)
async def refresh_context(req: ContextRefreshRequest) -> AnalyzeAccepted:
    job_id = await insert_job(
        team_id=req.team_id,
        job_type="context_refresh",
        payload=req.model_dump(mode="json"),
    )
    return AnalyzeAccepted(job_id=job_id)
