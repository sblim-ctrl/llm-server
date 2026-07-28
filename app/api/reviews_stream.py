"""실시간 심사 스트리밍 (SSE) — 데모·관측 전용 (강의 04-07 Streaming-Steps).

워커 큐를 거치지 않고 API 프로세스가 심사 그래프를 직접 `astream`으로 실행하며,
노드가 하나 끝날 때마다 SSE 이벤트를 브라우저에 흘려보낸다. policy-draft와 같은
'동기 실행 예외'(§2.2)의 관측 버전 — 정식 심사 경로(POST /v1/analyze → 워커 큐)는
그대로가 진실이고, 이 엔드포인트는 대시보드 데모·관측용이다.

그래프 자체는 워커와 동일하므로 콜백·판례 저장 등 부수 효과도 동일하게 일어난다
(목 백엔드에선 무해 — 기존 데모 흐름과 같은 효과). 체크포인터 없는 컴파일이라
중단 시 재개는 없다(데모 특성상 허용).

인증: AuthMiddleware 그대로 적용 — 클라이언트는 EventSource 대신 fetch 스트리밍
읽기를 써서 Authorization 헤더를 싣는다 (미들웨어 면제 경로 추가 없음).

SSE 이벤트: start(노드 목록) → node(완료된 노드·소요ms·심사관 소견 요약)*
            → result(판정·신뢰도·사유·가드레일) | error(실패 — fail-safe)
"""
import json
import logging
import uuid
from time import perf_counter

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.graphs.review.graph import review_graph
from app.observability import langsmith_config
from app.schemas.analyze import AnalyzeRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# 그래프 노드 → 화면 표시명 (심사 그래프 13노드, graph.py 배선 순서 기준)
NODE_LABELS = {
    "load_context": "컨텍스트 로드",
    "classify_category": "카테고리 분류",
    "intake_receipt": "영수증 판독",
    "mismatch_gate": "영수증-청구 일치 검증",
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
AUDITOR_NODES = {"rule_auditor", "budget_auditor", "precedent_auditor"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/v1/reviews/stream")
async def stream_review(req: AnalyzeRequest) -> StreamingResponse:
    """심사 그래프를 직접 실행하며 노드 진행을 SSE로 중계 (데모·관측 전용)."""

    async def gen():
        job_id = f"demo-stream-{uuid.uuid4().hex[:8]}"
        initial_state = {  # worker.run_review_job의 초기 상태와 동일 구성
            "job_id": job_id,
            "external_job_id": req.job_id,
            "expense_id": req.expense_id,
            "team_id": req.organization_id,
            "review_goal": req.review_goal,
            "receipt_path": req.receipt_path,
        }
        config = langsmith_config("review-stream", job_id, req.organization_id)

        yield _sse("start", {"jobId": job_id,
                             "nodes": [{"id": n, "label": lb} for n, lb in NODE_LABELS.items()]})

        merged: dict = {}
        opinions: dict = {}
        started = last = perf_counter()
        try:
            async for chunk in review_graph.astream(initial_state, config=config,
                                                    stream_mode="updates"):
                now = perf_counter()
                for node, upd in chunk.items():
                    payload = {"node": node,
                               "label": NODE_LABELS.get(node, node),
                               "ms": int((now - last) * 1000)}
                    if isinstance(upd, dict):
                        # opinions는 reducer 병합 키 — 통째로 덮지 말고 누적
                        ops = upd.get("opinions") or {}
                        opinions.update(ops)
                        merged.update({k: v for k, v in upd.items() if k != "opinions"})
                        if node in AUDITOR_NODES and ops:
                            op = next(iter(ops.values()))
                            payload["opinion"] = {"verdict": op.verdict, "summary": op.summary}
                    yield _sse("node", payload)
                last = now
        except Exception:
            # fail-safe: 데모 스트림의 실패는 이벤트로 알리고 종료 (§8 — 심사 확정 아님)
            logger.exception("review stream failed")
            yield _sse("error", {"detail": "심사 실행 실패 — 서버 로그 확인"})
            return

        reasons = merged.get("reasons")
        gate = merged.get("gate_result")
        claim = merged.get("claim")
        yield _sse("result", {
            "category": claim.category if claim else None,
            "categorySource": merged.get("category_source"),
            "verdict": merged.get("verdict") or "escalate",
            "confidence": merged.get("confidence"),
            "reasons": reasons.model_dump() if reasons else None,
            "gateRules": list(gate.triggered_rules) if gate else [],
            "opinions": {k: {"verdict": o.verdict, "summary": o.summary}
                         for k, o in opinions.items()},
            "totalMs": int((perf_counter() - started) * 1000),
        })

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
