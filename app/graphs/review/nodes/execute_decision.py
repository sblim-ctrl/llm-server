"""execute_decision — Agent 승인/반려 API 호출 (멱등성 키 = job_id, §4.2).

escalate 건은 이 노드에 오지 않는다 (상태 변경 없음).
"""
from app.graphs.review.state import ReviewState
from app.tools.backend_client import approve_expense, reject_expense


async def execute_decision(state: ReviewState) -> dict:
    verdict = state["verdict"]
    expense_id = state["expense_id"]
    idempotency_key = state["job_id"]  # 잡 재시도에도 이중 처리 방지
    reason = state["reasons"].admin if state.get("reasons") else ""

    if verdict == "approve":
        result = await approve_expense(expense_id, idempotency_key, reason)
    else:
        result = await reject_expense(expense_id, idempotency_key, reason)

    return {"execution_result": result}
