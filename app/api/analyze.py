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


@router.post("/analyze", response_model=AnalyzeAccepted, status_code=202,
             summary="지출 심사 요청 (백엔드 → Agent Server)")
async def create_analyze_job(req: AnalyzeRequest) -> AnalyzeAccepted:
    """지출 1건의 AI 심사를 요청한다. **즉시 202로 접수만 하고 심사는 비동기 실행**된다.

    **pull 모델** — 요청에는 5필드만 담는다(지출 상세·예산·회칙은 Agent Server가
    백엔드 내부 API로 되물어 조회. `docs/백엔드_요구_내부API_명세.md` 참조).

    - `jobId`: 백엔드가 발급. 콜백에서 그대로 echo되므로 `expenses.ai_job_id` 대조 가능
    - `expenseId` / `organizationId`(= teams.id): 지출·모임 식별자
    - `reviewGoal`: 심사 목표 자연어 지시문
    - `receiptPath`: 영수증 조회 경로 (없으면 미첨부로 심사)

    **결과 수신 2경로**: ① 심사 완료 시 `POST {백엔드}/agent-callback` 으로 전송(주경로,
    3회 재시도) ② `GET /v1/jobs/{id}` 폴링(안전망 — 내부 job_id·백엔드 jobId 둘 다 조회 가능)

    **멱등성**: 같은 지출의 활성 잡이 있으면 새로 만들지 않고 재사용한다(중복 심사·
    이중 콜백 방지). 응답의 `job_id`가 같으면 기존 잡에 수렴한 것.
    """
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
