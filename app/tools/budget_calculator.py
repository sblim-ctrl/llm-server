"""예산 수치 계산 — 순수 Python. 수치 계산은 LLM에 맡기지 않는다 (§5.1)."""
from pydantic import BaseModel


class BudgetCheck(BaseModel):
    limit: int              # 카테고리 한도
    spent: int              # 기간 내 기사용액
    amount: int             # 이번 청구액
    remaining_before: int   # 청구 전 잔액
    remaining_after: int    # 승인 시 잔액
    usage_rate_after: float # 승인 시 사용률 (0.0~1.0+)
    sufficient: bool        # 잔액으로 충당 가능한가


def check_budget(limit: int, spent: int, amount: int) -> BudgetCheck:
    remaining_before = limit - spent
    remaining_after = remaining_before - amount
    return BudgetCheck(
        limit=limit,
        spent=spent,
        amount=amount,
        remaining_before=remaining_before,
        remaining_after=remaining_after,
        usage_rate_after=(spent + amount) / limit if limit > 0 else 1.0,
        sufficient=remaining_after >= 0,
    )
