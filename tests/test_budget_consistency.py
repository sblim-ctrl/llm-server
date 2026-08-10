"""대시보드·budget_auditor가 같은 백엔드 누적 spent를 기준으로 잔액을 일치시키는지 교차 검증.

과거엔 대시보드가 당월 지출만 합산해 잔액을 계산해서, 당월 지출이 0건인 달은 잔액이
예산 전액이 되는 자기모순이 있었다(eval/golden/writers_golden_v1.json의 db-tight-budget
케이스가 이 문제를 피해 5월 대신 6월을 골랐던 이력 참고). 이 테스트는 그 자기모순이
해소됐는지 확인한다.
"""

import json
from pathlib import Path

import pytest

from app.graphs.writers.dashboard import aggregate_dashboard_pure
from app.tools.budget_calculator import check_budget

_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "mock_backend.json").read_text(
        encoding="utf-8"
    )
)
TEAM_9026_BUDGET = _FIXTURE["organizations"]["9026"]["budget"]
TEAM_9026_HISTORY = _FIXTURE["expense_histories"]["tight_study"]


def test_dashboard_remaining_uses_backend_cumulative_even_when_period_is_empty():
    """2026-05는 tight_study에 항목이 없다 — 그래도 잔액은 예산 전액이 아니어야 한다."""
    figures = aggregate_dashboard_pure(TEAM_9026_HISTORY, TEAM_9026_BUDGET, "2026-05")
    assert figures.spent == 0  # 당월 승인 지출은 실제로 0건
    assert figures.remaining == 22_000  # 그래도 잔액은 백엔드 누적 기준
    assert figures.usage_ratio == pytest.approx(0.89, abs=0.005)


def test_dashboard_remaining_matches_budget_auditor():
    """대시보드와 budget_auditor(check_budget)가 같은 잔액을 말해야 한다."""
    figures = aggregate_dashboard_pure(TEAM_9026_HISTORY, TEAM_9026_BUDGET, "2026-05")
    check = check_budget(
        limit=TEAM_9026_BUDGET["total_budget"], spent=TEAM_9026_BUDGET["spent"], amount=0
    )
    assert figures.remaining == check.remaining_before
