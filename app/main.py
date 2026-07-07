"""FastAPI 앱 — 라우터·미들웨어 조립만 (§11.1). LLM 호출은 워커에만 존재 (§10.2)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import analyze, context, health, jobs
from app.db.pool import apply_schema, close_pool, open_pool
from app.middleware.auth import AuthMiddleware
from app.middleware.request_log import RequestLogMiddleware

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

# TODO(5주차): /v1/policy-draft, /v1/reports/summary, /v1/briefings 라우터 (§7.2)
# TODO(5주차): FastMCP 서버 마운트 — 읽기 툴 4종 노출 (§5.2)
