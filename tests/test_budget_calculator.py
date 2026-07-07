"""budget_calculator 단위 테스트 — 수치 판단 정확도 100% 목표 (§9.1)."""
from app.tools.budget_calculator import check_budget


def test_sufficient():
    c = check_budget(limit=300_000, spent=118_000, amount=45_000)
    assert c.sufficient is True
    assert c.remaining_before == 182_000
    assert c.remaining_after == 137_000


def test_insufficient():
    c = check_budget(limit=100_000, spent=90_000, amount=20_000)
    assert c.sufficient is False
    assert c.remaining_after == -10_000


def test_exact_boundary_is_sufficient():
    c = check_budget(limit=100_000, spent=50_000, amount=50_000)
    assert c.sufficient is True
    assert c.remaining_after == 0
    assert c.usage_rate_after == 1.0


def test_zero_limit():
    c = check_budget(limit=0, spent=0, amount=1_000)
    assert c.sufficient is False
    assert c.usage_rate_after == 1.0
