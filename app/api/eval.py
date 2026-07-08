"""GET /v1/eval/golden — 골든셋 회귀를 API로 노출 (대시보드 전용, §9.1).

내부 검증 도구다. 쓰기 작업이 없어 MCP 읽기 툴과 같은 성격 — 서비스 토큰 인증은
그대로 적용된다(AuthMiddleware). CLI(eval/run_eval.py)와 로직을 공유(app/eval_support.py).
"""
from fastapi import APIRouter

from app.eval_support import run_golden_set

router = APIRouter(prefix="/v1/eval", tags=["eval"])


@router.get("/golden")
async def get_golden_eval() -> dict:
    return await run_golden_set()
