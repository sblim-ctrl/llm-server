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


# ── 총무 코멘트(advice) — LLM 권고 + 금액 환각 차단 ──────


async def _valid_doc():
    from app.graphs.writers.digest import generate_digest
    budget = await get_budget_status("digest-test-team")
    expenses = await get_expense_history("digest-test-team")
    f = aggregate_digest_pure(PRECEDENTS, expenses, budget, WEEK_OF)
    state = await generate_digest({"figures": f})
    return state["digest"], f


async def test_advice_present_and_passes_verification():
    doc, f = await _valid_doc()
    assert doc.advice.strip()                      # 코멘트는 필수 산출물
    assert "식비" in doc.advice                    # 이상 징후 기반 권고 (목 규약)
    assert verify_digest_pure(doc, f) is True


async def test_advice_with_fabricated_money_is_rejected():
    """조언은 자유, 돈 얘기는 정확하게 — 허용 목록 밖 금액이 advice에 있으면 폐기."""
    doc, f = await _valid_doc()
    bad = doc.model_copy(update={"advice": "다음 주 예산으로 999,999원을 배정하세요."})
    assert verify_digest_pure(bad, f) is False


async def test_advice_may_cite_known_figures():
    """figures에 있는 금액 그대로는 advice에 인용 가능 (허용 목록)."""
    doc, f = await _valid_doc()
    ok = doc.model_copy(update={
        "advice": f"주간 지출 {f.weekly_spent:,}원 수준을 유지하시길 권합니다."})
    assert verify_digest_pure(ok, f) is True


async def test_empty_advice_is_rejected():
    doc, f = await _valid_doc()
    assert verify_digest_pure(doc.model_copy(update={"advice": "  "}), f) is False


def test_advice_may_cite_negative_balance_when_budget_exceeded():
    """예산 초과 시 advice의 음수 잔액 표기 — 2026-08-05에 발견한 회귀.

    금액 정규식이 앞의 마이너스를 안 잡아서, advice의 "-50,000원"에서 "50,000원"만
    뽑히고 허용 목록("-50,000원")과 어긋나 **브리핑이 통째로 폐기**됐다.
    dashboard의 같은 결함과 한 쌍이다.

    주간 지출(37,000원)을 잔액 절댓값(50,000원)과 **일부러 다르게** 뒀다. 같으면
    떼어낸 "50,000원"이 우연히 허용 목록에 들어 있어 버그가 있어도 통과해버린다.
    """
    from app.graphs.writers.digest import DigestFigures

    forecast_cls = DigestFigures.model_fields["forecast"].annotation
    f = DigestFigures(
        week_start="2026-07-01", week_end="2026-07-07", auto_approved=1,
        auto_rejected=0, escalated=0, weekly_spent=37000,
        forecast=forecast_cls(
            total_budget=200000, spent=250000, elapsed_days=20, daily_burn=12500.0,
            projected_period_end_spent=375000, depletion_date="2026-07-10",
            over_categories=[], under_categories=[]),
        anomalies=[])
    assert f.forecast.total_budget - f.forecast.spent == -50000
    doc = DigestDoc(
        figures=f, verified=False,
        summary=("이번 주에는 자동 승인 1건, 반려 0건, 관리자 확인 0건을 처리했습니다. "
                 "주간 지출은 37,000원이며 기간 말 예상 지출은 375,000원, 잔액은 "
                 "2026-07-10에 소진될 것으로 예상됩니다."),
        highlights=["자동 승인 1건 · 반려 0건 · 에스컬레이션 0건"],
        advice="잔액이 -50,000원으로 이미 예산을 넘겼습니다. 남은 기간 집행을 멈추고 점검해 주세요.")
    assert verify_digest_pure(doc, f) is True


# ── 폴백·과장 차단 (2026-08-06, PR #11 리뷰 A-7 후속) ──────────────────────

def _figs(total_budget: int, spent: int):
    """잔액을 마음대로 정할 수 있는 최소 figures — 잔액 = total_budget - spent."""
    from app.graphs.writers.digest import DigestFigures

    forecast_cls = DigestFigures.model_fields["forecast"].annotation
    return DigestFigures(
        week_start="2026-07-01", week_end="2026-07-07", auto_approved=1,
        auto_rejected=0, escalated=0, weekly_spent=37000,
        forecast=forecast_cls(
            total_budget=total_budget, spent=spent, elapsed_days=20, daily_burn=12500.0,
            projected_period_end_spent=375000, depletion_date=None,
            over_categories=[], under_categories=[]),
        anomalies=[])


async def test_failed_verification_falls_back_to_safe_digest():
    """검증 실패 시 집계 기반 문구로 교체 — `verified`는 정직하게 false로 남긴다.

    dashboard에는 이 폴백이 있었는데 digest에는 없어서, 같은 검증기 결함이 한쪽에서만
    화면 손실로 이어지는 비대칭이 있었다(2026-08-06 발견).
    """
    from app.graphs.writers.digest import verify_digest

    f = _figs(500_000, 100_000)
    bad = DigestDoc(figures=f, summary="엉터리", highlights=[],
                    advice="잔액이 999,999원입니다.", verified=False)

    out = (await verify_digest({"digest": bad, "figures": f}))["digest"]

    assert out.verified is False, "폴백을 썼다고 verified를 올리면 필드가 의미를 잃는다"
    assert "999,999" not in out.advice, "지어낸 금액이 화면으로 나가면 안 된다"
    assert out.summary.strip(), "화면이 비면 안 된다 — 이 폴백의 존재 이유"
    assert verify_digest_pure(out, f) is True, "폴백 문구 자체는 검증을 통과해야 한다"


def test_advice_overstatement_rejected_when_balance_remains():
    """잔액이 남았는데 "다 썼다"고 하는 과장 — advice는 자유 서술이라 나오기 쉬운 자리다."""
    from app.graphs.writers.digest import _mock_digest_text

    f = _figs(500_000, 100_000)          # 잔액 400,000원
    base = _mock_digest_text(f)
    doc = DigestDoc(figures=f, summary=base.summary, highlights=base.highlights,
                    advice="예산을 모두 사용했습니다.", verified=False)
    assert verify_digest_pure(doc, f) is False


def test_advice_may_state_exhaustion_when_budget_exceeded():
    """예산을 넘겼으면 "다 썼다"는 과장이 아니라 사실이다 — 막으면 안 된다.

    조건이 `remaining > 0`인 이유(`!= 0`이 아니라). PR #11 리뷰 A-7 질문에 대한 답.
    """
    from app.graphs.writers.digest import _mock_digest_text

    f = _figs(200_000, 250_000)          # 잔액 -50,000원
    base = _mock_digest_text(f)
    doc = DigestDoc(figures=f, summary=base.summary, highlights=base.highlights,
                    advice="예산을 모두 사용했습니다.", verified=False)
    assert verify_digest_pure(doc, f) is True
