"""budget_auditor — 예산 심사관 (병렬). 수치 계산은 코드(budget_calculator), LLM은 해석만.

[팀 확인 2026-07-09] 예산은 '모임 전체 총액' 하나 — 잔액 = 총예산 − 승인된 지출 합계.
카테고리는 지출 내역 분류·현황 표시용이며 한도 검사 기준이 아니다.
(관리자 수동 카테고리 한도 버튼은 유지/제거 상의중 — 확정 시 백엔드 응답에
category_limit이 추가되면 아래에 카테고리 검사 한 단계만 더하면 됨: 확장 지점)
"""
import logging

from app.graphs.review.state import ReviewState
from app.schemas.common import Opinion
from app.tools.backend_client import get_budget_status
from app.tools.budget_calculator import check_budget

logger = logging.getLogger(__name__)

# budget_auditor는 LLM을 호출하지 않는 결정적 계산 노드 — 프롬프트·버전 개념 없음 (B1 정리)


async def budget_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        budget = await get_budget_status(state["team_id"])
        check = check_budget(limit=budget["total_budget"], spent=budget["spent"],
                             amount=claim.amount)

        if not check.sufficient:
            verdict, summary = "fail", (
                f"총예산 잔액 부족: 잔액 {check.remaining_before:,}원 < 청구 {claim.amount:,}원"
            )
        elif check.usage_rate_after >= 0.9:
            verdict, summary = "warn", (
                f"승인 시 총예산 사용률 {check.usage_rate_after:.0%} — 소진 임박"
            )
        else:
            verdict, summary = "pass", (
                f"총예산 잔액 충분: 승인 후 잔액 {check.remaining_after:,}원"
            )

        return {"opinions": {"budget": Opinion(
            auditor="budget", verdict=verdict, summary=summary,
            figures={"total_budget": check.limit, "spent": check.spent,
                     "remaining": check.remaining_before,
                     "remaining_after": check.remaining_after},
        )}}
    except Exception:
        logger.exception("budget_auditor failed")
        return {"opinions": {"budget": Opinion(
            auditor="budget", verdict="error", summary="예산 조회 실패",
        )}}
