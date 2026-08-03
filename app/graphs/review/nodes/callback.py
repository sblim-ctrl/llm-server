"""callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)."""

import time
from typing import Any

from app.graphs.review.state import ReviewState
from app.schemas.callback import CallbackPayload
from app.tools.backend_client import send_callback


def trace_meta(state: ReviewState) -> dict[str, Any]:
    """LLM 호출 계측 4종 — worker가 jobs.result에 남기는 관측값.

    2026-08-03까지는 콜백 페이로드의 일부였다. 지출 상세 화면 4종 어디에도 표시되지
    않아 콜백에서 덜어냈고(`docs/internal/화면_대조_2026-08-03.md` §4), 계산 로직만
    여기 남겨 worker가 쓴다 — 원래 이 값들을 만들던 자리가 여기이기 때문이다.
    """
    # llm_meta 실측치 (B2→B4): adjudicator는 escalate 경로(영수증 불일치·가드레일
    # 차단)에선 실행되지 않으므로 반드시 .get() — 대괄호 접근이면 콜백이 크래시한다
    llm_meta = state.get("llm_meta") or {}
    adj = llm_meta.get("adjudicator")
    started_at = state.get("started_at")
    return {
        "model_version": adj.model if adj else "mock",
        "prompt_version": adj.prompt_version if adj and adj.prompt_version else "review/v1",
        "cost_usd": round(sum(m.cost_usd for m in llm_meta.values()), 6),
        "latency_ms": int((time.time() - started_at) * 1000) if started_at else 0,
    }


def build_callback_payload(state: ReviewState) -> CallbackPayload:
    return CallbackPayload(
        # 백엔드 발급 jobId를 echo (pull 모델) — 없으면(직접 그래프 호출) 내부 id
        job_id=state.get("external_job_id") or state["job_id"],
        expense_id=state["expense_id"],
        team_id=state["team_id"],
        verdict=state.get("verdict") or "escalate",
        suggested_category=state["claim"].category or None,
        confidence=state.get("confidence"),
        opinions=list(state.get("opinions", {}).values()),
        mismatch=state.get("mismatch", []),
        reasons=state.get("reasons"),
    )


async def callback(state: ReviewState) -> dict:
    payload = build_callback_payload(state)
    # by_alias=True 필수 — 백엔드 API는 전부 camelCase (§ bravo_API명세서.xlsx)
    ok = await send_callback(payload.model_dump(mode="json", by_alias=True))
    return {"callback_status": "sent" if ok else "failed"}
