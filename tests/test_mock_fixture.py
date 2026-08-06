"""eval/fixtures/mock_backend.json 정합성 (T9) — golden_v1.json과의 참조 무결성 포함.

이 파일이 커버하는 것은 fixture 자체의 "모양"이다. 개별 조회 동작(get_budget_status
등)은 test_backend_client_shared.py·test_analyze_pull_model.py가 담당한다.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from app.tools.category_catalog import all_categories

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "eval/fixtures/mock_backend.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((ROOT / "eval/golden/golden_v1.json").read_text(encoding="utf-8"))

VALID_CATEGORIES = set(all_categories()) | {""}


def test_organization_ids_are_plain_positive_integers():
    """조직 키가 숫자 문자열이 아니면 str(team_id) 조회가 옛 문자열 규약처럼
    부분 일치로 오작동할 여지가 생긴다 — 키는 전부 순수 정수 문자열이어야 한다."""
    for key in FIXTURE["organizations"]:
        assert key.isdigit(), key


def test_expense_ids_are_plain_positive_integers():
    for key in FIXTURE["expenses"]:
        assert key.isdigit(), key


def test_organization_expense_history_references_exist():
    for oid, org in FIXTURE["organizations"].items():
        assert org["expense_history"] in FIXTURE["expense_histories"], (
            oid,
            org["expense_history"],
        )


def test_team_settings_shape_excludes_escalation_threshold():
    """map_team_settings의 force=limit 해석(app/tools/policy_params.py:44-49)이
    깨지지 않으려면 fixture가 escalation_threshold 키를 절대 갖지 않아야 한다."""
    for oid, org in FIXTURE["organizations"].items():
        assert set(org) >= {"auto_approve", "auto_approve_limit"}, oid
        assert "escalation_threshold" not in org, oid


@pytest.mark.parametrize("history_name", ["default", "none", "balanced"])
def test_expense_history_categories_are_canonical(history_name):
    for row in FIXTURE["expense_histories"][history_name]:
        assert row["category"] in VALID_CATEGORIES, row


def test_expense_categories_are_canonical_or_blank():
    for expense_id, expense in FIXTURE["expenses"].items():
        assert expense["category"] in VALID_CATEGORIES, (expense_id, expense["category"])


def test_autoclassify_cases_keep_blank_category():
    """분류기 경로를 태우는 골든 케이스 2건은 category가 비어 있어야 한다."""
    autoclassify_ids = {c["id"] for c in GOLDEN["cases"] if "autoclassify" in c["id"]}
    assert len(autoclassify_ids) == 2, autoclassify_ids
    for case in GOLDEN["cases"]:
        if case["id"] in autoclassify_ids:
            expense_id = str(case["input"]["expenseId"])
            assert FIXTURE["expenses"][expense_id]["category"] == ""


def test_golden_case_ids_resolve_in_fixture():
    """골든셋 68건의 expenseId·organizationId가 전부 fixture에 등재돼 있어야 한다.

    fixture 미등재 ID는 (의도적으로) 조용히 기본값으로 폴백하므로, 오타 하나가
    verdict를 못 바꾸는 대신 "왜 기대값이 안 맞지"로 조용히 새는 실패를 만든다 —
    여기서 먼저 잡는다.
    """
    orgs = FIXTURE["organizations"]
    expenses = FIXTURE["expenses"]
    missing = []
    for case in GOLDEN["cases"]:
        org_id = str(case["input"]["organizationId"])
        expense_id = str(case["input"]["expenseId"])
        if org_id not in orgs:
            missing.append(("organization", case["id"], org_id))
        if expense_id not in expenses:
            missing.append(("expense", case["id"], expense_id))
    assert not missing, missing


def test_golden_case_amounts_and_dates_survive_migration():
    """expenseId가 더 이상 쿼리스트링이 아니므로, fixture의 title/amount/date/
    description이 옛 쿼리값과 같은지 별도로 대조할 수 없다 — 대신 amount·date가
    사람이 읽는 값 범위(0 초과, YYYY-MM-DD)인지만 형태를 확인한다."""
    for expense in FIXTURE["expenses"].values():
        assert expense["amount"] > 0
        assert len(expense["date"]) == 10 and expense["date"].count("-") == 2


def test_no_query_string_leftovers_in_golden_ids():
    """골든셋 치환 후 옛 규약(? 쿼리)이 하나라도 남아 있으면 여기서 잡는다."""
    for case in GOLDEN["cases"]:
        assert "?" not in str(case["input"]["expenseId"]), case["id"]
        assert not parse_qs(str(case["input"]["organizationId"])), case["id"]
