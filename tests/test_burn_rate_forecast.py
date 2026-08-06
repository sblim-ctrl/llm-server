"""burn_rate_forecast 단위 테스트 — 엣지 4종(B-2 ③) + 비중 임계 경계."""

from app.tools.burn_rate_forecast import forecast


def test_normal_projection_and_depletion():
    # 6/1~6/30 기간, 6/11 기준(경과 10일), 일소진 6,000원 → 7일 뒤(6/18) 소진
    f = forecast(
        total_budget=100_000, spent=60_000, expenses=[], as_of="2026-06-11", period_end="2026-06-30"
    )
    assert f.elapsed_days == 10
    assert f.daily_burn == 6_000.0
    assert f.projected_period_end_spent == 60_000 + 6_000 * 19
    assert f.depletion_date == "2026-06-18"


def test_elapsed_zero_on_period_start():
    # 월 1일 기준 → 경과 0일, daily_burn은 max(1, ·) 가드로 spent 그대로
    f = forecast(
        total_budget=100_000, spent=5_000, expenses=[], as_of="2026-06-01", period_end="2026-06-30"
    )
    assert f.elapsed_days == 0
    assert f.daily_burn == 5_000.0


def test_zero_spend_no_depletion():
    f = forecast(
        total_budget=100_000, spent=0, expenses=[], as_of="2026-06-11", period_end="2026-06-30"
    )
    assert f.daily_burn == 0.0
    assert f.projected_period_end_spent == 0
    assert f.depletion_date is None


def test_already_depleted_returns_as_of():
    f = forecast(
        total_budget=100_000,
        spent=120_000,
        expenses=[],
        as_of="2026-06-11",
        period_end="2026-06-30",
    )
    assert f.depletion_date == "2026-06-11"


def test_not_depleted_within_period():
    # 일소진 3,000원, 잔액 70,000원 → 24일 뒤(7/5) 소진 예상 = 기간 밖 → None
    f = forecast(
        total_budget=100_000, spent=30_000, expenses=[], as_of="2026-06-11", period_end="2026-06-30"
    )
    assert f.depletion_date is None


def test_category_share_thresholds():
    # 총 100,000원: 식비 40%(경계 포함), 대관 32%, 도서 23%, 다과 5%(경계 포함), 비품 0원(제외)
    expenses = [
        {"category": "식비", "amount": 40_000},
        {"category": "대관", "amount": 32_000},
        {"category": "도서", "amount": 23_000},
        {"category": "다과", "amount": 5_000},
        {"category": "비품", "amount": 0},
    ]
    f = forecast(
        total_budget=300_000,
        spent=118_000,
        expenses=expenses,
        as_of="2026-06-20",
        period_end="2026-06-30",
    )
    assert f.over_categories == ["식비"]  # share == 0.40 → >= 포함
    assert f.under_categories == ["다과"]  # share == 0.05 포함, 지출 0원 비품 제외


def test_as_of_equals_period_end_past_month_scenario():
    # 지난달 예산 제안 시 _period_bounds가 as_of=period_end로 클램프한다(budget_planner
    # 실사용 경로) — 남은 일수 0을 forecast가 정상 처리하는지 확인.
    f = forecast(
        total_budget=100_000,
        spent=58_000,
        expenses=[],
        as_of="2026-06-30",
        period_end="2026-06-30",
    )
    assert f.elapsed_days == 29
    assert f.projected_period_end_spent == f.spent  # 남은 일수 0 → 추가 소진분 없음


def test_depletion_date_equals_period_end_boundary():
    # d <= end_d 등호 경계 — 소진 예상일이 기간 마지막 날과 정확히 일치.
    # `<=`를 `<`로 뒤집는 회귀 시 이 케이스가 None으로 잘못 바뀐다.
    f = forecast(
        total_budget=290,
        spent=190,
        expenses=[],
        as_of="2026-06-20",
        period_end="2026-06-30",
    )
    assert f.depletion_date == "2026-06-30"


def test_tiny_spend_does_not_overflow():
    """지출이 극히 적은 팀 — 2026-08-06 발견한 기존 결함.

    소진 예정일이 date.max를 넘으면 `as_of + timedelta(...)`가 OverflowError로 죽었다.
    월초에 커피 한 잔만 결제한 팀(예산 30만원·지출 1원)에서 재현되며, 같은 forecast()를
    쓰는 Digest도 함께 죽는다. 기간 내 소진이 아님을 date 연산 **전에** 판정해 피한다.
    """
    f = forecast(
        total_budget=300_000, spent=1, expenses=[], as_of="2026-06-20", period_end="2026-06-30"
    )
    assert f.depletion_date is None


def test_empty_expenses_no_categories():
    f = forecast(
        total_budget=300_000,
        spent=118_000,
        expenses=[],
        as_of="2026-06-20",
        period_end="2026-06-30",
    )
    assert f.over_categories == []
    assert f.under_categories == []
