"""FastAPI 앱 — 라우터·미들웨어 조립만 (§11.1). LLM 호출은 워커에만 존재 (§10.2)."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import (
    analyze, briefings, context, drafts, eval as eval_api, health, jobs, precedents, reports,
)
from app.db.pool import apply_schema, close_pool, open_pool
from app.middleware.auth import AuthMiddleware
from app.middleware.request_log import RequestLogMiddleware

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    await apply_schema()
    yield
    await close_pool()  # graceful shutdown (§10.2)


app = FastAPI(
    title="BudgetOps LLM API",
    version="0.1.0",
    description="지출 자동 심사 에이전트 서버 — 잡 등록·상태 조회 (그래프 실행은 llm-worker)",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLogMiddleware)

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(jobs.router)
app.include_router(context.router)
app.include_router(precedents.router)
app.include_router(drafts.router)
app.include_router(reports.router)
app.include_router(briefings.router)
app.include_router(eval_api.router)


@app.get("/ui", include_in_schema=False)
async def dashboard():
    """내부 검증 대시보드 — 팀이 파이프라인 동작을 직접 눌러 확인하는 개발용 페이지.

    별도 서버·포트 없이 llm-api가 그대로 서빙한다. 페이지 자체는 인증 없이 열리고,
    페이지 안의 API 호출(fetch)이 서비스 토큰을 실어 보낸다(AuthMiddleware 그대로 적용).
    """
    return FileResponse(STATIC_DIR / "dashboard.html")


# TODO(5주차): FastMCP 서버 마운트 — 읽기 툴 4종 노출 (§5.2)
