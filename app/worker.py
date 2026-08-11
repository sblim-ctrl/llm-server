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
from app.db.pool import (
    apply_schema_locked,
    close_pool,
    finish_job,
    get_pool,
    open_pool,
    setup_checkpointer_locked,
)
from app.graphs.indexing.graph import indexing_graph
from app.graphs.review.graph import build_review_graph
from app.graphs.review.nodes.callback import trace_meta
from app.observability import langsmith_config, setup_langsmith
from app.graphs.writers.briefing import briefing_graph

from app.graphs.writers.budget_planner import budget_planner_graph
from app.graphs.writers.digest import digest_graph
from app.graphs.writers.report import report_graph
from app.graphs.writers.rule_amendment import rule_amendment_graph
from app.schemas.analyze import AnalyzeRequest, ContextRefreshRequest
from app.schemas.callback import CallbackPayload
from app.schemas.common import Reasons
from app.schemas.proposals import (
    ProposalBudgetRequest,
    RuleAmendmentRequest,
)
from app.schemas.writers import BriefingRequest, DigestRequest, ReportRequest
from app.tools.backend_client import close_backend_client, send_callback
from app.tools.document_parser import DocumentParseError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")

_shutdown = asyncio.Event()
_review_graph = None  # main()에서 checkpointer와 함께 컴파일됨
_checkpointer = None  # B-7: 재시도 시 체크포인트 존재 확인용 (main()에서 주입)

# params 변경은 RAG 인덱스 대상이 아님 — 팀 정책 파라미터는 load_context가 백엔드에서 직접 조회 (§4.2)
INDEXABLE_CHANGE_TYPES = {"rule", "category"}


async def run_context_refresh_job(job: dict[str, Any]) -> tuple[dict[str, Any], None]:
    req = ContextRefreshRequest.model_validate(job["payload"])
    if req.change_type not in INDEXABLE_CHANGE_TYPES:
        return {
            "status": "skipped",
            "reason": f"non-indexable change_type: {req.change_type}",
        }, None

    final_state = await indexing_graph.ainvoke(
        {
            "team_id": req.team_id,
            "doc_type": req.change_type,
        }
    )
    # 인덱싱 그래프는 llm_meta가 없음 — 계측 대상 아님 → final_state 대신 None
    return {
        "status": "indexed",
        "chunks_indexed": final_state.get("chunks_indexed", 0),
        "version": final_state.get("version"),
    }, None


async def run_review_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(잡 결과, 그래프 final_state) 반환 — final_state는 llm_meta 합산(B-7)용."""
    req = AnalyzeRequest.model_validate(job["payload"])
    job_id = str(job["id"])
    # thread_id=job_id → 잡 1건 = 체크포인트 스레드 1개 (§4.2)
    # run_name/tags → LangSmith 트레이스 식별 (B3, C9 형식)
    config = langsmith_config("review", job_id, req.organization_id, thread_id=job_id)

    # pull 모델(§0-2) — 지출 상세는 여기 없다, load_context가 백엔드에 되물어 채운다.
    # 최초 시도와 B-7 무체크포인트 재시도 방어가 같은 초기 상태를 쓴다.
    initial_state = {
        "job_id": job_id,  # 내부 id — thread_id·체크포인트 키
        "external_job_id": req.job_id,  # 백엔드 발급 jobId — 콜백 echo용
        "expense_id": req.expense_id,
        "team_id": req.organization_id,
        "review_goal": req.review_goal,
        "receipt_path": req.receipt_path,
    }
    if job["attempts"] <= 1:
        # 최초 시도 — START부터 실행
        final_state = await _review_graph.ainvoke(initial_state, config=config)
    else:
        # 재시도 — 체크포인트가 있으면 마지막 완료 노드 이후부터 재개(input=None).
        # B-7 방어: 첫 체크포인트 기록 전에 크래시했으면 aget이 None — 이때 None을
        # 넣으면 빈 상태로 실행되므로 payload에서 initial_state를 재구성해 START부터.
        ckpt = await _checkpointer.aget(config) if _checkpointer else None
        final_state = await _review_graph.ainvoke(None if ckpt else initial_state, config=config)

    reasons = final_state.get("reasons")
    meta = trace_meta(final_state)
    result = {
        "verdict": final_state.get("verdict"),
        "confidence": final_state.get("confidence"),
        "reasons": reasons.model_dump() if reasons else None,
        "callback_status": final_state.get("callback_status"),
        # classify_category가 채운 최종 카테고리 — UI에서 분류 결과 확인용
        "category": final_state["claim"].category,
        "category_source": final_state.get("category_source"),
        # 아래는 콜백 정제(화면_대조_2026-08-03.md) 대비 관측 보관처. 지금까지 심사관
        # 소견·불일치·모델 버전은 콜백 페이로드에만 있었고 우리 쪽엔 남지 않았다 —
        # 콜백에서 덜어내도 GET /v1/jobs/{id}로 되짚을 수 있어야 한다.
        "opinions": [o.model_dump() for o in final_state.get("opinions", {}).values()],
        "mismatch": [m.model_dump() for m in final_state.get("mismatch", [])],
        "model_version": meta["model_version"],
        "prompt_version": meta["prompt_version"],
        "latency_ms": meta["latency_ms"],
        # jobs.cost_usd 컬럼에도 기록되지만(B-7) JobStatusResponse가 그 컬럼을 노출하지
        # 않는다 — 콜백에서 뺀 이상 여기 없으면 API로는 조회할 방법이 사라진다.
        "cost_usd": meta["cost_usd"],
    }
    return result, final_state


async def run_report_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """P1-1 — ReportWriter가 이제 실LLM을 호출하므로 C9 태깅."""
    req = ReportRequest.model_validate(job["payload"])
    final = await report_graph.ainvoke(
        {"request": req},
        config=langsmith_config("report", str(job["id"]), req.team_id),
    )
    return final["report"].model_dump(mode="json"), final


async def run_briefing_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """P1-2 — BriefingWriter가 이제 실LLM을 호출하므로 C9 태깅."""
    req = BriefingRequest.model_validate(job["payload"])
    final = await briefing_graph.ainvoke(
        {"request": req},
        config=langsmith_config("briefing", str(job["id"]), req.team_id),
    )
    return final["briefing"].model_dump(mode="json"), final


async def run_digest_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A-4 — AI 총무 주간 브리핑. C9 태깅: run_name=digest:{job_id}·tags=[team_id]."""
    req = DigestRequest.model_validate(job["payload"])
    final = await digest_graph.ainvoke(
        {"request": req},
        config=langsmith_config("digest", str(job["id"]), req.team_id),
    )
    return final["digest"].model_dump(mode="json"), final


async def run_proposal_budget_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """B-3 — 예산관리 페이지 AI 메시지 3블록 (LLM-016). C9 태깅."""
    req = ProposalBudgetRequest.model_validate(job["payload"])
    final = await budget_planner_graph.ainvoke(
        {"request": req},
        config=langsmith_config("proposal_budget", str(job["id"]), req.team_id),
    )
    return {"proposal_id": final.get("proposal_id"), "payload": final.get("payload")}, final


async def run_proposal_rule_amendment_job(
    job: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """B-6 — 회칙 개정 제안 (작성: 개발자 B, 레지스트리 이식은 병합 시 A). C9 태깅."""
    req = RuleAmendmentRequest.model_validate(job["payload"])
    final = await rule_amendment_graph.ainvoke(
        {"request": req},
        config=langsmith_config("proposal_rule_amendment", str(job["id"]), req.team_id),
    )
    return {
        "proposals": final.get("proposal_ids") or [],
        "reason": final.get("reason"),
        # verify_amendment가 검증 실패를 세팅해도 save는 {"proposal_ids": []}만
        # 조용히 반환한다 — jobs.result만 보는 호출자가 "군집 없음"(정상)과
        # "군집은 있었는데 LLM 초안이 검증 실패"(실패, 종전엔 여기서 삼켜짐)를
        # 구분하도록 결과에 그대로 노출한다.
        "verified": final.get("verified"),
        "verify_error": final.get("verify_error"),
    }, final


# 잡 타입 → 핸들러 레지스트리 (C6 계약, A-2) — 7종 전부 등록.
# 핸들러 계약(팀 합의 7/20): async (job: dict) -> (result dict, final_state | None)
# — final_state는 B-7 잡 비용 계측(_meta_totals)이 llm_meta 합산에 사용, 그래프
# 상태가 없거나 계측 무의미하면 None. C9 태깅은 각 핸들러 내부에서.
JOB_HANDLERS: dict[str, Any] = {
    "review": run_review_job,
    "context_refresh": run_context_refresh_job,
    "report": run_report_job,
    "briefing": run_briefing_job,
    "digest": run_digest_job,
    "proposal_budget": run_proposal_budget_job,
    "proposal_rule_amendment": run_proposal_rule_amendment_job,
}


def _meta_totals(final_state: dict[str, Any] | None) -> tuple[float, int, int]:
    """그래프 final_state의 llm_meta(dict[str, LLMCallMeta]) 합산 — B-7 잡 비용 계측.

    llm_meta를 싣지 않는 그래프(context_refresh)는 0.
    콜백 payload 합산(callback.py)과 같은 패턴이지만 기록 대상이 jobs 테이블이라
    파일이 다르다 (A-5와 무충돌).
    """
    metas = list(((final_state or {}).get("llm_meta") or {}).values())
    return (
        round(sum(m.cost_usd for m in metas), 6),
        sum(m.tokens_in for m in metas),
        sum(m.tokens_out for m in metas),
    )


async def _send_review_failsafe(job: dict[str, Any]) -> None:
    """review 잡이 dead로 전환됐을 때 ESCALATED fail-safe 콜백 발송 (§8).

    합집합 (7/20 팀 합의 ②):
    · review 잡 한정 (B-7 — 비-review 잡의 지출 에스컬레이션 오발송 방지)
    · 정식 CallbackPayload camelCase + 백엔드 발급 jobId echo (A-5 —
      snake_case·내부 id면 expenses.ai_job_id 대조에서 무시된다)

    handle_job()의 재시도 소진 경로와 poll_loop()의 reclaim_stale_jobs 하드 크래시
    경로 양쪽에서 재사용한다 — job dict는 job_id(또는 id)·external_job_id·
    expense_id·team_id를 가진다고 가정.
    """
    job_id = str(job.get("job_id") or job.get("id"))
    expense_id = job.get("expense_id")
    if not expense_id:
        # expense_id 없이 CallbackPayload를 만들면 app/schemas/ids.py의 strict
        # BigIntId(conint(strict=True, gt=0)) 때문에 ValidationError가 난다 —
        # 콜백을 건너뛰고 조용히 삼키지 않도록 critical로 남긴다.
        logger.critical(
            "job %s review 잡이 dead로 전환됐지만 expense_id가 없어 fail-safe 콜백을 건너뜁니다",
            job_id,
        )
        return
    fail_safe = CallbackPayload(
        job_id=job.get("external_job_id") or job_id,
        expense_id=expense_id,
        team_id=job["team_id"],
        verdict="escalate",
        reasons=Reasons(
            requester="심사 지연으로 관리자 확인이 필요합니다.",
            admin="AI 분석이 반복 실패하여 안전 정책에 따라 관리자 확인으로 전환 (재시도 소진)",
        ),
    )
    await send_callback(fail_safe.model_dump(mode="json", by_alias=True))


async def handle_job(job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    logger.info("job %s start (type=%s attempt=%s)", job_id, job["type"], job["attempts"])
    final_state: dict[str, Any] | None = None  # llm_meta 합산용 (B-7)
    try:
        handler = JOB_HANDLERS.get(job["type"])
        if handler is None:
            result: dict[str, Any] = {"status": "unknown_job_type"}
        else:
            result, final_state = await handler(job)
        cost_usd, tokens_in, tokens_out = _meta_totals(final_state)  # B-7 잡 비용 계측
        await finish_job(
            job_id,
            "succeeded",
            result,
            cost_usd=cost_usd,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        logger.info("job %s succeeded: %s", job_id, result.get("verdict"))
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        if job["attempts"] >= job["max_attempts"]:
            # **실패 사유를 jobs.result에 남긴다** (2026-08-06). 종전에는 status만
            # 'dead'로 적어서 `GET /v1/jobs/{id}`가 `result: null`을 돌려줬다 — 백엔드는
            # "실패했다"만 알고 왜인지 알 방법이 없었고, 사유는 서버 로그에만 있었다.
            #
            # 회칙 파일 파싱(T2)에서 이 구멍이 드러났다. "스캔한 이미지 PDF는 글자를
            # 인식할 수 없으니 텍스트가 든 파일로 다시 올려 주세요" 같은 안내를 만들어
            # 놓고도 관리자에게 닿을 경로가 없었다. 관리자는 회칙을 올렸는데 심사에
            # 반영이 안 된 이유를 영영 모른다 — 이 프로젝트가 반복해 겪은 '조용한 실패'다.
            #
            # 메시지는 관리자에게 그대로 보여도 되는 수준으로 쓰여 있다(document_parser).
            # 내부 스택은 넣지 않는다 — 화면에 나가도 안전해야 하고 상세는 로그에 있다.
            #
            # 그 "안전하다" 보장은 DocumentParseError 계열에만 성립한다(그 클래스의
            # 계약이다) — 다른 예외의 str()은 안전을 보장하지 않는다. 예: run_review_job의
            # AnalyzeRequest.model_validate 실패 시 pydantic ValidationError가 지출 제목
            # 원문을 담고(2026-08-06 CI 로그로 실측), httpx 오류는 내부 백엔드 URL을 담는다.
            # 이 result는 명세상 관리자 화면에 그대로 나갈 수 있는 자리라 무차별로 흘리면
            # 안 된다.
            message = (
                str(exc)
                if isinstance(exc, DocumentParseError)
                else "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
            )
            await finish_job(
                job_id,
                "dead",
                result={"error": type(exc).__name__, "message": message},
            )
            # fail-safe: 재시도 소진 → ESCALATED 콜백 (§8, 헬퍼 계약은 _send_review_failsafe 참고)
            if job["type"] == "review":
                await _send_review_failsafe(job)
        else:
            # 재큐잉 — claim_next_job의 attempts 증가와 함께 재시도
            async with get_pool().connection() as conn:
                await conn.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = now() WHERE id = %s",
                    (job_id,),
                )


async def poll_loop() -> None:
    from app.db.pool import claim_next_job, reclaim_stale_jobs

    settings = get_settings()
    interval = settings.worker_poll_interval_sec
    logger.info("worker started (poll every %.1fs)", interval)
    while not _shutdown.is_set():
        # B-7 고아 잡 회수 — 크래시로 running에 갇힌 잡을 visibility timeout 후
        # 재큐잉하거나(attempts 소진 시) dead 처리. dead+review는 여기서도
        # handle_job()의 except 블록과 동일하게 fail-safe 콜백을 보내야 한다 —
        # 하드 크래시(OOM kill 등)는 그 except 블록을 거치지 않기 때문.
        reclaimed = await reclaim_stale_jobs(settings.worker_visibility_timeout_sec)
        if reclaimed:
            logger.warning(
                "고아 잡 %d건 회수: %s",
                len(reclaimed),
                [(r["id"], r["status"]) for r in reclaimed],
            )
            for row in reclaimed:
                if row.get("status") == "dead" and row.get("type") == "review":
                    await _send_review_failsafe(row)
        job = await claim_next_job()
        if job is None:
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=interval)
            except TimeoutError:
                pass
            continue
        try:
            await handle_job(job)
        except Exception:
            # handle_job 자체가 (finish_job 오류 등으로) 예외를 던지면 poll_loop
            # 전체가 죽어 main()까지 전파되고 워커 프로세스가 죽는다 — 잡 하나의
            # 실패가 큐 전체를 멈추지 않도록 여기서 막고 다음 사이클로 넘어간다.
            logger.critical("handle_job 자체가 실패 — 잡 %s, 루프는 계속", job["id"], exc_info=True)
    logger.info("worker stopped")


async def main() -> None:
    global _review_graph, _checkpointer
    setup_langsmith()  # B3 — 켜져 있으면 LANGCHAIN_* env 주입 (그래프 자동 트레이싱)
    await open_pool()
    await apply_schema_locked()  # API(--workers 2)와 동시에 기동해도 안전 (pool.py 참고)

    async with AsyncPostgresSaver.from_conn_string(get_settings().database_url) as checkpointer:
        await setup_checkpointer_locked(checkpointer)  # 동시 기동 안전 (pool.py 참고)
        _checkpointer = checkpointer  # B-7: run_review_job의 체크포인트 존재 확인용
        _review_graph = build_review_graph(checkpointer=checkpointer)
        try:
            await poll_loop()
        finally:
            await close_backend_client()  # 공유 httpx 클라이언트 정리
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
