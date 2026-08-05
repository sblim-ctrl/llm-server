"""대시보드 AI 요약 (풀스택 협의 2026-08-04 5번).

집계는 순수 함수라 그대로 검증하고, 요약문은 '수치가 집계에서만 나왔는가'를 본다.
문장 자체는 강제하지 않는다 — 실모드 LLM이 다듬는 영역이다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.api.dashboards import create_dashboard_summary
from app.graphs.writers.dashboard import (
    aggregate_dashboard_pure, allowed_money, verify_summary_pure,
)
from app.schemas.dashboard import DashboardSummaryDoc, DashboardSummaryRequest

BUDGET = {"total_budget": 800_000, "spent": 320_000}
EXPENSES = [
    # 이번 달 (승인)
    {"title": "AWS 서버 운영비", "amount": 180_000, "category": "IT/인프라",
     "date": "2026-07-18", "status": "APPROVED"},
    {"title": "외부 강사 강연료", "amount": 90_000, "category": "교육",
     "date": "2026-07-12", "status": "APPROVED"},
    {"title": "팀 회식", "amount": 50_000, "category": "식비",
     "date": "2026-07-20", "status": "APPROVED"},
    # 전월 (승인)
    {"title": "지난달 서버비", "amount": 146_000, "category": "IT/인프라",
     "date": "2026-06-18", "status": "APPROVED"},
    {"title": "지난달 회식", "amount": 40_000, "category": "식비",
     "date": "2026-06-20", "status": "APPROVED"},
    # 이번 달 대기
    {"title": "해커톤 참가비", "amount": 60_000, "category": "행사/활동",
     "date": "2026-07-22", "status": "PENDING"},
]


def _figures(expenses=EXPENSES, budget=BUDGET, period="2026-07"):
    return aggregate_dashboard_pure(expenses, budget, period)


# ── 집계 ──────────────────────────────────────────────────────────────────

def test_spent_counts_approved_only_and_current_month():
    f = _figures()
    assert f.spent == 320_000              # 180+90+50, 전월·대기 제외
    assert f.remaining == 480_000
    assert f.usage_ratio == pytest.approx(0.4)


def test_pending_is_counted_separately_not_as_spent():
    """대기 건은 아직 나간 돈이 아니다 — 화면도 '사용됨/대기 중'을 나눠 보여준다."""
    f = _figures()
    assert f.pending_count == 1
    assert f.pending_amount == 60_000
    assert f.spent == 320_000              # 대기 60,000이 섞이지 않았다


def test_top_category_and_share():
    f = _figures()
    assert f.top_category.category == "IT/인프라"
    assert f.top_category.share == pytest.approx(180_000 / 320_000)


def test_month_over_month_change():
    f = _figures()
    it = next(c for c in f.categories if c.category == "IT/인프라")
    assert it.prev_spent == 146_000
    assert it.change_ratio == pytest.approx((180_000 - 146_000) / 146_000)
    # 증가율 1위는 식비 (50,000 vs 40,000 = +25%)
    assert f.fastest_growing.category == "식비"
    assert f.fastest_growing.change_ratio == pytest.approx(0.25)


def test_new_category_has_null_change_ratio():
    """전월이 0이면 증가율을 정의할 수 없다 — 0으로 두면 '변화 없음'으로 읽힌다."""
    f = _figures([
        {"title": "신규", "amount": 10_000, "category": "교통",
         "date": "2026-07-01", "status": "APPROVED"},
    ])
    assert f.categories[0].change_ratio is None
    assert f.fastest_growing is None       # 증가로 셀 수 없다


def test_largest_expense():
    f = _figures()
    assert f.largest_expense_title == "AWS 서버 운영비"
    assert f.largest_expense_amount == 180_000


def test_empty_month():
    f = _figures([], {"total_budget": 500_000, "spent": 0})
    assert f.spent == 0 and f.remaining == 500_000
    assert f.categories == [] and f.top_category is None
    assert f.usage_ratio == 0.0
    assert f.largest_expense_title is None


def test_zero_budget_does_not_divide_by_zero():
    f = _figures(EXPENSES, {"total_budget": 0, "spent": 0})
    assert f.usage_ratio == 0.0


def test_january_looks_back_to_previous_december():
    f = _figures([
        {"title": "12월 지출", "amount": 30_000, "category": "식비",
         "date": "2025-12-20", "status": "APPROVED"},
        {"title": "1월 지출", "amount": 60_000, "category": "식비",
         "date": "2026-01-10", "status": "APPROVED"},
    ], BUDGET, "2026-01")
    assert f.categories[0].prev_spent == 30_000
    assert f.categories[0].change_ratio == pytest.approx(1.0)


# ── 검증 ──────────────────────────────────────────────────────────────────

def _doc(message: str) -> DashboardSummaryDoc:
    return DashboardSummaryDoc(figures=_figures(), message=message, verified=False)


def test_verifier_accepts_numbers_from_figures():
    assert verify_summary_pure(_doc(
        "이번 달 지출은 320,000원으로 예산의 40%를 썼고 480,000원이 남았습니다.")) is True


def test_verifier_rejects_invented_money():
    """대시보드는 관리자가 예산 판단을 하는 화면이라 없는 금액이 가장 해롭다."""
    assert verify_summary_pure(_doc("이번 달 지출은 999,999원입니다.")) is False


def test_verifier_rejects_invented_percent():
    assert verify_summary_pure(_doc("예산의 77%를 썼습니다.")) is False


def test_verifier_rejects_empty_message():
    assert verify_summary_pure(_doc("   ")) is False


def test_verifier_accepts_negative_remaining_when_budget_exceeded():
    """예산 초과(잔액 음수) — 2026-08-05에 발견한 회귀.

    금액 정규식이 앞의 마이너스를 안 잡아서, 본문의 "-99,000원"에서 "99,000원"만
    뽑히고 허용 목록("-99,000원")과 어긋나 **요약이 항상 폐기**됐다. 예산을 넘긴
    달은 관리자가 대시보드를 가장 봐야 할 때인데 그때 화면이 비는 방향이라
    실사용에서 가장 나빴다.
    """
    over = _figures(
        expenses=[{"title": "행사비", "amount": 399000, "category": "행사_활동",
                   "date": "2026-07-10", "status": "APPROVED"}],
        budget={"total_budget": 300000, "spent": 399000},
    )
    assert over.remaining == -99000, "이 케이스는 잔액이 음수여야 의미가 있다"
    doc = DashboardSummaryDoc(
        figures=over, verified=False,
        message="이번 달 지출은 399,000원으로 남은 예산은 -99,000원입니다.")
    assert verify_summary_pure(doc) is True


def test_verifier_still_rejects_invented_negative_money():
    """마이너스를 허용했다고 아무 음수나 통과하면 안 된다 — 환각 방어는 그대로."""
    over = _figures(budget={"total_budget": 300000, "spent": 399000})
    doc = DashboardSummaryDoc(
        figures=over, verified=False, message="남은 예산은 -12,345원입니다.")
    assert verify_summary_pure(doc) is False


def test_verifier_allows_category_amounts():
    assert verify_summary_pure(_doc(
        "IT/인프라가 180,000원으로 가장 큽니다.")) is True


def test_allowed_money_excludes_zero():
    """0원은 허용 목록에 넣지 않는다 — '0원'이 아무 데나 붙는 걸 막는다.

    잔액이 남아 있는데 "남은 예산은 0원"이라고 쓰는 것을 막는 가드다. 아래
    test_allowed_money_includes_zero_only_when_balance_is_zero와 한 쌍으로 본다.
    """
    f = _figures([], {"total_budget": 500_000, "spent": 0})
    assert f.remaining == 500_000
    assert "0원" not in allowed_money(f)


def test_allowed_money_includes_zero_only_when_balance_is_zero():
    """예산을 딱 맞춰 쓴 달만 '0원'을 허용한다 — 2026-08-05에 발견한 회귀.

    잔액이 정확히 0이면 본문에 "남은 예산은 0원입니다"가 나올 수밖에 없는데,
    0을 일괄로 걸러내던 탓에 그 요약이 통째로 폐기됐다. 음수 잔액 건과 한 쌍이다.

    처음엔 0을 전부 허용하도록 고쳤다가 위 가드를 깨뜨렸다 — 0은 어느 문장에나
    자연스럽게 붙어서 일괄 허용하면 검증기가 사실상 그 표현을 못 막는다.
    그래서 **실제로 잔액이 0인 경우만** 연다.
    """
    exact = _figures(
        expenses=[{"title": "행사", "amount": 300000, "category": "행사_활동",
                   "date": "2026-07-10", "status": "APPROVED"}],
        budget={"total_budget": 300000, "spent": 300000},
    )
    assert exact.remaining == 0
    assert "0원" in allowed_money(exact)
    doc = DashboardSummaryDoc(
        figures=exact, verified=False,
        message="이번 달 지출은 300,000원으로 예산의 100%를 썼어요. 남은 예산은 0원입니다.")
    assert verify_summary_pure(doc) is True


# ── 과장 표현 차단 ────────────────────────────────────────────────────────

def test_verifier_rejects_overstatement_when_balance_remains():
    """잔액이 남았는데 "다 썼다"고 하는 과장 — 숫자가 아니라 서술이 틀린 경우.

    v1 실측에서 95% 사용·1만원 잔여를 "전체 예산을 모두 사용했어요"로 썼다. 숫자가
    맞아서 토큰 대조로는 안 잡혔고, 프롬프트 규칙으로 막으려 했으나 2회 다 실패해
    few_shot으로 눌렀다. 그 방어가 프롬프트에만 있어 깨져도 아무도 몰랐다.
    """
    f = _figures(
        expenses=[{"title": "행사", "amount": 190000, "category": "행사_활동",
                   "date": "2026-07-10", "status": "APPROVED"}],
        budget={"total_budget": 200000, "spent": 190000})
    assert f.remaining == 10000, "잔액이 남아 있어야 과장이 성립한다"
    for msg in ("전체 예산을 모두 사용했어요.",
                "예산을 전부 사용했습니다.",
                "남은 예산이 없습니다.",
                "예산이 바닥났어요."):
        doc = DashboardSummaryDoc(figures=f, message=msg, verified=False)
        assert verify_summary_pure(doc) is False, f"과장을 놓쳤다: {msg}"


def test_verifier_allows_conditional_and_normal_phrasing():
    """가정·미래형은 과장이 아니다 — 오탐이 나면 멀쩡한 요약이 폴백으로 밀린다."""
    f = _figures()
    for msg in ("예산을 모두 사용하면 알려드릴게요.",
                "이번 달 지출은 320,000원으로 예산의 40%를 썼고 480,000원이 남았어요.",
                "카테고리별로 고르게 사용 중이에요."):
        doc = DashboardSummaryDoc(figures=f, message=msg, verified=False)
        assert verify_summary_pure(doc) is True, f"정상 문장을 걸렀다: {msg}"


# ── 폴백 (검증 실패 시 화면이 비지 않는다) ────────────────────────────────

async def test_failed_verification_falls_back_to_safe_message():
    """검증 실패 시 집계 기반 문장으로 교체 — `verified`는 정직하게 false로 남긴다.

    종전에는 AI 문장을 그대로 두고 verified=false만 내렸다. 명세는 그때 "띄우지
    말거나 '확인 필요'로 표시"하라 했는데 어느 쪽이든 나쁘다. 2026-08-05에 검증기
    결함 2건으로 멀쩡한 달이 실제로 그 상태가 됐다.
    """
    from app.graphs.writers.dashboard import dashboard_graph
    from app.schemas.dashboard import DashboardSummary

    with patch("app.graphs.writers.dashboard.get_expense_history",
               AsyncMock(return_value=EXPENSES)), \
         patch("app.graphs.writers.dashboard.get_budget_status",
               AsyncMock(return_value=BUDGET)), \
         patch("app.graphs.writers.dashboard.chat_structured",
               AsyncMock(return_value=(DashboardSummary(message="지출은 999,999원입니다."), None))):
        final = await dashboard_graph.ainvoke(
            {"request": DashboardSummaryRequest(team_id=9001, period="2026-07")})

    doc = final["doc"]
    assert doc.verified is False, "폴백을 썼다고 verified를 올리면 필드가 의미를 잃는다"
    assert "999,999" not in doc.message, "지어낸 금액이 화면으로 나가면 안 된다"
    assert doc.message.strip(), "화면이 비면 안 된다 — 이 폴백의 존재 이유"
    assert verify_summary_pure(doc) is True, "폴백 문장 자체는 검증을 통과해야 한다"


# ── API (목 모드) ─────────────────────────────────────────────────────────

async def test_api_returns_verified_summary():
    with patch("app.graphs.writers.dashboard.get_expense_history",
               AsyncMock(return_value=EXPENSES)), \
         patch("app.graphs.writers.dashboard.get_budget_status",
               AsyncMock(return_value=BUDGET)):
        doc = await create_dashboard_summary(
            DashboardSummaryRequest(team_id=9001, period="2026-07"))

    assert doc.verified is True
    assert doc.message.strip()
    assert doc.figures.spent == 320_000


async def test_api_handles_month_without_expenses():
    """지출이 없어도 빈 문자열이 아니라 그 사실을 말하는 문장이 와야 한다."""
    with patch("app.graphs.writers.dashboard.get_expense_history",
               AsyncMock(return_value=[])), \
         patch("app.graphs.writers.dashboard.get_budget_status",
               AsyncMock(return_value={"total_budget": 500_000, "spent": 0})):
        doc = await create_dashboard_summary(
            DashboardSummaryRequest(team_id=9001, period="2026-07"))

    assert doc.verified is True
    assert "500,000원" in doc.message


def test_request_rejects_bad_period():
    for bad in ["2026", "2026-13", "26-07", "2026-7"]:
        with pytest.raises(ValueError):
            DashboardSummaryRequest(team_id=9001, period=bad)
