"""BudgetPlanner 단위 테스트 — 순수 함수 + 목 모드 generate 노드 (DB 무접촉)."""

from datetime import date

import pytest
from pydantic import ValidationError

import app.graphs.writers.budget_planner as bp
from app.graphs.writers.budget_planner import (
    SMALL_EXPENSE_MAX,
    _period_bounds,
    build_budget_figures,
    generate_proposal,
)
from app.schemas.proposals import ProposalBudgetRequest
from app.tools.burn_rate_forecast import forecast

EXPENSES = [
    {"category": "식비", "amount": 45_000},  # 45% → over
    {"category": "대관", "amount": 30_000},
    {"category": "도서", "amount": 22_500},
    {"category": "다과", "amount": 2_500},  # 2.5% → under
]


def _forecast():
    return forecast(
        total_budget=100_000,
        spent=60_000,
        expenses=EXPENSES,
        as_of="2026-06-11",
        period_end="2026-06-30",
    )


# ── T4 3블록 집계 (BudgetFigures) ──────────────────────────────────

EXPENSES_3B = [
    {"category": "비품", "amount": 60_000},  # 75% → over
    {"category": "식비", "amount": 8_000},  # 소액
    {"category": "식비", "amount": 12_000},  # 소액 — 식비 합 20,000 (25%)
]

AS_OF, PERIOD_END = "2026-06-20", "2026-06-30"


def _figures(total_budget=300_000, spent=118_000, expenses=None):
    """기간을 6/1~6/30·경과 19일로 고정한다 — 오늘 날짜에 의존하지 않게."""
    expenses = EXPENSES_3B if expenses is None else expenses
    f = forecast(total_budget, spent, expenses, as_of=AS_OF, period_end=PERIOD_END)
    return build_budget_figures(f, expenses, as_of=AS_OF, period_end=PERIOD_END)


def test_figures_shares_and_usage_ratio():
    fig = _figures()
    assert fig.expenses_total == 80_000
    assert [(c.category, c.spent) for c in fig.categories] == [("비품", 60_000), ("식비", 20_000)]
    assert fig.categories[0].share == pytest.approx(0.75)  # 지출 큰 순 — 결정적 순서
    assert fig.categories[1].share == pytest.approx(0.25)
    assert fig.remaining == 182_000
    assert fig.usage_ratio == pytest.approx(118_000 / 300_000)
    assert fig.reserve_amount == 27_300  # 잔액의 15%


def test_figures_negative_remaining_has_no_reserve():
    """예산 초과는 이 화면에서 정상 상태다 — 잔액 음수를 그대로 싣되 예비비 권고는 끈다."""
    fig = _figures(total_budget=100_000, spent=137_000)
    assert fig.remaining == -37_000, "이 케이스는 잔액이 음수여야 의미가 있다"
    assert fig.reserve_amount == 0
    assert fig.usage_ratio == pytest.approx(1.37)  # 100% 초과도 그대로


def test_figures_zero_remaining():
    fig = _figures(total_budget=118_000, spent=118_000)
    assert fig.remaining == 0
    assert fig.reserve_amount == 0


def test_figures_no_expenses_has_no_zero_division():
    """지출 내역이 없는 신규 팀·월초 — 가장 흔한 첫 화면이라 여기서 죽으면 안 된다."""
    fig = _figures(expenses=[])
    assert fig.expenses_total == 0
    assert fig.categories == []
    assert fig.small_expense_share == 0.0


def test_figures_small_expense_metrics():
    fig = _figures()
    assert fig.small_expense_max == SMALL_EXPENSE_MAX
    assert fig.small_expense_total == 20_000  # 8,000 + 12,000 (경계 20,000 이하)
    assert fig.small_expense_count == 2
    assert fig.small_expense_share == pytest.approx(0.25)
    assert fig.small_expense_categories == ["식비"]
    assert fig.savings_potential == 10_000  # 절반 감축 가정


def test_figures_small_expense_boundary_is_inclusive():
    fig = _figures(expenses=[{"category": "비품", "amount": SMALL_EXPENSE_MAX}])
    assert fig.small_expense_count == 1, "상한 금액 자체는 소액에 포함된다"


def test_figures_projected_overrun():
    fig = _figures(total_budget=100_000, spent=90_000)
    assert fig.forecast.projected_period_end_spent > 100_000, "이 케이스는 초과 예상이어야 한다"
    assert fig.projected_overrun == fig.forecast.projected_period_end_spent - 100_000
    assert _figures().projected_overrun == 0, "초과 예상이 아니면 0"


def test_figures_daily_burn_is_rounded_int():
    """float 그대로 두면 검증기 허용 목록이 '6,210.5원'을 만들어 실제 표기와 어긋난다."""
    fig = _figures()
    assert fig.daily_burn == round(fig.forecast.daily_burn)
    assert isinstance(fig.daily_burn, int)


# ── T4 3블록 검증기 ────────────────────────────────────────────────

# 목/폴백 문장이 모든 상황에서 검증을 통과해야 한다는 불변식을 시나리오 전수로 못 박는다.
# 깨지면 그 달에는 화면에 띄울 문장이 아예 없어진다.
MOCK_INVARIANT_CASES = {
    "정상": {},
    "잔액 음수": {"total_budget": 100_000, "spent": 137_000},
    "잔액 0": {"total_budget": 118_000, "spent": 118_000},
    "지출 내역 없음": {"expenses": []},
    "지출 0원 (신규 팀·월초)": {"spent": 0},
    "예산 0": {"total_budget": 0, "spent": 0},
    "금액 0원 지출만": {"expenses": [{"category": "비품", "amount": 0}]},
    "소액 1원 1건": {"expenses": [{"category": "식비", "amount": 1}]},
    "카테고리 1종": {"expenses": [{"category": "교육", "amount": 50_000}]},
    "기간 내 소진 예상": {"total_budget": 130_000, "spent": 118_000},
    "지출 극소 (소진일 계산 극단)": {"spent": 1},
}


def _msg(fig, **overrides):
    return bp._mock_budget_message(fig).model_copy(update=overrides)


def test_mock_message_passes_verifier():
    """폴백 불변식 — 목 문장은 어떤 집계값에서도 자기 검증기를 통과해야 한다."""
    for label, kwargs in MOCK_INVARIANT_CASES.items():
        fig = _figures(**kwargs)
        assert bp.verify_budget_message_pure(bp._mock_budget_message(fig), fig), (
            f"목 문장이 폐기됐다 — 이 달은 화면이 빈다: {label}"
        )


def test_verifier_accepts_negative_remaining():
    """예산 초과(잔액 음수) — 2026-08-05 대시보드 회귀와 한 쌍. 이 화면에선 정상 상태다.

    잔액 절댓값(37,000원)이 다른 허용 금액과 겹치지 않게 뒀다 — 겹치면 마이너스를
    떼어낸 토큰이 우연히 허용 목록에 들어 결함이 있어도 통과해버린다.
    """
    fig = _figures(total_budget=100_000, spent=137_000)
    assert fig.remaining == -37_000, "이 케이스는 잔액이 음수여야 의미가 있다"
    assert "37,000원" not in bp.allowed_money(fig), "판별력을 위해 절댓값이 겹치면 안 된다"
    assert bp.verify_budget_message_pure(bp._mock_budget_message(fig), fig)


def test_verifier_rejects_invented_negative_money():
    fig = _figures(total_budget=100_000, spent=137_000)
    msg = _msg(fig, budget_status_analysis="남은 예산은 -12,345원입니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_allowed_money_excludes_zero_when_balance_remains():
    """'0원'을 무조건 열면 '잔액 18만인데 남은 예산은 0원'을 못 막는다."""
    assert "0원" not in bp.allowed_money(_figures())


def test_allowed_money_opens_zero_only_for_figures_that_are_zero():
    # 잔액 0 / 지출 0 / 기간 말 예상 0 — 문장이 0을 말할 수밖에 없는 세 머릿값
    assert "0원" in bp.allowed_money(_figures(total_budget=118_000, spent=118_000))
    assert "0원" in bp.allowed_money(_figures(spent=0))


def test_verifier_rejects_unknown_money():
    fig = _figures()
    msg = _msg(fig, recommendation="999,999원을 아낄 수 있습니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_allowed_percent_accepts_half_up_rounding():
    """round()는 half-even이라 22.5→22를 준다 — 2026-08-06 적대적 리뷰 발견.

    프롬프트는 "반올림해 정수로"라고 지시하는데 사람·LLM의 반올림은 half-up(22.5→23)이다.
    정수부가 짝수인 .5 케이스마다 지시를 정확히 따른 출력이 폐기되던 자리다.
    """
    # 지출 100,000 중 한 카테고리 22,500 → share 22.5%
    exp = [{"category": "교육", "amount": 22_500}, {"category": "식비", "amount": 77_500}]
    fig = _figures(expenses=exp)
    assert fig.categories[1].share == pytest.approx(0.225), "이 케이스는 share가 22.5%여야 한다"
    allowed = bp.allowed_percent(fig)
    assert "23%" in allowed, "half-up(23%)이 허용돼야 한다"
    assert "22%" in allowed, "half-even(22%)도 그대로 허용한다"


def test_verifier_rejects_unknown_percent():
    fig = _figures()
    msg = _msg(fig, category_analysis="'식비' 비중이 87%입니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_verifier_rejects_uncheckable_notation():
    """범위·한글 수사 표기는 어느 집계값과도 대조할 수 없어 원천 차단한다.

    Figma 시안 문구가 '15~20%'·'8~10만 원' 형태였다. 특히 '3만5천원'은 콤마 원화
    정규식을 통째로 빠져나가 환각 금액이 무검증 통과하던 구멍이다.
    """
    fig = _figures()
    for text in (
        "남은 예산의 15~20%는 예비비로 두세요.",
        "약 8~10만 원을 아낄 수 있습니다.",
        "약 3만5천원을 아낄 수 있습니다.",
        "10만원 정도 여유가 있습니다.",
    ):
        msg = _msg(fig, recommendation=text)
        assert not bp.verify_budget_message_pure(msg, fig), f"검증 불가 표기를 놓쳤다: {text}"


def test_verifier_rejects_period_end_cited_as_depletion():
    """소진 예상이 없는 달에 기간 말일을 소진일로 인용하는 것을 막는다.

    as_of·period_end까지 허용 날짜에 넣으면 잔액이 넉넉한데 '곧 바닥난다'고 말해도
    통과한다 — 대시보드의 '잔액 있는데 다 썼다'와 같은 종류의 오도다.
    """
    fig = _figures()
    assert fig.forecast.depletion_date is None, "이 케이스는 소진 예상이 없어야 의미가 있다"
    for date_str in (PERIOD_END, AS_OF, "2026-09-01"):
        msg = _msg(
            fig, budget_status_analysis=f"남은 예산은 182,000원이고 {date_str}에 소진됩니다."
        )
        assert not bp.verify_budget_message_pure(msg, fig), f"허위 소진일을 놓쳤다: {date_str}"


def test_verifier_rejects_invented_category():
    """숫자만 대조하면 없는 카테고리를 지어내도 통과한다 — 교체 전 검증기보다 후퇴하지 않게."""
    fig = _figures()
    msg = _msg(fig, category_analysis="'광고비' 비중이 가장 높습니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_verifier_rejects_overstatement_when_balance_remains():
    fig = _figures()  # 잔액 182,000원
    msg = _msg(fig, budget_status_analysis="남은 예산은 182,000원입니다. 예산을 모두 사용했습니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_verifier_allows_overstatement_when_budget_exceeded():
    """잔액이 음수면 '다 썼다'는 과장이 아니라 사실이다 — 사실 보고까지 폴백으로 밀지 않는다."""
    fig = _figures(total_budget=100_000, spent=137_000)
    msg = _msg(fig, budget_status_analysis="예산을 전부 사용했고 남은 예산은 -37,000원입니다.")
    assert bp.verify_budget_message_pure(msg, fig)


def test_overstate_check_is_per_block_not_joined():
    """3블록을 이어 붙이면 앞 블록 종결어미 '…다'와 다음 블록 '소진…'이 '다 소진'으로 읽힌다.

    단일 message인 대시보드에는 없던, 블록 분할이 새로 만드는 오탐이다.
    """
    fig = _figures()
    msg = _msg(
        fig,
        category_analysis="'비품' 비중이 가장 큽니다",
        budget_status_analysis="남은 예산은 182,000원입니다",
        recommendation="소진 속도는 완만합니다",
    )
    assert bp.verify_budget_message_pure(msg, fig), "블록 경계가 만든 가짜 과장에 걸렸다"


def test_verifier_requires_remaining_in_status_block():
    """화이트리스트는 '없는 숫자'만 막고 '있어야 할 숫자'는 요구하지 않아, 수치 0개짜리
    공허한 3블록이 통과한다. 교체 전 verify_proposal_pure가 강제하던 방어를 되살린다."""
    fig = _figures()
    msg = _msg(fig, budget_status_analysis="예산은 넉넉한 편입니다.")
    assert not bp.verify_budget_message_pure(msg, fig)


def test_verifier_rejects_wrong_remaining_hidden_inside_larger_amount():
    """잔액 필수 언급을 부분문자열로 보면 검사가 거꾸로 뚫린다 — 2026-08-06 적대적 리뷰 발견.

    `"0원" in "300,000원"`이 참이라서, 예산을 딱 맞춰 쓴 팀(잔액 0)에
    "남은 예산은 300,000원입니다"가 verified=true로 저장됐다. 잔액을 말하라는 검사가
    오히려 잔액을 틀리게 말해도 되는 통로가 된 셈이다. 토큰 단위로 봐야 한다.
    """
    fig = _figures(total_budget=118_000, spent=118_000)
    assert fig.remaining == 0, "이 케이스는 잔액이 정확히 0이어야 의미가 있다"
    assert "300,000원" not in bp.allowed_money(fig), "허용 목록 밖 금액이어야 판별력이 있다"
    msg = _msg(fig, budget_status_analysis="예산은 여유롭습니다. 남은 예산은 118,000원입니다.")
    assert not bp.verify_budget_message_pure(msg, fig), (
        "'118,000원'은 허용 목록에 있지만 잔액(0원)이 아니므로 필수 언급을 만족하지 못한다"
    )


def test_verifier_rejects_empty_block():
    fig = _figures()
    for block in ("category_analysis", "budget_status_analysis", "recommendation"):
        assert not bp.verify_budget_message_pure(_msg(fig, **{block: "  "}), fig), (
            f"빈 블록을 놓쳤다: {block}"
        )


def test_mock_category_block_carries_no_total_figures():
    """총액 기준 수치는 예산 현황 블록에만 — 비중과 총액을 한 문장에 섞지 않는다 (B-2 ④)."""
    fig = _figures()
    cat = bp._mock_budget_message(fig).category_analysis
    for token in (
        f"{fig.forecast.total_budget:,}",
        f"{fig.forecast.spent:,}",
        f"{fig.remaining:,}",
    ):
        assert token not in cat


def test_period_bounds_current_month():
    assert _period_bounds(None, date(2026, 7, 19)) == ("2026-07-19", "2026-07-31")


def test_period_bounds_past_month_clamps_to_end():
    # 지난달 지정 → 기간 전체 경과로 간주 (as_of = 기간 말)
    assert _period_bounds("2026-06", date(2026, 7, 19)) == ("2026-06-30", "2026-06-30")


def test_period_bounds_future_month_clamps_to_start():
    assert _period_bounds("2026-08", date(2026, 7, 19)) == ("2026-08-01", "2026-08-31")


async def test_generate_proposal_mock_meta():
    out = await generate_proposal({"figures": _figures()})
    assert out["message"].category_analysis
    meta = out["llm_meta"]["budget_planner"]
    assert meta.mock is True
    assert meta.model == "gpt-4o-mini"  # models.yaml budget_planner 라우팅


def test_period_format_validation():
    # 유효값은 통과, 형식이 다르면 즉시 422 거부 (조기 검증 — 리뷰 발견)
    ProposalBudgetRequest(team_id=1, period="2026-06")
    ProposalBudgetRequest(team_id=1, period=None)
    # "0000-01"은 \d{4}를 통과하지만 date.fromisoformat이 뒤늦게 죽는다 —
    # 202로 수락된 뒤 워커가 3회 재시도 후 dead로 소진되는 경로다 (적대적 리뷰 발견).
    for bad in ("2026-6", "June", "2026-13", "2026/06", "0000-01"):
        with pytest.raises(ValidationError):
            ProposalBudgetRequest(team_id=1, period=bad)


# ── T4 그래프 (저장 정책·폴백) ──────────────────────────────────────

PAYLOAD_KEYS = {
    "category_analysis",
    "budget_status_analysis",
    "recommendation",
    "figures",
    "verified",
}


def _saver(calls, pid="pid-123"):
    async def fake_save_proposal(team_id, proposal_type, payload):
        calls.append((team_id, proposal_type, payload))
        return pid

    return fake_save_proposal


async def test_save_persists_even_when_not_verified(monkeypatch):
    """검증 실패해도 저장한다 — 예산관리 페이지는 열 때마다 3블록이 보여야 해서 미저장 = 화면 공백이다.

    종전 정책(verified일 때만 저장)은 관리자가 승인·거절하던 제안이라 맞았지만,
    3블록은 화면에 항상 뜨는 메시지다. 폴백 문장이 정의상 안전하므로 저장해도 된다.
    """
    calls = []
    monkeypatch.setattr(bp, "save_proposal", _saver(calls))
    fig = _figures()
    out = await bp.save(
        {
            "request": ProposalBudgetRequest(team_id=1),
            "figures": fig,
            "message": bp._mock_budget_message(fig),
            "verified": False,
        }
    )
    assert out["proposal_id"] == "pid-123"
    assert len(calls) == 1
    assert calls[0][2]["verified"] is False, "저장하되 대조 결과는 정직하게 남긴다"


async def test_save_payload_carries_three_blocks_and_figures(monkeypatch):
    calls = []
    monkeypatch.setattr(bp, "save_proposal", _saver(calls))
    fig = _figures()
    out = await bp.save(
        {
            "request": ProposalBudgetRequest(team_id=1),
            "figures": fig,
            "message": bp._mock_budget_message(fig),
            "verified": True,
        }
    )
    assert set(out["payload"]) == PAYLOAD_KEYS
    assert calls[0][0] == 1
    assert calls[0][1] == "budget"


async def test_graph_roundtrip_produces_verified_three_blocks(monkeypatch):
    """완료 기준 — 3블록이 verified=true로 왕복한다.

    period를 반드시 고정한다. 생략하면 오늘 날짜 기준이 되어 목 지출(전부 2026년 6월)이
    기간 밖으로 빠지고 테스트가 날짜에 의존한다.
    """
    calls = []
    monkeypatch.setattr(bp, "save_proposal", _saver(calls))
    final = await bp.budget_planner_graph.ainvoke(
        {"request": ProposalBudgetRequest(team_id=1, period="2026-06")}
    )
    assert final["verified"] is True
    assert final["proposal_id"] == "pid-123"
    assert set(final["payload"]) == PAYLOAD_KEYS
    assert calls[0][1] == "budget"


async def test_aggregate_counts_only_the_requested_period(monkeypatch):
    """카테고리 비중은 그 기간 지출로만 낸다 — 2026-08-06 적대적 리뷰 발견.

    get_expense_history는 기간 필터 없이 전 기간을 돌려준다. 걸러내지 않으면
    "이번 달 지출은 '행사_활동'(97%)에 가장 많이 쓰였습니다"가 사실은 몇 달치 누적을
    말하게 된다 — 숫자는 집계와 일치하니 verified=true로 통과해 더 나쁘다.
    forecast()의 over/under 카테고리도 같은 목록에서 나오므로 양쪽에 같은 것을 넘긴다.
    """
    history = [
        {"category": "행사_활동", "amount": 900_000, "date": "2026-05-10", "status": "APPROVED"},
        {"category": "식비", "amount": 30_000, "date": "2026-06-10", "status": "APPROVED"},
        {"category": "교육", "amount": 50_000, "date": "2026-07-05", "status": "APPROVED"},
        {"category": "교통", "amount": 7_000, "date": "2026-07-20", "status": "APPROVED"},
    ]

    async def fake_history(team_id, **filters):
        return history

    async def fake_budget(team_id):
        return {"total_budget": 300_000, "spent": 118_000}

    monkeypatch.setattr(bp, "get_expense_history", fake_history)
    monkeypatch.setattr(bp, "get_budget_status", fake_budget)

    req = ProposalBudgetRequest(team_id=1, period="2026-07")
    fetched = await bp.fetch({"request": req})
    out = await bp.aggregate({"request": req, **fetched})
    fig = out["figures"]

    assert fig.expenses_total == 57_000, "7월분 50,000 + 7,000만 세어야 한다"
    assert [c.category for c in fig.categories] == ["교육", "교통"]
    assert "행사_활동" not in fig.forecast.over_categories, (
        "5월 지출이 남아 있으면 forecast의 편중 판정까지 틀어진다"
    )


async def test_failed_verification_falls_back_to_safe_message_and_still_saves(monkeypatch):
    """검증 실패 시 안전 문장으로 교체하고 저장한다 — 2026-08-05 대시보드가 같은 이유로 바꾼 정책.

    숨기면 화면이 비고, 경고를 붙이면 멀쩡한 달에도 '확인 필요'가 달린다.
    """
    calls = []
    monkeypatch.setattr(bp, "save_proposal", _saver(calls, pid="pid-456"))
    bad = bp.BudgetMessage(
        category_analysis="'광고비' 비중이 가장 큽니다.",
        budget_status_analysis="지출은 999,999원입니다.",
        recommendation="약 3만5천원을 아낄 수 있습니다.",
    )

    async def fake_chat_structured(**kwargs):
        return bad, None

    monkeypatch.setattr(bp, "chat_structured", fake_chat_structured)
    final = await bp.budget_planner_graph.ainvoke(
        {"request": ProposalBudgetRequest(team_id=1, period="2026-06")}
    )
    assert final["verified"] is False, "폴백을 썼다고 verified를 올리면 필드가 의미를 잃는다"
    assert "999,999" not in str(final["payload"]), "환각 수치가 폴백으로 교체돼야 한다"
    assert "광고비" not in str(final["payload"])
    assert len(calls) == 1, "검증 실패해도 저장한다 — 미저장이면 화면이 빈다"
    assert bp.verify_budget_message_pure(final["message"], final["figures"]), (
        "폴백 문장 자체는 검증을 통과해야 한다"
    )
