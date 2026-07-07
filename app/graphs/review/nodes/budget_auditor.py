"""budget_auditor — 예산 심사관 (병렬). 수치 계산은 코드(budget_calculator), LLM은 해석만."""
import logging

from app.graphs.review.state import ReviewState
from app.schemas.common import Opinion
from app.tools.backend_client import get_budget_status
from app.tools.budget_calculator import check_budget

logger = logging.getLogger(__name__)

PROMPT_VERSION = "budget_auditor/v1"


async def budget_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        budget = await get_budget_status(state["team_id"], claim.category)
        check = check_budget(limit=budget["limit"], spent=budget["spent"], amount=claim.amount)

        if not check.sufficient:
            verdict, summary = "fail", (
                f"잔액 부족: 잔액 {check.remaining_before:,}원 < 청구 {claim.amount:,}원"
            )
        elif check.usage_rate_after >= 0.9:
            verdict, summary = "warn", (
                f"승인 시 예산 사용률 {check.usage_rate_after:.0%} — 한도 근접"
            )
        else:
            verdict, summary = "pass", (
                f"잔액 충분: 승인 후 잔액 {check.remaining_after:,}원"
            )

        return {"opinions": {"budget": Opinion(
            auditor="budget", verdict=verdict, summary=summary,
            figures={"limit": check.limit, "spent": check.spent,
                     "remaining": check.remaining_before,
                     "remaining_after": check.remaining_after},
        )}}
    except Exception:
        logger.exception("budget_auditor failed")
        return {"opinions": {"budget": Opinion(
            auditor="budget", verdict="error", summary="예산 조회 실패",
        )}}
