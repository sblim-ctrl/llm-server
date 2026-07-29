"""callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)."""
import time

from app.graphs.review.state import ReviewState
from app.schemas.callback import CallbackPayload
from app.tools.backend_client import send_callback


def build_callback_payload(state: ReviewState) -> CallbackPayload:
    # llm_meta 실측치 (B2→B4): adjudicator는 escalate 경로(영수증 불일치·가드레일
    # 차단)에선 실행되지 않으므로 반드시 .get() — 대괄호 접근이면 콜백이 크래시한다
    llm_meta = state.get("llm_meta") or {}
    adj = llm_meta.get("adjudicator")
    started_at = state.get("started_at")
    return CallbackPayload(
        # 백엔드 발급 jobId를 echo (pull 모델) — 없으면(직접 그래프 호출) 내부 id
        job_id=state.get("external_job_id") or state["job_id"],
        expense_id=state["expense_id"],
        team_id=state["team_id"],
        verdict=state.get("verdict") or "escalate",
        # 카테고리 불일치 보류 시엔 AI 분류 의견을 전달(관리자 화면 "AI는 X로 봤어요"),
        # 평상시엔 확정 카테고리 — API-045/046 suggestedCategory 의미와 정합
        suggested_category=state.get("ai_suggested_category")
                           or state["claim"].category or None,
        # HITL 재개 경로: 관리자가 직접 결정한 건은 processedBy=ADMIN (API-045/046)
        processed_by="ADMIN" if state.get("admin_decision") else "AI",
        confidence=state.get("confidence"),
        opinions=list(state.get("opinions", {}).values()),
        mismatch=state.get("mismatch", []),
        reasons=state.get("reasons"),
        model_version=adj.model if adj else "mock",
        prompt_version=adj.prompt_version if adj and adj.prompt_version else "review/v1",
        cost_usd=round(sum(m.cost_usd for m in llm_meta.values()), 6),
        latency_ms=int((time.time() - started_at) * 1000) if started_at else 0,
    )


async def callback(state: ReviewState) -> dict:
    payload = build_callback_payload(state)
    # by_alias=True 필수 — 백엔드 API는 전부 camelCase (§ bravo_API명세서.xlsx)
    ok = await send_callback(payload.model_dump(mode="json", by_alias=True))
    return {"callback_status": "sent" if ok else "failed"}
