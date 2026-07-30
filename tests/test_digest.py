"""DigestWriter (A-4) — 주간 윈도우·집계·이상 징후·수치 검증.

fetch(DB)는 제외하고 순수 함수·생성 노드를 검증한다 (test_briefing.py 스타일).
이상 징후 규칙이 '실제 목 데이터'로 발화하는지 확인하는 테스트 포함 (A-4 명세 —
개발자 B의 seed_demo·목 데이터 확장은 C10 append-only라 이 테스트와 정합 유지 필요).
"""
from app.graphs.writers.digest import (
    DigestDoc, aggregate_digest_pure, detect_anomalies_pure, generate_digest,
    verify_digest_pure, week_bounds,
)
from app.tools.backend_client import get_budget_status, get_expense_history

# 목 get_expense_history의 6월 데이터에서 식비 급증이 걸리는 주 (6/22 월 ~ 6/28 일):
# 주간 식비 96,000원 vs 직전 4주(5/25~6/21) 식비 146,000원 → 주평균 36,500원의 2배 초과
WEEK_OF = "2026-06-26"


def test_week_bounds_monday_to_sunday():
    assert week_bounds("2026-06-26") == ("2026-06-22", "2026-06-28")   # 금요일 기준
    assert week_bounds("2026-06-22") == ("2026-06-22", "2026-06-28")   # 월요일 그대로


def test_request_rejects_invalid_date():
    """잘못된 week_of는 API 422로 거절 — 워커 3회 재시도→dead 낭비 방지."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.writers import DigestRequest
    with pytest.raises(ValidationError):
        DigestRequest(team_id=1, week_of="2026-99-99")
    with pytest.raises(ValidationError):
        DigestRequest(team_id=1, week_of="다음주")
    assert DigestRequest(team_id=1, week_of="2026-06-26").week_of == "2026-06-26"


PRECEDENTS = [
    {"decision": "approve", "decided_by": "AGENT"},
    {"decision": "approve", "decided_by": "AGENT"},
    {"decision": "reject", "decided_by": "AGENT"},
    {"decision": "escalate", "decided_by": "AGENT"},
    {"decision": "approve", "decided_by": "ADMIN"},   # 관리자 결정 — auto 집계 제외
]


async def test_aggregate_with_real_mock_data_fires_spike_anomaly():
    """이상 징후 ①이 목 데이터로 실제 발화하는지 (A-4 명세의 명시 요구)."""
    budget = await get_budget_status("digest-test-team")
    expenses = await get_expense_history("digest-test-team")
    f = aggregate_digest_pure(PRECEDENTS, expenses, budget, WEEK_OF)

    assert f.week_start == "2026-06-22" and f.week_end == "2026-06-28"
    assert (f.auto_approved, f.auto_rejected, f.escalated) == (2, 1, 1)
    assert f.weekly_spent == 108_000                       # 비품 12,000 + 식비 96,000
    assert any(a.startswith("식비") for a in f.anomalies)  # 급증 규칙 발화
    assert f.forecast.total_budget == budget["total_budget"]  # C8 — B-2 forecast 탑재


def test_spike_needs_prior_history():
    """직전 지출이 없는 카테고리의 첫 지출은 급증이 아님 (정보 부족)."""
    expenses = [{"category": "비품", "amount": 999_999, "date": "2026-06-25",
                 "status": "APPROVED"}]
    assert detect_anomalies_pure([], expenses, "2026-06-22", "2026-06-28") == []


def test_consecutive_escalates_fire_anomaly():
    esc = {"decision": "escalate", "decided_by": "AGENT"}
    ok = {"decision": "approve", "decided_by": "AGENT"}
    assert detect_anomalies_pure([esc, esc, esc], [], "2026-06-22", "2026-06-28") \
        == ["에스컬레이션이 3건 연속 발생했습니다"]
    # 연속이 끊기면 미발화
    assert detect_anomalies_pure([esc, esc, ok, esc], [], "2026-06-22", "2026-06-28") == []


async def test_generated_digest_passes_verification():
    budget = await get_budget_status("digest-test-team")
    expenses = await get_expense_history("digest-test-team")
    f = aggregate_digest_pure(PRECEDENTS, expenses, budget, WEEK_OF)
    state = await generate_digest({"figures": f})

    assert verify_digest_pure(state["digest"], f) is True
    assert state["llm_meta"]["digest_writer"].mock is True   # 목 모드 계측 확인 (B-7 재료)


async def test_verification_detects_figure_mismatch():
    budget = await get_budget_status("digest-test-team")
    expenses = await get_expense_history("digest-test-team")
    f = aggregate_digest_pure(PRECEDENTS, expenses, budget, WEEK_OF)
    bad = DigestDoc(figures=f, summary="자동 승인 999건뿐입니다.", highlights=[],
                    verified=False)
    assert verify_digest_pure(bad, f) is False
