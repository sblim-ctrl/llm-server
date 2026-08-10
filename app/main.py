"""FastAPI 앱 — 라우터·미들웨어 조립만 (§11.1). LLM 호출은 워커에만 존재 (§10.2)."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.api import (
    analyze,
    briefings,
    categories,
    context,
    dashboards,
    digests,
    drafts,
    eval as eval_api,
    health,
    jobs,
    policy,
    precedents,
    proposals,
    reports,
    reviews_stream,
)
from app.config import get_settings
from app.db.pool import apply_schema_locked, close_pool, open_pool, setup_checkpointer_locked
from app.mcp_server import mcp_app, mcp_session_manager
from app.tools.backend_client import close_backend_client
from app.observability import setup_langsmith
from app.middleware.auth import PUBLIC_PATHS, AuthMiddleware
from app.middleware.request_log import RequestLogMiddleware

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_langsmith()  # B3 — PolicyDrafter 동기 호출(§2.2 예외)도 트레이싱 대상
    await open_pool()
    await apply_schema_locked()  # --workers 2 + 잡 워커 동시 기동 안전 (pool.py 참고)
    # HITL 체크포인터 — 워커(worker.py main)와 같은 AsyncPostgresSaver를 앱 수명으로
    # 연다. 멈춘 심사가 Postgres에 남아 --workers N의 다른 프로세스·재시작 후에도
    # 재개된다 (reviews_stream 모듈 docstring 참고).
    async with AsyncPostgresSaver.from_conn_string(get_settings().database_url) as checkpointer:
        await setup_checkpointer_locked(checkpointer)  # 동시 기동 안전 (pool.py 참고)
        reviews_stream.init_hitl_graph(checkpointer)
        async with mcp_session_manager():  # MCP Streamable HTTP 세션 (§5.2)
            yield
    await close_backend_client()  # 공유 httpx 클라이언트 정리
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
app.include_router(reviews_stream.router)  # 실시간 심사 SSE (데모·관측 전용)
app.include_router(jobs.router)
app.include_router(context.router)
app.include_router(policy.router)  # 마법사 2단계 승인 정책 반영 상태
app.include_router(precedents.router)
app.include_router(drafts.router)
app.include_router(categories.router)
app.include_router(reports.router)
app.include_router(briefings.router)
app.include_router(digests.router)
app.include_router(dashboards.router)  # 대시보드 AI 요약 (동기)
app.include_router(proposals.router)
app.include_router(eval_api.router)


def _custom_openapi() -> dict:
    """스펙에만 서비스 토큰 인증 스킴을 노출 — 런타임 인증 경로는 그대로 둔다.

    Swagger UI의 Authorize 버튼을 켜기 위한 문서용 오버라이드. 실제 인증은 여전히
    AuthMiddleware가 담당하므로(PUBLIC_PATHS 면제 경로 포함) 여기서는 요청을 막지 않는다.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
    schema["components"]["securitySchemes"] = {"ServiceToken": {"type": "http", "scheme": "bearer"}}
    schema["security"] = [{"ServiceToken": []}]
    for path, methods in schema["paths"].items():
        if path in PUBLIC_PATHS:
            for operation in methods.values():
                operation["security"] = []
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


@app.get("/ui", include_in_schema=False)
async def dashboard():
    """내부 검증 대시보드 — 팀이 파이프라인 동작을 직접 눌러 확인하는 개발용 페이지.

    별도 서버·포트 없이 llm-api가 그대로 서빙한다. 페이지 자체는 인증 없이 열리고,
    페이지 안의 API 호출(fetch)이 서비스 토큰을 실어 보낸다(AuthMiddleware 그대로 적용).
    """
    return FileResponse(STATIC_DIR / "dashboard.html")


# MCP 서버 — 읽기 툴 4종 (§5.2). MCP Inspector: http://localhost:8000/mcp
app.mount("/mcp", mcp_app)
