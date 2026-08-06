"""소진 속도 예측 — 순수 Python. 수치 계산은 LLM에 맡기지 않는다 (§9.1).

spent 출처 단일화 규칙 (B-2 ④ — 목 데이터 불일치 방어):
daily_burn·projected·depletion_date는 budget.spent(총액) 기준,
over/under 카테고리는 expenses 비중 기준 — 의미가 다른 두 수치를
한 문장에 섞지 않는다. 소비자(BudgetPlanner·Digest)도 이 규칙을 따른다.

기간은 월 단위 가정: 기간 시작 = period_end가 속한 달의 1일.
as_of는 파라미터로 받는다 (함수 안 now() 금지 — 테스트 결정성).
"""

import math
from datetime import date, timedelta

from pydantic import BaseModel

# 편중·저활용 임계는 report.py와 동일 기준 재사용 (B-2 명세)
from app.graphs.writers.report import HIGH_SHARE, LOW_SHARE


class BurnForecast(BaseModel):
    """C8 계약 — 개발자 A의 Digest(DigestFigures.forecast)가 소비. 필드 변경은 상호 리뷰."""

    total_budget: int
    spent: int
    elapsed_days: int  # 기간 시작(월초)~as_of 경과일
    daily_burn: float  # spent / max(1, elapsed_days)
    projected_period_end_spent: int  # 현재 속도 유지 시 기간 말 예상 지출
    depletion_date: str | None  # 잔액 소진 예상일 (기간 내 소진 안 되면 None)
    over_categories: list[str]  # 비중 >= HIGH_SHARE(0.4) — expenses 기준
    under_categories: list[str]  # 비중 <= LOW_SHARE(0.05)·지출 > 0 — expenses 기준


def forecast(
    total_budget: int, spent: int, expenses: list[dict], as_of: str, period_end: str
) -> BurnForecast:
    """소진 예측. expenses는 호출부가 이미 APPROVED로 필터한 목록을 넘긴다."""
    as_of_d = date.fromisoformat(as_of)
    end_d = date.fromisoformat(period_end)
    period_start = end_d.replace(day=1)

    elapsed_days = max(0, (as_of_d - period_start).days)
    daily_burn = spent / max(1, elapsed_days)

    remaining_days = max(0, (end_d - as_of_d).days)
    projected = spent + round(daily_burn * remaining_days)

    remaining = total_budget - spent
    if remaining <= 0:
        depletion: str | None = as_of  # 이미 소진
    elif daily_burn <= 0:
        depletion = None  # 지출 0 — 소진 없음
    else:
        # 기간 내 소진 여부를 date 연산 **전에** 일수로 판정한다 — 지출이 극히 적으면
        # 소진 예정일이 date.max를 넘어 timedelta가 OverflowError로 죽는다 (2026-08-06 발견).
        days = math.ceil(remaining / daily_burn)
        depletion = (as_of_d + timedelta(days=days)).isoformat() if days <= remaining_days else None

    # 카테고리 비중 (expenses 기준 — 총액 수치와 의미 분리, 위 docstring 규칙)
    by_cat: dict[str, int] = {}
    for e in expenses:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
    total_exp = sum(by_cat.values())
    ordered = sorted(by_cat.items(), key=lambda kv: -kv[1])  # 지출 큰 순 — 결정적 순서
    over = [c for c, v in ordered if total_exp and v / total_exp >= HIGH_SHARE]
    under = [c for c, v in ordered if total_exp and v > 0 and v / total_exp <= LOW_SHARE]

    return BurnForecast(
        total_budget=total_budget,
        spent=spent,
        elapsed_days=elapsed_days,
        daily_burn=daily_burn,
        projected_period_end_spent=projected,
        depletion_date=depletion,
        over_categories=over,
        under_categories=under,
    )
