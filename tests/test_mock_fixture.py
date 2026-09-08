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
GOLDEN_V2_DIR = ROOT / "eval/golden/golden_v2"
GOLDEN_V2_FILES = sorted(GOLDEN_V2_DIR.glob("*.json")) if GOLDEN_V2_DIR.is_dir() else []

# v1 + v2(있으면 전 유형 파일) 케이스를 합쳐 검사한다 — 유형 파일을 새로 추가할 때마다
# 이 테스트만 돌려도 계약 위반을 즉시 잡을 수 있게 하기 위해서다(golden_v2 생성 작업 지시).
ALL_CASES = list(GOLDEN["cases"])
for _path in GOLDEN_V2_FILES:
    ALL_CASES += json.loads(_path.read_text(encoding="utf-8"))["cases"]

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


def test_expenses_carry_no_category():
    """심사 전 지출에는 카테고리가 없다 — 백엔드 계약(BE-001 등록 시 null)과 같은 모양.

    2026-08-06까지는 fixture가 category를 실어 보냈는데, T7 이후 classify_category가
    **어떤 값이 와도 AI 분류로 덮으므로** 그 값은 판정에 쓰이지 않으면서 대조 경고만
    찍었다(eval 1회에 14건). 사람이 매긴 정답은 골든셋의 expected_category로 옮겼다.
    """
    with_category = {
        eid: e["category"] for eid, e in FIXTURE["expenses"].items() if e.get("category")
    }
    assert not with_category, (
        f"expenses에 category가 남아 있다 — 기대값은 골든셋 expected_category로: {with_category}"
    )


def test_every_golden_case_has_expected_category():
    """분류 채점의 분모 — 기대값이 빠진 케이스는 조용히 채점에서 빠진다."""
    missing = [c["id"] for c in ALL_CASES if not c.get("expected_category")]
    assert not missing, missing


def test_expected_categories_are_canonical():
    """기대값이 카탈로그 밖이면 영원히 못 맞히는 케이스가 된다 — 채점이 무의미해진다."""
    bad = {
        c["id"]: c["expected_category"]
        for c in ALL_CASES
        if c["expected_category"] not in VALID_CATEGORIES
    }
    assert not bad, bad


def test_every_catalog_category_appears_as_an_answer():
    """9종 **전부**가 골든셋에 정답으로 최소 1건 있어야 한다.

    정답으로 한 번도 안 나오는 카테고리는 분류기가 그쪽으로 보내도 맞았는지 틀렸는지
    판정할 수 없다 — 채점표에 없는 과목이 된다. 2026-08-06까지 `IT_인프라`·`회의`·
    `기타` 3종이 그 상태였고(68건 중 0건), 커버리지 케이스 4건을 추가해 메웠다.
    특히 `기타`는 "모르면 억지로 8종에 밀어 넣지 않는다"는 T7의 핵심 설계라
    검증 없이 두면 안 된다.
    """
    answered = {c["expected_category"] for c in ALL_CASES}
    missing = [cat for cat in all_categories() if cat not in answered]
    assert not missing, f"골든셋에 정답으로 한 번도 없는 카테고리: {missing}"


def test_golden_case_ids_resolve_in_fixture():
    """골든셋 전 케이스의 expenseId·organizationId가 전부 fixture에 등재돼 있어야 한다.

    fixture 미등재 ID는 (의도적으로) 조용히 기본값으로 폴백하므로, 오타 하나가
    verdict를 못 바꾸는 대신 "왜 기대값이 안 맞지"로 조용히 새는 실패를 만든다 —
    여기서 먼저 잡는다.
    """
    orgs = FIXTURE["organizations"]
    expenses = FIXTURE["expenses"]
    missing = []
    for case in ALL_CASES:
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


def test_golden_receipt_paths_are_posix_and_exist():
    """`file://` 영수증 경로는 POSIX 슬래시여야 하고 파일이 실재해야 한다.

    scripts/generate_golden_receipts.py를 **윈도우에서 돌리면** `relative_to`가
    역슬래시 경로를 주고(`eval\\golden\\receipts\\x.png`), 그대로 골든셋에 박히면
    CI(우분투)·macOS의 실모드 평가가 파일을 못 연다. 목 모드는 파일을 열지 않아
    통과해버리므로 **실모드에서만 터지는 조용한 실패**가 된다 — 2026-08-06에 실제로
    밟았고, 스크립트를 as_posix()로 고치면서 이 그물을 함께 놓는다.
    """
    bad_sep, missing = [], []
    for case in ALL_CASES:
        path = case["input"].get("receiptPath") or ""
        if not path.startswith("file://"):
            continue  # mock://receipt(불일치 시나리오)·미첨부는 대상 아님
        rel = path[len("file://") :]
        if "\\" in rel:
            bad_sep.append((case["id"], rel))
        elif not (ROOT / rel).exists():
            missing.append((case["id"], rel))
    assert not bad_sep, f"역슬래시 경로(윈도우에서 생성됨): {bad_sep}"
    assert not missing, f"영수증 파일 없음: {missing}"


def test_no_query_string_leftovers_in_golden_ids():
    """골든셋 치환 후 옛 규약(? 쿼리)이 하나라도 남아 있으면 여기서 잡는다."""
    for case in ALL_CASES:
        assert "?" not in str(case["input"]["expenseId"]), case["id"]
        assert not parse_qs(str(case["input"]["organizationId"])), case["id"]
