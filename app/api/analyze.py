"""POST /v1/analyze — 심사 잡 수락 (202). LLM 호출 없음 — 그래프 실행은 워커 몫 (§2.2).

pull 모델 (bravo 설계서 TABLE 18): 백엔드가 jobId·expenseId·organizationId·
심사목표·영수증 경로 5필드만 보낸다. jobId는 백엔드 발급 — 내부 jobs.id와 별도로
external_job_id에 매핑하고, 응답·콜백에서는 백엔드 jobId를 그대로 쓴다.
"""
from fastapi import APIRouter

from app.config import get_settings
from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted, AnalyzeRequest

router = APIRouter(prefix="/v1", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeAccepted, status_code=202)
async def create_analyze_job(req: AnalyzeRequest) -> AnalyzeAccepted:
    job_id = await insert_job(
        team_id=req.organization_id,
        job_type="review",
        payload=req.model_dump(mode="json"),
        expense_id=req.expense_id,
        max_attempts=get_settings().job_max_attempts,
        dedupe_active=True,  # 같은 지출의 활성 잡이 있으면 재사용 (§8 멱등성)
        external_job_id=req.job_id,
    )
    # job_id=내부 jobs.id (dedupe 가시성), external_job_id=백엔드 발급 jobId echo —
    # 폴링 조회(GET /v1/jobs/{id})는 어느 쪽 값으로도 가능
    return AnalyzeAccepted(job_id=job_id, external_job_id=req.job_id)
