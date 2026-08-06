"""BudgetPlanner — 예산관리 페이지 AI 메시지 그래프 (LLM-016, §4.4-d).

수집 → 결정적 집계(코드 계산) → 생성(LLM은 문장만) → 검증(수치 대조) → 저장.
수치는 build_budget_figures가 계산하고 LLM은 figures 해석·패턴 진단·권고 문장만 쓴다.

산출은 Figma 확정 3블록(category_analysis·budget_status_analysis·recommendation)이다.
검증에 실패하면 폐기하지 않고 집계 기반 안전 문장으로 교체한다 — 이 화면은 열 때마다
3블록이 보여야 해서 미저장·미표시가 곧 화면 공백이기 때문이다. verified 플래그는
대조 통과 여부를 정직하게 남긴다.
"""

import calendar
import logging
import re
from datetime import date

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

# 금액·과장 표현 그물은 dashboard와 **같은 상수를 쓴다** — writer마다 복사해 두면 한쪽만
# 고쳐지는 사고가 난다(2026-08-05에 _MONEY_RE가 정확히 그래서 dashboard·digest 양쪽 다
# 결함이었다). _OVERSTATE_RE는 지금도 오탐 수정이 진행 중이라 특히 그렇다.
from app.graphs.writers.dashboard import _MONEY_RE, _OVERSTATE_RE, _PERCENT_RE
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta
from app.schemas.proposals import ProposalBudgetRequest
from app.tools.backend_client import get_budget_status, get_expense_history
from app.tools.burn_rate_forecast import BurnForecast, forecast
from app.tools.proposal_store import save_proposal

logger = logging.getLogger(__name__)

SMALL_EXPENSE_MAX = 20_000  # '반복 소액 지출' 기준 상한 (원)
RESERVE_RATIO = 0.15  # 예비비 권고 비율 — Figma의 '15~20%' 범위를 하한 단일값으로 고정
SAVINGS_RATIO = 0.5  # 소액 지출 절감 가정 (절반으로 줄였을 때 확보액)


class ProposalText(BaseModel):
    """프롬프트 v1·v2의 output_schema 이력 — **삭제 금지**.

    v3부터 산출은 BudgetMessage(3블록)로 바뀌었지만, prompts/budget_planner/v1·v2.yaml이
    여전히 `output_schema: ProposalText`이고 tests/test_prompt_fewshot_contract.py가
    모듈 최상위에서 이 이름을 import한다 — 지우면 계약 테스트가 수집 단계에서 통째로 죽는다.
    """

    adjustments: list[str]  # 카테고리 재배분·한도 권고 문장
    rationale: str  # 총액 기준 근거 문장


class CategoryShare(BaseModel):
    category: str
    spent: int  # 해당 카테고리 승인 지출 합 (expenses 기준)
    share: float  # spent / expenses_total


class BudgetFigures(BaseModel):
    """3블록 메시지의 결정적 재료 — 검증기 허용 목록의 유일한 원천.

    BurnForecast는 C8 계약 그대로 내장한다 (필드를 늘리면 Digest가 깨진다).
    총액 기준 수치(forecast.spent)와 지출 내역 합계(expenses_total)는 출처가 달라
    일치하지 않을 수 있다 — burn_rate_forecast의 B-2 ④ 규칙대로 한 문장에 섞지 않는다.
    """

    forecast: BurnForecast
    as_of: str
    period_end: str
    remaining: int  # total_budget - spent (음수 가능 — 예산 초과가 정상인 화면)
    usage_ratio: float
    projected_usage_ratio: float
    projected_overrun: int  # max(0, 기간 말 예상 지출 - 총예산)
    daily_burn: int  # forecast.daily_burn 반올림 — 원화 표기와 자릿수를 맞춘다
    expenses_total: int
    categories: list[CategoryShare]  # 지출 큰 순
    small_expense_max: int
    small_expense_total: int
    small_expense_count: int
    small_expense_share: float
    small_expense_categories: list[str]  # 소액 합 큰 순
    reserve_ratio: float  # 상수지만 figures에 실어 인용 출처를 강제한다
    reserve_amount: int
    savings_potential: int


def build_budget_figures(
    f: BurnForecast, expenses: list[dict], as_of: str, period_end: str
) -> BudgetFigures:
    """순수 집계 — expenses는 호출부가 이미 APPROVED로 필터한 목록을 넘긴다."""
    expenses_total = sum(e["amount"] for e in expenses)
    by_cat: dict[str, int] = {}
    small_by_cat: dict[str, int] = {}
    small_total = small_count = 0
    for e in expenses:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
        if e["amount"] <= SMALL_EXPENSE_MAX:
            small_total += e["amount"]
            small_count += 1
            small_by_cat[e["category"]] = small_by_cat.get(e["category"], 0) + e["amount"]

    remaining = f.total_budget - f.spent
    return BudgetFigures(
        forecast=f,
        as_of=as_of,
        period_end=period_end,
        remaining=remaining,
        usage_ratio=(f.spent / f.total_budget) if f.total_budget else 0.0,
        projected_usage_ratio=(
            (f.projected_period_end_spent / f.total_budget) if f.total_budget else 0.0
        ),
        projected_overrun=max(0, f.projected_period_end_spent - f.total_budget),
        daily_burn=round(f.daily_burn),
        expenses_total=expenses_total,
        categories=[
            CategoryShare(
                category=c, spent=v, share=(v / expenses_total) if expenses_total else 0.0
            )
            for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
        ],
        small_expense_max=SMALL_EXPENSE_MAX,
        small_expense_total=small_total,
        small_expense_count=small_count,
        small_expense_share=(small_total / expenses_total) if expenses_total else 0.0,
        small_expense_categories=[
            c for c, _ in sorted(small_by_cat.items(), key=lambda kv: -kv[1])
        ],
        reserve_ratio=RESERVE_RATIO,
        reserve_amount=round(remaining * RESERVE_RATIO) if remaining > 0 else 0,
        savings_potential=round(small_total * SAVINGS_RATIO),
    )


class BudgetMessage(BaseModel):
    """LLM 산출은 문장만 — 수치는 코드(BudgetFigures)가 계산한다. Figma 확정 3블록."""

    category_analysis: str  # 카테고리별 분석
    budget_status_analysis: str  # 예산 현황 분석
    recommendation: str  # AI 추천


# ── 3블록 검증 (순수 함수) ────────────────────────────────────────────────

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 어느 집계값과도 대조할 수 없는 표기를 원천 차단한다. Figma 시안 문구가 '15~20%'·
# '8~10만 원' 형태였는데, 범위는 검증할 수 없고 한글 수사('3만5천원')는 콤마 원화를
# 잡는 _MONEY_RE를 통째로 빠져나가 환각 금액이 무검증 통과한다.
_RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*[~〜]\s*\d+")  # 하이픈은 날짜 오탐이라 제외
_KOR_NUM_RE = re.compile(r"\d\s*[만천억]")
_QUOTED_RE = re.compile(r"'([^']+)'")  # 카테고리명 인용 규약 — 프롬프트가 강제한다


def allowed_money(fig: BudgetFigures) -> set[str]:
    """본문에 나와도 되는 금액 표기. 집계값에서만 유도한다."""
    f = fig.forecast
    values = {
        f.total_budget,
        f.spent,
        f.projected_period_end_spent,
        fig.remaining,
        fig.projected_overrun,
        fig.daily_burn,
        fig.small_expense_max,
        fig.small_expense_total,
        fig.reserve_amount,
        fig.savings_potential,
    }
    values |= {c.spent for c in fig.categories}
    # expenses_total은 일부러 넣지 않는다 — 총액 기준 spent와 출처가 달라(B-2 ④),
    # 허용하면 LLM이 둘을 한 문장에 섞어 써도 검증기가 통과시킨다.
    allowed = {f"{v:,}원" for v in values if v}
    # 0은 기본적으로 넣지 않는다 — '0원'은 어느 문장에나 자연스럽게 붙어서, 허용하면
    # "잔액이 18만인데 남은 예산은 0원"을 못 막는다(dashboard와 같은 가드). 다만 문장이
    # 0을 말할 수밖에 없는 머릿값 셋은 열어준다 — 지출이 아직 없는 신규 팀·월초가 가장
    # 흔한 첫 화면인데, 안 열면 폴백 문장까지 폐기되어 화면이 통째로 빈다.
    if 0 in (fig.remaining, f.spent, f.projected_period_end_spent):
        allowed.add("0원")
    return allowed


def allowed_percent(fig: BudgetFigures) -> set[str]:
    """본문에 나와도 되는 백분율. 반올림 자리수가 갈리므로 이웃값까지 허용한다."""
    out: set[str] = set()

    def add(ratio: float) -> None:
        pct = abs(ratio) * 100
        # dashboard는 `{v:g}`로 적지만 여기선 쓰지 않는다 — :g는 100만 이상을 지수 표기
        # ('1.18e+07')로 바꿔서, 예산을 아주 작게 잡은 팀의 사용률이 본문 표기와 어긋나
        # 폴백까지 폐기된다. round()가 이미 정수를 주므로 :g의 이득도 없다.
        #
        # int(pct + 0.5)는 half-up 반올림이다. round()는 half-even이라 22.5%를 22로
        # 주는데, 프롬프트는 "반올림해 정수로"라고 지시하고 사람·LLM의 반올림은
        # half-up(23)이라 정수부가 짝수인 .5 케이스마다 **지시를 정확히 따른 출력이**
        # 폐기된다. pct는 abs()라 항상 0 이상이므로 math.floor 없이 이 식이면 된다.
        for v in {round(pct), int(pct), round(pct, 1), int(pct + 0.5)}:
            out.add(f"{v}%")

    add(fig.usage_ratio)
    add(fig.projected_usage_ratio)
    add(fig.small_expense_share)
    add(fig.reserve_ratio)
    for c in fig.categories:
        add(c.share)
    return out


def _allowed_dates(fig: BudgetFigures) -> set[str]:
    """소진 예상일만 허용한다.

    as_of·period_end까지 열면, 소진 예상이 없는 달에 LLM이 기간 말일을 소진일로 인용해도
    통과한다("2026-06-30에 예산이 소진됩니다"). 잔액이 넉넉한데 곧 바닥난다고 말하는
    셈이라 대시보드의 '잔액 있는데 다 썼다'와 같은 종류의 오도다. 이미 소진된 달은
    forecast가 depletion_date에 as_of를 넣으므로 그 경로로 자동 허용된다.
    """
    return {fig.forecast.depletion_date} if fig.forecast.depletion_date else set()


def verify_budget_message_pure(msg: BudgetMessage, fig: BudgetFigures) -> bool:
    """3블록의 수치·카테고리가 집계에서 나온 것인지 대조한다.

    문장 자체는 강제하지 않는다 — 해석·패턴 진단·권고는 실모드 LLM이 자유롭게 쓰는
    영역이고, 거기가 이 화면의 값어치다. 다만 **숫자와 카테고리명은 예외**다. 관리자가
    예산 판단을 하는 화면이라 없는 금액이 적히면 잘못된 결정으로 이어진다.
    """
    blocks = [msg.category_analysis, msg.budget_status_analysis, msg.recommendation]
    if any(not b.strip() for b in blocks):
        return False
    body = " ".join(blocks)

    if _RANGE_RE.search(body) or _KOR_NUM_RE.search(body):
        return False
    if any(tok not in allowed_money(fig) for tok in _MONEY_RE.findall(body)):
        return False
    if any(tok not in allowed_percent(fig) for tok in _PERCENT_RE.findall(body)):
        return False
    if any(tok not in _allowed_dates(fig) for tok in _DATE_RE.findall(body)):
        return False
    # 없는 카테고리를 지어내는 것도 막는다. 숫자만 대조하면 "'광고비' 비중이 높습니다"가
    # 그냥 통과하는데, 교체 전 verify_proposal_pure는 over/under 카테고리 언급을 강제하고
    # 있었으므로 그대로 두면 방어력이 순수하게 후퇴한다.
    known = {c.category for c in fig.categories}
    if any(q not in known for q in _QUOTED_RE.findall(body)):
        return False
    # 잔액이 남았는데 "다 썼다"고 하는 과장. **블록별로** 본다 — 이어 붙이면 앞 블록의
    # 종결어미 '…다'와 다음 블록의 '소진…'이 붙어 '다 소진'으로 읽힌다(단일 message인
    # 대시보드에는 없던, 블록 분할이 새로 만드는 오탐). 잔액이 음수면 '다 썼다'는 과장이
    # 아니라 사실이므로 `> 0`으로 본다.
    if fig.remaining > 0 and any(_OVERSTATE_RE.search(b) for b in blocks):
        return False
    # 화이트리스트는 '없는 숫자'만 막고 '있어야 할 숫자'는 요구하지 않아서, 수치가 하나도
    # 없는 공허한 3블록이 통과한다. 예산 현황 블록은 잔액을 반드시 말하게 한다 — 필수
    # 항목을 늘릴수록 폐기율이 오르므로 가장 중요한 하나로 시작한다.
    #
    # 부분문자열이 아니라 **토큰 단위로** 본다. `"0원" in "300,000원"`이 참이라서, 예산을
    # 딱 맞춰 쓴 팀(잔액 0)에 "남은 예산은 300,000원입니다"가 그대로 통과했다.
    # 잔액을 말하라는 검사가 오히려 잔액을 틀리게 말해도 되는 통로가 됐던 자리다.
    return f"{fig.remaining:,}원" in _MONEY_RE.findall(msg.budget_status_analysis)


def _mock_budget_message(fig: BudgetFigures) -> BudgetMessage:
    """목 모드 결정적 문구 겸 **검증 실패 시 폴백 문장**.

    집계값만으로 조립하므로 정의상 검증을 통과한다 — 이 불변식이 깨지면 그 달에는
    화면에 띄울 문장이 아예 없어진다(tests가 시나리오 전수로 못 박는다).
    실모드 문장과 같은 수치를 쓰도록 맞춰 둔다.
    """
    f = fig.forecast

    # ① 카테고리별 분석 — 비중만. 총액 기준 수치는 섞지 않는다 (B-2 ④).
    if not fig.categories:
        cat = "아직 승인된 지출이 없어 카테고리별 분석을 드리기 어렵습니다. 지출이 쌓이면 알려드릴게요."
    else:
        top = fig.categories[0]
        cat = (
            f"이번 달 지출은 '{top.category}'({abs(top.share) * 100:.0f}%)에 가장 많이 쓰였습니다."
        )
        if len(fig.categories) > 1:
            nxt = fig.categories[1]
            cat += f" 그 다음은 '{nxt.category}'({abs(nxt.share) * 100:.0f}%)입니다."
        if f.over_categories:
            cat += f" '{f.over_categories[0]}'는 비중이 높은 편이라 회당 상한을 정해두면 관리가 쉬워집니다."
        if f.under_categories:
            cat += f" '{f.under_categories[0]}'는 여유가 있어 지금 수준을 유지해도 좋겠습니다."

    # ② 예산 현황 분석 — 총액 기준만. 잔액은 반드시 말한다(검증기 필수 항목).
    status = (
        f"현재 예산 사용률은 {abs(fig.usage_ratio) * 100:.0f}%이고 "
        f"남은 예산은 {fig.remaining:,}원입니다."
    )
    # 지출이 극히 적으면 daily_burn이 0으로 반올림된다 — "하루 평균 0원씩"은 말이 안 되는
    # 문장이고, 허용 목록의 0원 가드에도 걸려 폴백째로 폐기된다.
    if fig.daily_burn > 0:
        status += f" 하루 평균 {fig.daily_burn:,}원씩 쓰고 있습니다."
    status += f" 이 속도가 이어지면 기간 말 예상 지출은 {f.projected_period_end_spent:,}원입니다."
    if f.depletion_date:
        status += f" 이 속도라면 {f.depletion_date}쯤 잔액이 소진될 것으로 보입니다."
    if fig.projected_overrun > 0:
        status += f" 예상대로면 {fig.projected_overrun:,}원을 넘기게 됩니다."
    if fig.reserve_amount > 0:
        status += (
            f" 남은 예산의 {fig.reserve_ratio * 100:.0f}%인 {fig.reserve_amount:,}원 정도는 "
            f"예비비로 남겨두시길 권합니다."
        )

    # ③ AI 추천 — 소액 지출 지표만.
    if fig.small_expense_count > 0 and fig.savings_potential > 0:
        head = f"'{fig.small_expense_categories[0]}'처럼 " if fig.small_expense_categories else ""
        rec = (
            f"{head}건당 금액은 작지만 반복되는 지출이 {fig.small_expense_count}건으로 "
            f"전체 지출의 {abs(fig.small_expense_share) * 100:.0f}%를 차지합니다. "
            f"절반으로 줄이면 {fig.savings_potential:,}원을 다른 곳에 쓸 수 있습니다."
        )
    else:
        rec = "반복되는 소액 지출은 눈에 띄지 않습니다. 지금 지출 습관을 유지하셔도 좋겠습니다."

    return BudgetMessage(category_analysis=cat, budget_status_analysis=status, recommendation=rec)


class PlannerState(TypedDict, total=False):
    request: ProposalBudgetRequest
    budget: dict  # get_budget_status 결과 {total_budget, spent}
    expenses: list[dict]  # APPROVED만
    figures: BudgetFigures
    message: BudgetMessage
    verified: bool  # 본문 수치와 집계값의 대조 통과 여부 — 폴백을 썼어도 false로 남긴다
    proposal_id: str | None
    payload: dict
    llm_meta: dict[str, LLMCallMeta]  # 작성 노드가 하나뿐 — reducer 불요 (B-7 합산용)


def _period_bounds(period: str | None, today: date) -> tuple[str, str]:
    """(as_of, period_end) 계산 — 순수 함수 (단위 테스트 대상).

    period 미지정이면 today의 당월. 지난달 지정 시 as_of는 기간 말(전체 경과),
    미래 달 지정 시 기간 시작으로 클램프.
    """
    base = date.fromisoformat(f"{period}-01") if period else today.replace(day=1)
    end = base.replace(day=calendar.monthrange(base.year, base.month)[1])
    as_of = min(max(today, base), end)
    return as_of.isoformat(), end.isoformat()


async def fetch(state: PlannerState) -> dict:
    req = state["request"]
    budget = await get_budget_status(req.team_id)
    expenses = await get_expense_history(req.team_id)
    approved = [e for e in expenses if e.get("status") == "APPROVED"]
    return {"budget": budget, "expenses": approved}


async def aggregate(state: PlannerState) -> dict:
    # now()는 이 노드 한 곳에서만 주입 — _period_bounds()·forecast()·build_budget_figures()는 순수 유지
    as_of, period_end = _period_bounds(state["request"].period, date.today())
    b = state["budget"]
    # 카테고리 비중은 **그 기간의 지출**로만 낸다. get_expense_history는 기간 필터 없이
    # 전 기간을 돌려주므로, 안 걸러내면 "이번 달 지출은 …에 가장 많이 쓰였습니다"가 사실은
    # 몇 달치 누적을 말하게 된다 — 숫자가 집계와는 일치하니 verified=true로 통과해 더 나쁘다.
    # forecast()의 over/under 카테고리도 같은 목록에서 나오므로 양쪽에 같은 것을 넘긴다.
    # (dashboard.py:54·68이 쓰는 날짜 접두사 비교와 같은 방식. 백엔드에 period를 넘기지
    #  않는 이유는 기본값 None이 `?period=` 빈 문자열로 직렬화되기 때문이다.)
    month = period_end[:7]
    expenses = [e for e in state["expenses"] if str(e.get("date") or "").startswith(month)]
    f = forecast(b["total_budget"], b["spent"], expenses, as_of=as_of, period_end=period_end)
    return {"figures": build_budget_figures(f, expenses, as_of=as_of, period_end=period_end)}


async def generate_proposal(state: PlannerState) -> dict:
    fig = state["figures"]
    spec = load_prompt("budget_planner")
    result, meta = await chat_structured(
        agent="budget_planner",
        system=spec.system_with_few_shot(),
        user=fig.model_dump_json(),  # figures만 전달 — 수치 출처 강제
        schema=BudgetMessage,
        mock_response=_mock_budget_message(fig),
        prompt_version=spec.version,
    )
    return {"message": result, "llm_meta": {"budget_planner": meta}}


async def verify_proposal(state: PlannerState) -> dict:
    """검증 실패 시 **집계로 조립한 안전한 문장으로 교체**한다 (verified=false는 유지).

    종전에는 실패하면 저장 자체를 건너뛰었다. 관리자가 승인·거절하는 제안이던 시절에는
    맞는 정책이었지만, 3블록은 예산관리 페이지를 열 때 항상 보여야 하는 메시지라
    미저장 = 화면 공백이다(2026-08-05에 대시보드가 같은 이유로 폐기 정책을 버렸다).
    교체용 문장은 _mock_budget_message가 집계값만으로 만들어 정의상 검증을 통과한다.

    **verified는 정직하게 false로 남긴다.** 그 값의 뜻은 "본문 수치와 집계값의 대조
    통과 여부"다. 폴백을 썼다고 true로 올리면 필드가 의미를 잃고 AI 품질 저하가 영영
    안 보이게 된다. 대신 거부된 원문을 로그에 남겨 나중에 폐기율을 셀 수 있게 한다.
    """
    fig, msg = state["figures"], state["message"]
    if verify_budget_message_pure(msg, fig):
        return {"verified": True}

    logger.error(
        "budget 3블록 검증 실패 — 집계 기반 문장으로 교체(verified=false 유지). 거부된 원문: %r",
        msg.model_dump(),
    )
    safe = _mock_budget_message(fig)
    if not verify_budget_message_pure(safe, fig):
        # 폴백까지 실패하면 집계 자체가 이상한 것이다 — 조용히 넘기지 않는다.
        logger.critical("폴백 문장도 검증 실패 — 집계값 점검 필요: %r", safe.model_dump())
    return {"message": safe, "verified": False}


async def save(state: PlannerState) -> dict:
    fig, msg = state["figures"], state["message"]
    payload = {**msg.model_dump(), "figures": fig.model_dump(), "verified": state["verified"]}
    proposal_id = await save_proposal(state["request"].team_id, "budget", payload)
    return {"proposal_id": proposal_id, "payload": payload}


def build_budget_planner_graph():
    g = StateGraph(PlannerState)
    g.add_node("fetch", fetch)
    g.add_node("aggregate", aggregate)
    g.add_node("generate_proposal", generate_proposal)
    g.add_node("verify_proposal", verify_proposal)
    g.add_node("save", save)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "aggregate")
    g.add_edge("aggregate", "generate_proposal")
    g.add_edge("generate_proposal", "verify_proposal")
    g.add_edge("verify_proposal", "save")
    g.add_edge("save", END)
    return g.compile()


budget_planner_graph = build_budget_planner_graph()
