"""llm-worker — 잡 폴링 → LangGraph 실행 → 결과 기록 (§2.2, ADR-4).

실행: python -m app.worker
실패 시 max_attempts까지 자동 재시도(잡 재큐잉), 소진 시 dead 처리 후
fail-safe 에스컬레이션 콜백을 보낸다 — 어떤 실패도 자동 승인으로 이어지지 않는다 (§8).
"""
import asyncio
import logging
import signal
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings
from app.db.pool import apply_schema, close_pool, finish_job, get_pool, open_pool
from app.graphs.indexing.graph import indexing_graph
from app.graphs.review.graph import build_review_graph
from app.graphs.writers.briefing import briefing_graph
from app.graphs.writers.report import report_graph
from app.schemas.analyze import AnalyzeRequest, ContextRefreshRequest
from app.schemas.writers import BriefingRequest, ReportRequest
from app.tools.backend_client import send_callback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")

_shutdown = asyncio.Event()
_review_graph = None  # main()에서 checkpointer와 함께 컴파일됨

# params 변경은 RAG 인덱스 대상이 아님 — 팀 정책 파라미터는 load_context가 백엔드에서 직접 조회 (§4.2)
INDEXABLE_CHANGE_TYPES = {"rule", "category"}


async def run_context_refresh_job(job: dict[str, Any]) -> dict[str, Any]:
    req = ContextRefreshRequest.model_validate(job["payload"])
    if req.change_type not in INDEXABLE_CHANGE_TYPES:
        return {"status": "skipped", "reason": f"non-indexable change_type: {req.change_type}"}

    final_state = await indexing_graph.ainvoke({
        "team_id": req.team_id,
        "doc_type": req.change_type,
        "version": req.version,
    })
    return {"status": "indexed", "chunks_indexed": final_state.get("chunks_indexed", 0)}


async def run_review_job(job: dict[str, Any]) -> dict[str, Any]:
    req = AnalyzeRequest.model_validate(job["payload"])
    job_id = str(job["id"])
    # thread_id=job_id → 잡 1건 = 체크포인트 스레드 1개 (§4.2)
    config = {"configurable": {"thread_id": job_id}}

    if job["attempts"] <= 1:
        # 최초 시도 — START부터 실행
        initial_state = {
            "job_id": job_id,
            "expense_id": req.expense_id,
            "team_id": req.team_id,
            "claim": req.claim,
            "receipt_url": req.receipt_signed_url,
            "receipt_text": req.receipt_text,
        }
        final_state = await _review_graph.ainvoke(initial_state, config=config)
    else:
        # 재시도 — 마지막 체크포인트 이후 노드부터 재개 (완료 노드 재실행 없음)
        final_state = await _review_graph.ainvoke(None, config=config)

    reasons = final_state.get("reasons")
    return {
        "verdict": final_state.get("verdict"),
        "confidence": final_state.get("confidence"),
        "reasons": reasons.model_dump() if reasons else None,
        "callback_status": final_state.get("callback_status"),
    }


async def handle_job(job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    logger.info("job %s start (type=%s attempt=%s)", job_id, job["type"], job["attempts"])
    try:
        if job["type"] == "review":
            result = await run_review_job(job)
        elif job["type"] == "context_refresh":
            result = await run_context_refresh_job(job)
        elif job["type"] == "report":
            req = ReportRequest.model_validate(job["payload"])
            final = await report_graph.ainvoke({"request": req})
            result = final["report"].model_dump(mode="json")
        elif job["type"] == "briefing":
            req = BriefingRequest.model_validate(job["payload"])
            final = await briefing_graph.ainvoke({"request": req})
            result = final["briefing"].model_dump(mode="json")
        else:
            result = {"status": "unknown_job_type"}
        await finish_job(job_id, "succeeded", result)
        logger.info("job %s succeeded: %s", job_id, result.get("verdict"))
    except Exception:
        logger.exception("job %s failed", job_id)
        if job["attempts"] >= job["max_attempts"]:
            await finish_job(job_id, "dead")
            # fail-safe: 재시도 소진 → ESCALATED 콜백 (§8)
            await send_callback({
                "job_id": job_id,
                "expense_id": job.get("expense_id"),
                "team_id": job["team_id"],
                "verdict": "escalate",
                "reasons": {"requester": "심사 지연으로 관리자 확인이 필요합니다.",
                            "admin": "AI 분석 실패 (재시도 소진) — fail-safe 에스컬레이션"},
            })
        else:
            # 재큐잉 — claim_next_job의 attempts 증가와 함께 재시도
            async with get_pool().connection() as conn:
                await conn.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = now() WHERE id = %s",
                    (job_id,),
                )


async def poll_loop() -> None:
    from app.db.pool import claim_next_job
    interval = get_settings().worker_poll_interval_sec
    logger.info("worker started (poll every %.1fs)", interval)
    while not _shutdown.is_set():
        job = await claim_next_job()
        if job is None:
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=interval)
            except TimeoutError:
                pass
            continue
        await handle_job(job)
    logger.info("worker stopped")


async def main() -> None:
    global _review_graph
    await open_pool()
    await apply_schema()

    async with AsyncPostgresSaver.from_conn_string(get_settings().database_url) as checkpointer:
        await checkpointer.setup()  # idempotent — checkpoint 테이블 마이그레이션
        _review_graph = build_review_graph(checkpointer=checkpointer)
        try:
            await poll_loop()
        finally:
            await close_pool()


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        # psycopg 비동기는 ProactorEventLoop 비호환 — Selector로 교체
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        loop = asyncio.new_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown.set)
            except NotImplementedError:
                pass  # Windows — KeyboardInterrupt로 대체
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
