"""라이터 골든셋 평가기 테스트 — expect 대조 규칙 + 목 이력 규약."""

from app.eval_writers import evaluate_expectations
from app.graphs.writers.report import HIGH_SHARE, LOW_SHARE, aggregate_pure
from app.tools.backend_client import get_expense_history

ACTUAL = {
    "verified": True,
    "rules_count": 6,
    "rules_text": "제1조 영수증 첨부\n안전장비 구입은 우선 인정한다.",
}


def test_equality_check_passes_and_fails():
    assert evaluate_expectations({"rules_count": 6}, ACTUAL) == []
    fails = evaluate_expectations({"rules_count": 5}, ACTUAL)
    assert len(fails) == 1 and "rules_count" in fails[0]


def test_contain_checks_text_field():
    assert evaluate_expectations({"rules_contain": ["안전장비"]}, ACTUAL) == []
    fails = evaluate_expectations({"rules_contain": ["홍보물"]}, ACTUAL)
    assert len(fails) == 1 and "홍보물" in fails[0]


def test_not_contain_flags_forbidden_substring():
    fails = evaluate_expectations({"rules_not_contain": ["안전장비"]}, ACTUAL)
    assert len(fails) == 1
    assert evaluate_expectations({"rules_not_contain": ["{placeholder}"]}, ACTUAL) == []


def test_missing_actual_key_is_a_failure():
    fails = evaluate_expectations({"top_category": "식비"}, ACTUAL)
    assert len(fails) == 1


# ── 실모드 대응 연산자 (2026-08-13) ───────────────────────
# 목 산출물의 문자열·개수를 그대로 못박으면 실 LLM에서 같은 뜻을 다르게 써서 전부
# 실패한다 — 실측에서 32건 중 8건이 그렇게 걸렸고 생성물은 전부 verified 통과였다.


def test_contain_any_passes_when_one_alternative_matches():
    """허용 표현 중 하나만 있으면 통과 — 패러프레이즈를 흡수한다."""
    assert evaluate_expectations(
        {"rules_contain_any": ["보호 장비", "안전장비", "안전 수칙"]}, ACTUAL) == []


def test_contain_any_fails_when_no_alternative_matches():
    """아무 표현이나 통과시키지 않는다 — 허용 목록은 못박혀 있다."""
    fails = evaluate_expectations({"rules_contain_any": ["홍보물", "서버"]}, ACTUAL)
    assert len(fails) == 1 and "홍보물" in fails[0]


def test_contain_any_nested_groups_need_one_match_each():
    """중첩 리스트는 그룹마다 하나씩 — 한 조항에 두 주제를 함께 요구할 때 쓴다."""
    ok = evaluate_expectations(
        {"rules_contain_any": [["안전장비", "보호 장비"], ["영수증", "증빙"]]}, ACTUAL)
    assert ok == []
    fails = evaluate_expectations(
        {"rules_contain_any": [["안전장비"], ["서버", "인프라"]]}, ACTUAL)
    assert len(fails) == 1 and "서버" in fails[0]  # 두 번째 그룹만 실패


def test_between_checks_inclusive_range():
    """조 수는 정확값이 아니라 범위가 요구사항이다 (목=고정 휴리스틱, 실=가변)."""
    assert evaluate_expectations({"rules_count_between": [5, 7]}, ACTUAL) == []
    assert evaluate_expectations({"rules_count_between": [6, 6]}, ACTUAL) == []  # 양끝 포함
    fails = evaluate_expectations({"rules_count_between": [7, 9]}, ACTUAL)
    assert len(fails) == 1 and "6" in fails[0]


def test_between_treats_missing_key_as_failure():
    """없는 키를 범위 검사로 조용히 통과시키면 그물에 구멍이 난다."""
    fails = evaluate_expectations({"categories_count_between": [1, 9]}, ACTUAL)
    assert len(fails) == 1


# ── 목 이력 규약 (골든셋 시나리오의 결정성 기반) ─────────


async def test_noexpense_team_returns_empty_history():
    assert await get_expense_history(9022) == []  # eval-writers-report-noexpense


# 2026-08-07: 이력이 팀마다 3~5개월치로 늘면서 "이력 전체 = 한 달"이라는 전제가 깨졌다.
# 아래 둘이 지키려던 것은 **골든 케이스가 쓰는 그 달**의 성질이므로 기간을 명시한다
# (period를 안 주면 전 기간이 합쳐져 다른 달의 지출이 비중·건수를 흔든다).


async def test_balanced_team_has_no_share_outliers():
    """rp-balanced가 쓰는 2026-06은 편중·저활용 어느 쪽도 아니어야 한다."""
    expenses = await get_expense_history(9023, period="2026-06")
    figures = aggregate_pure("2026-06", expenses)
    assert figures.by_category
    for cat in figures.by_category:
        assert LOW_SHARE < cat.share < HIGH_SHARE


async def test_default_team_history_unchanged():
    """rp-standard가 의존하는 2026-06 슬라이스는 8건 399,000원 그대로여야 한다."""
    expenses = await get_expense_history(9021, period="2026-06")
    assert len(expenses) == 8
    assert sum(e["amount"] for e in expenses) == 399_000


def test_every_team_has_at_least_three_months():
    """시연에서 달을 바꾸면 숫자가 달라져야 한다 — 팀마다 3개월 이상을 보장한다.

    2026-08-07까지 14개 팀이 `default` 하나(2026-06 한 달)를 공유해, 팀을 바꾸든
    달을 바꾸든 리포트 숫자가 같았다. 9022만 예외다 — rp-empty가 '지출 없는 기간'을
    보려고 일부러 비워 둔 팀이다.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    fx = json.loads((root / "eval/fixtures/mock_backend.json").read_text(encoding="utf-8"))
    hist = fx["expense_histories"]
    thin = {
        team: sorted({r["date"][:7] for r in hist[org["expense_history"]]})
        for team, org in fx["organizations"].items()
        if int(team) != 9022
        and len({r["date"][:7] for r in hist[org["expense_history"]]}) < 3
    }
    assert not thin, f"3개월 미만인 팀: {thin}"
