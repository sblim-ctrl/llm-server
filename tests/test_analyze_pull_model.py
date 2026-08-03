"""/v1/analyze pull 모델 계약 테스트 (bravo 설계서 TABLE 18).

- AnalyzeRequest: 백엔드 camelCase 5필드 수용 (+내부 snake_case 호환)
- get_expense_detail 목 규약: expense_id의 ?쿼리로 지출 상세 오버라이드
- load_context: claim pull 채움 / 직접 주입 시 조회 생략 / team_settings 실패 시
  auto_approve=False fail-safe
- team_settings·budget 응답 필드 계약 (풀스택 DB 스키마 2026-07-27 수령분)
"""

from unittest.mock import patch

from app.graphs.review.nodes.load_context import load_context
from app.schemas.analyze import AnalyzeRequest
from app.schemas.common import ExpenseClaim
from app.tools.backend_client import get_budget_status, get_expense_detail, get_team_settings


def test_analyze_request_accepts_camel_case():
    req = AnalyzeRequest.model_validate(
        {
            "jobId": "be-1",
            "expenseId": 101,
            "organizationId": 11,
            "reviewGoal": "심사하라",
            "receiptPath": "/api/internal/receipts/1",
        }
    )
    assert req.job_id == "be-1"
    assert req.expense_id == 101
    assert req.organization_id == 11
    assert req.receipt_path == "/api/internal/receipts/1"


def test_analyze_request_accepts_snake_case_too():
    """populate_by_name — 내부 도구·테스트의 snake_case 호출 호환."""
    req = AnalyzeRequest(job_id="be-2", expense_id=102, organization_id=12)
    assert req.review_goal == ""  # 선택 필드 기본값
    assert req.receipt_path is None


def test_analyze_request_rejects_string_entity_ids():
    """백엔드 BIGINT 계약 — 숫자처럼 보이는 문자열도 허용하지 않는다."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(
            {"jobId": "be-3", "expenseId": "103", "organizationId": "13"}
        )


def test_analyze_request_rejects_old_push_contract():
    """구 push 계약(claim 인라인)은 jobId 등 필수 필드가 없어 수락되지 않아야 한다."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(
            {
                "expense_id": 101,
                "team_id": 11,
                "claim": {"title": "교재", "amount": 32000, "date": "2026-07-01"},
            }
        )


async def test_expense_detail_mock_query_override():
    detail = await get_expense_detail(
        "org-1",
        "exp-1?title=스터디 교재&amount=32000&category=도서"
        "&date=2026-07-01&description=설명%3D테스트",
    )
    assert detail["title"] == "스터디 교재"
    assert detail["amount"] == 32000
    assert detail["category"] == "도서"
    assert detail["description"] == "설명=테스트"  # 최소 이스케이프(%3D) 복원


async def test_expense_detail_mock_default_without_query():
    detail = await get_expense_detail("org-1", "exp-plain")
    assert detail["amount"] == 30_000 and detail["title"]


async def test_team_settings_mock_noauto_convention():
    assert (await get_team_settings("org-noauto-1"))["auto_approve"] is False
    assert (await get_team_settings("org-normal"))["auto_approve"] is True


async def test_load_context_pulls_claim():
    state = {
        "team_id": "org-1",
        "expense_id": "exp-1?title=회식&amount=45000&category=식비&date=2026-07-02",
    }
    updates = await load_context(state)
    claim = updates["claim"]
    assert claim.title == "회식" and claim.amount == 45000
    assert updates["policy_params"].auto_approve is True


async def test_load_context_skips_pull_when_claim_given():
    """직접 그래프 호출(smoke·seed_demo·단위테스트) — 주입된 claim을 덮지 않는다."""
    given = ExpenseClaim(title="직접 주입", amount=1000, date="2026-07-01")
    updates = await load_context(
        {"team_id": "org-1", "expense_id": "exp-1?title=다른값&amount=99999", "claim": given}
    )
    assert "claim" not in updates


async def test_load_context_fail_safe_on_settings_error():
    """team_settings 조회 실패 → auto_approve=False (자동판정 권한 미확인이면 판정 금지)."""
    with patch(
        "app.graphs.review.nodes.load_context.get_team_settings",
        side_effect=RuntimeError("backend down"),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1"})
    assert updates["policy_params"].auto_approve is False


