"""/v1/analyze 및 잡 조회 API 계약 — pull 모델 (bravo 기술아키텍처설계서 TABLE 18).

백엔드가 보내는 필드는 5개뿐: jobId·expenseId·organizationId·심사목표·영수증 조회
경로. 지출 상세(제목·금액·카테고리 등)는 요청에 없다 — load_context 노드가
organizationId+expenseId로 백엔드에 되물어 가져온다(pull). 백엔드 전 API가
camelCase이므로 이 요청도 camelCase 키로 온다고 가정한다(reviewGoal·receiptPath는
정확한 키 이름 미확정 — 풀스택 질의요청서 회신 후 alias만 조정하면 됨).
populate_by_name=True라 내부 도구·테스트의 snake_case 호출도 그대로 동작한다.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

JobStatus = Literal["queued", "running", "succeeded", "failed", "dead"]


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # 백엔드가 발급한 잡 ID — 콜백 때 그대로 echo해야 백엔드가 expenses.ai_job_id와
    # 대조해 유효성을 검증한다(재제출로 무효화된 옛 jobId면 무시). 우리 내부 jobs.id와는
    # 별도로 external_job_id 컬럼에 매핑 저장한다.
    job_id: str
    expense_id: str
    organization_id: str            # 구 team_id — 내부 상태 키는 team_id를 유지한다
    review_goal: str = ""           # 심사 목표 자연어 지시문 (프롬프트 반영은 TODO — 프롬프트 트랙)
    receipt_path: str | None = None  # Spring 내부 영수증 조회 경로 (없으면 영수증 미첨부)


class AnalyzeAccepted(BaseModel):
    """202 응답. job_id는 우리 내부 jobs.id — 같은 지출의 동시 제출이 하나의 잡으로
    dedupe됐는지가 이 값으로 드러난다(멱등성 스트레스 테스트·대시보드 폴링용).
    백엔드는 자기가 발급한 jobId(external_job_id로 echo)로도 GET /v1/jobs/{id} 조회
    가능. 응답 키 형식(camelCase 여부)은 미확정이라 내부 관례(snake_case) 유지.
    """
    job_id: str
    external_job_id: str | None = None
    status: JobStatus = "queued"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    attempts: int
    result: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ContextRefreshRequest(BaseModel):
    """REQ-041 컨텍스트 갱신 이벤트."""
    team_id: str
    change_type: Literal["rule", "category", "params"]
    version: int
