"""GET /v1/eval/golden · /v1/eval/writers — 골든셋 회귀를 API로 노출 (대시보드 전용, §9.1).

내부 검증 도구다. 심사 쪽은 쓰기 작업이 없고, 라이터 쪽은 전용 평가 팀
(eval-writers-bf-*)의 판례 시드만 갱신한다 — 서비스 토큰 인증은 그대로
적용된다(AuthMiddleware). CLI(eval/run_eval*.py)와 로직을 공유.
"""
from fastapi import APIRouter

from app.eval_support import run_golden_set
from app.eval_writers import run_writers_golden_set

router = APIRouter(prefix="/v1/eval", tags=["eval"])


@router.get("/golden")
async def get_golden_eval() -> dict:
    return await run_golden_set()


@router.get("/writers")
async def get_writers_eval() -> dict:
    return await run_writers_golden_set()
