"""실시간 심사 스트리밍 (SSE) + HITL 사람 개입 — 데모·관측 전용.

강의 04-07(Streaming-Steps)·06-02(Human-In-The-Loop)·04-04(Durable Execution) 적용.

워커 큐를 거치지 않고 API 프로세스가 심사 그래프를 직접 `astream`으로 실행하며,
노드가 하나 끝날 때마다 SSE 이벤트를 브라우저에 흘려보낸다. policy-draft와 같은
'동기 실행 예외'(§2.2)의 관측 버전 — 정식 심사 경로(POST /v1/analyze → 워커 큐)는
그대로가 진실이고, 이 엔드포인트는 대시보드 데모·관측용이다.

HITL: 이 경로는 hitl_enabled=True로 실행돼 escalate 노드에서 interrupt()로
**그래프가 멈춘다**(SSE `paused` 이벤트 후 스트림 종료). 관리자가
POST /v1/reviews/{job_id}/decision 으로 승인/반려를 보내면 **같은 체크포인트에서
재개**돼 콜백·판례 저장(decided_by='ADMIN')까지 이어간다 — 관리자 결정이 판례로
학습되는 루프(REQ-042)의 사람 축.

체크포인터는 워커와 같은 Postgres(AsyncPostgresSaver) — lifespan(main.py)이 수명을
관리하고 기동 시 init_hitl_graph()로 주입한다. 종전 MemorySaver(프로세스 메모리)는
`--workers 2`에서 멈춤과 재개가 서로 다른 프로세스에 떨어지면 409가 났고, 서버
재시작 시 대기 중 심사가 소멸했다 — Postgres 전환으로 둘 다 해소(2026-08-07 팀장
합의). 그래프 부수 효과(콜백·판례 저장)는 워커 경로와 동일하게 일어난다(목
백엔드에선 무해).

인증: AuthMiddleware 그대로 적용 — 클라이언트는 EventSource 대신 fetch 스트리밍
읽기를 써서 Authorization 헤더를 싣는다 (미들웨어 면제 경로 추가 없음).

SSE 이벤트: start(노드 목록) → node(완료 노드·소요ms·심사관 소견)*
            → paused(관리자 결정 대기) | result(판정·신뢰도·사유) | error
"""
import contextlib
import json
import logging
import uuid
from time import perf_counter
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.types import Command
from psycopg import AsyncConnection
from pydantic import BaseModel

from app.config import get_settings
from app.graphs.review.graph import build_review_graph
from app.observability import langsmith_config
from app.schemas.analyze import AnalyzeRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# HITL 데모 전용 그래프 — interrupt 재개에 체크포인터가 필수라 별도 컴파일.
# (워커의 review_graph와 노드는 동일, 체크포인터 인스턴스만 별도)
# lifespan(main.py)이 AsyncPostgresSaver를 열어 init_hitl_graph()로 채운다 —
# 체크포인터 연결의 수명이 앱과 같아야 해서 import 시점에 만들 수 없다.
hitl_graph = None


def init_hitl_graph(checkpointer) -> None:
    """기동 시 1회 — 워커와 같은 Postgres 체크포인터로 HITL 그래프를 컴파일."""
    global hitl_graph
    hitl_graph = build_review_graph(checkpointer=checkpointer)

# 그래프 노드 → 화면 표시명 (심사 그래프 13노드, graph.py 배선 순서 기준 —
# 나열 순서가 화면 단계 목록 순서다. 배선과 어긋나면 test_reviews_stream의
# 위상 순서 테스트가 잡는다. 2026-08-06 순서 변경(영수증 판독 → 분류) 반영.)
NODE_LABELS = {
    "load_context": "컨텍스트 로드",
    "intake_receipt": "영수증 판독",
    "classify_category": "카테고리 분류",
    "mismatch_gate": "증빙 심사관",
    "rule_auditor": "회칙 심사관",
    "budget_auditor": "예산 심사관",
    "precedent_auditor": "판례 심사관",
    "guardrail_gate": "가드레일 (코드 검증)",
    "adjudicate": "최종 판정",
    "escalate": "관리자 검토로 보류",
    "execute_decision": "결정 실행",
    "callback": "백엔드 콜백",
    "persist_precedent": "판례 저장",
}
# mismatch_gate도 증빙 심사관 소견을 내므로 스트림에 소견을 함께 실어 보낸다
# (풀스택 협의 2026-08-04 — 지출 상세 'AI 심사결과'의 네 번째 심사관).
AUDITOR_NODES = {"rule_auditor", "budget_auditor", "precedent_auditor", "mismatch_gate"}


class DecisionRequest(BaseModel):
    """관리자 결정 — HITL 재개 입력."""
    decision: Literal["approve", "reject"]
    reason: str = ""


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_run(stream, job_id: str, started: float):
    """그래프 updates 스트림 → SSE 이벤트 제너레이터 (최초 실행·재개 공용).

    interrupt를 만나면 paused를 내고 끝낸다. 정상 종료면 체크포인트 상태에서
    최종 결과를 조립해 result를 낸다 (재개 요청은 이전 스트림의 지역 변수를
    갖고 있지 않으므로 상태 스냅샷이 유일한 진실).
    """
    last = started
    paused = False
    async for chunk in stream:
        now = perf_counter()
        for node, upd in chunk.items():
            if node == "__interrupt__":
                intr = upd[0] if isinstance(upd, (list, tuple)) and upd else upd
                value = getattr(intr, "value", {}) or {}
                yield _sse("paused", {"jobId": job_id, **value})
                paused = True
                continue
            payload = {"node": node,
                       "label": NODE_LABELS.get(node, node),
                       "ms": int((now - last) * 1000)}
            if isinstance(upd, dict) and node in AUDITOR_NODES:
                ops = upd.get("opinions") or {}
                if ops:
                    op = next(iter(ops.values()))
                    payload["opinion"] = {"verdict": op.verdict, "summary": op.summary}
            yield _sse("node", payload)
        last = now
    if paused:
        return

    snap = await hitl_graph.aget_state(
        {"configurable": {"thread_id": job_id}})
    v = snap.values
    reasons, gate, claim = v.get("reasons"), v.get("gate_result"), v.get("claim")
    yield _sse("result", {
        "category": claim.category if claim else None,
        "categorySource": v.get("category_source"),
        "verdict": v.get("verdict") or "escalate",
        "confidence": v.get("confidence"),
        "adminDecision": v.get("admin_decision"),
        "reasons": reasons.model_dump() if reasons else None,
        "gateRules": list(gate.triggered_rules) if gate else [],
        "opinions": {k: {"verdict": o.verdict, "summary": o.summary}
                     for k, o in (v.get("opinions") or {}).items()},
        "totalMs": int((perf_counter() - started) * 1000),
    })


@router.post("/v1/reviews/stream")
async def stream_review(req: AnalyzeRequest) -> StreamingResponse:
    """심사 그래프를 직접 실행하며 노드 진행을 SSE로 중계 (HITL 데모·관측 전용)."""

    async def gen():
        job_id = f"demo-stream-{uuid.uuid4().hex[:8]}"
        initial_state = {  # worker.run_review_job의 초기 상태 + HITL 플래그
            "job_id": job_id,
            "external_job_id": req.job_id,
            "expense_id": req.expense_id,
            "team_id": req.organization_id,
            "review_goal": req.review_goal,
            "receipt_path": req.receipt_path,
            "hitl_enabled": True,
        }
        config = langsmith_config("review-stream", job_id, req.organization_id,
                                  thread_id=job_id)
        yield _sse("start", {"jobId": job_id,
                             "nodes": [{"id": n, "label": lb}
                                       for n, lb in NODE_LABELS.items()]})
        started = perf_counter()
        try:
            stream = hitl_graph.astream(initial_state, config=config,
                                        stream_mode="updates")
            async for evt in _stream_run(stream, job_id, started):
                yield evt
        except Exception:
            # fail-safe: 데모 스트림의 실패는 이벤트로 알리고 종료 (§8 — 심사 확정 아님)
            logger.exception("review stream failed")
            yield _sse("error", {"detail": "심사 실행 실패 — 서버 로그 확인"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# HITL 재개 advisory lock 네임스페이스 — (hashtext(NS), hashtext(job_id)) 쌍.
# pool.py의 setup 잠금(hashtext('checkpointer_setup'), 0)과 축이 달라 안 겹친다.
RESUME_LOCK_NS = "hitl_resume"


async def _release_resume_lock(conn, job_id: str) -> None:
    """재개 잠금 해제 — 어떤 예외도 밖으로 흘리지 않는다.

    연결이 닫히면 세션 잠금은 함께 풀리므로 unlock 실패는 치명적이지 않다.
    여기서 예외를 흘리면 409 응답이 500으로 바뀌거나(종결 재확인 경로) 스트림
    제너레이터 정리가 오류로 끝난다(gen finally 경로).
    """
    try:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
            (RESUME_LOCK_NS, job_id))
    except Exception:
        logger.warning("HITL 재개 잠금 해제 실패 — 연결 종료로 대체: %s",
                       job_id, exc_info=True)
    finally:
        with contextlib.suppress(Exception):
            await conn.close()


@router.post("/v1/reviews/{job_id}/decision")
async def resume_review(job_id: str, req: DecisionRequest):
    """관리자 결정으로 멈춘 심사를 재개 — 콜백·판례 저장(ADMIN)까지 SSE 중계.

    확인("대기 중인가")과 실행(그래프 재개) 사이를 job_id 단위 advisory lock으로
    잠근다(2026-08-09 리뷰). 잠금이 없으면 같은 잡에 승인이 동시에 오는 경우
    (버튼 두 번·클라이언트 재시도) 둘 다 확인을 통과해 콜백·판례 저장이 2번
    일어난다 — 재현: 동시 2발 모두 200, ADMIN 판례 2행. MemorySaver 시절엔 다른
    프로세스가 스레드 상태를 못 봐 우연히 409로 막혀 있던 동작이다. 세션 수준
    잠금이라 재개 중 프로세스가 죽어도 연결이 닫히며 함께 풀린다.
    """
    config = {"configurable": {"thread_id": job_id}}
    lock_conn = await AsyncConnection.connect(
        get_settings().database_url, autocommit=True)
    try:
        got = (await (await lock_conn.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s), hashtext(%s))",
            (RESUME_LOCK_NS, job_id))).fetchone())[0]
        if not got:  # 같은 잡을 다른 요청이 재개하는 중 — 기다리지 않고 거절
            with contextlib.suppress(Exception):
                await lock_conn.close()
            return JSONResponse(status_code=409, content={
                "detail": f"'{job_id}'는 이미 다른 요청이 재개 중입니다 — "
                          "잠시 후 심사 상태를 확인하세요"})
        # 잠금 안에서 상태 확인 — 직전 재개가 방금 종결한 잡도 여기서 걸린다
        snap = await hitl_graph.aget_state(config)
        if not snap.next:  # 대기 중인 interrupt가 없음 — 모르는 잡이거나 이미 종결
            await _release_resume_lock(lock_conn, job_id)
            return JSONResponse(status_code=409, content={
                "detail": f"'{job_id}'는 관리자 결정 대기 상태가 아닙니다 "
                          "(이미 종결됐거나 알 수 없는 잡)"})
    except Exception:
        with contextlib.suppress(Exception):  # close 실패가 원인 예외를 가리지 않게
            await lock_conn.close()
        raise

    async def gen():
        try:
            team_id = snap.values.get("team_id") or "unknown"
            cfg = langsmith_config("review-resume", job_id, team_id,
                                   thread_id=job_id)
            started = perf_counter()
            stream = hitl_graph.astream(
                Command(resume={"decision": req.decision, "reason": req.reason}),
                config=cfg, stream_mode="updates")
            async for evt in _stream_run(stream, job_id, started):
                yield evt
        except Exception:
            logger.exception("review resume failed")
            yield _sse("error", {"detail": "재개 실패 — 서버 로그 확인"})
        finally:
            await _release_resume_lock(lock_conn, job_id)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
