"""callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)."""
from app.graphs.review.state import ReviewState
from app.schemas.callback import CallbackPayload
from app.tools.backend_client import send_callback


def build_callback_payload(state: ReviewState) -> CallbackPayload:
    return CallbackPayload(
        job_id=state["job_id"],
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
