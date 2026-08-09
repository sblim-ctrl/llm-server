"""/v1/analyze pull 모델 계약 테스트 (bravo 설계서 TABLE 18).

- AnalyzeRequest: 백엔드 camelCase 5필드 수용 (+내부 snake_case 호환)
- get_expense_detail 목 데이터: eval/fixtures/mock_backend.json 조회(T9)
- load_context: claim pull 채움 / 직접 주입 시 조회 생략 / team_settings 실패 시
  auto_approve=False fail-safe
- team_settings·budget 응답 필드 계약 (풀스택 DB 스키마 2026-07-27 수령분)
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.graphs.review.nodes.load_context import load_context
from app.schemas.analyze import AnalyzeRequest
from app.schemas.common import ExpenseClaim
from app.tools.backend_client import get_budget_status, get_expense_detail, get_team_settings
from app.tools.policy_params import effective_auto_approve_limit

# load_context가 gather로 같이 부르는 get_context_status는 이 파일에 실 DB 풀이
# 없어 그대로 두면 예외가 난다(§8 fail-closed 재전파) — rule_version과 무관한
# 테스트는 이 값으로 통일해 무DB 상태를 흉내낸다.
_STUB_CONTEXT_STATUS = {"chunk_count": 0, "version": None, "indexed_at": None}


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
        AnalyzeRequest.model_validate({"jobId": "be-3", "expenseId": "103", "organizationId": "13"})


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


async def test_expense_detail_mock_fixture_lookup():
    """fixture(9002/90001 = club-approve-001)의 값을 그대로 돌려준다.

    category는 **빈 값이 정상**이다 — 심사 전 지출에는 카테고리가 없다는 백엔드 계약
    (BE-001 등록 시 null)과 같은 모양이고, T7 이후 classify_category가 채운다.
    사람이 매긴 정답은 골든셋의 expected_category로 옮겼다 (2026-08-06).
    """
    detail = await get_expense_detail(9002, 90001)
    assert detail["title"] == "동아리 스터디 교재"
    assert detail["amount"] == 32000
    assert detail["category"] == "", "심사 전 지출은 카테고리가 비어 있어야 한다"
    assert detail["description"] == "알고리즘 스터디 교재 2권"


async def test_expense_detail_mock_default_when_unregistered():
    detail = await get_expense_detail(9002, 999999)
    assert detail["amount"] == 30_000 and detail["title"]


async def test_team_settings_mock_fixture_lookup():
    """fixture 9012(club-noauto)는 auto_approve=False, 9002(club-1)는 True."""
    assert (await get_team_settings(9012))["auto_approve"] is False
    assert (await get_team_settings(9002))["auto_approve"] is True


async def test_load_context_pulls_claim():
    state = {"team_id": 9002, "expense_id": 90001}
    with patch(
        "app.graphs.review.nodes.load_context.get_context_status",
        return_value=_STUB_CONTEXT_STATUS,
    ):
        updates = await load_context(state)
    claim = updates["claim"]
    assert claim.title == "동아리 스터디 교재" and claim.amount == 32000
    assert updates["policy_params"].auto_approve is True


async def test_load_context_skips_pull_when_claim_given():
    """직접 그래프 호출(smoke·seed_demo·단위테스트) — 주입된 claim을 덮지 않는다."""
    given = ExpenseClaim(title="직접 주입", amount=1000, date="2026-07-01")
    with patch(
        "app.graphs.review.nodes.load_context.get_context_status",
        return_value=_STUB_CONTEXT_STATUS,
    ):
        updates = await load_context({"team_id": 9002, "expense_id": 999999, "claim": given})
    assert "claim" not in updates


async def test_load_context_fail_safe_on_settings_error():
    """team_settings 조회 실패 → auto_approve=False (자동판정 권한 미확인이면 판정 금지)."""
    with (
        patch(
            "app.graphs.review.nodes.load_context.get_team_settings",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "app.graphs.review.nodes.load_context.get_context_status",
            return_value=_STUB_CONTEXT_STATUS,
        ),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1"})
    assert updates["policy_params"].auto_approve is False


async def test_load_context_propagates_active_rule_version():
    """get_context_status가 돌려준 활성 판번호가 그대로 state["rule_version"]에 실린다.

    rule_auditor(_retrieve_with_correction)가 심사 내내 고정해 쓰는 값이라 —
    조회 결과가 실제로 여기까지 전달되는지 이 노드 경계에서 잠근다.
    """
    claim = ExpenseClaim(title="교재", amount=32_000, category="도서", date="2026-07-01")
    with (
        patch("app.graphs.review.nodes.load_context.get_team_settings", return_value={}),
        patch("app.graphs.review.nodes.load_context.get_team_profile", return_value={}),
        patch("app.graphs.review.nodes.load_context.get_team_members", return_value=[]),
        patch(
            "app.graphs.review.nodes.load_context.get_context_status",
            return_value={"chunk_count": 5, "version": 3, "indexed_at": "2026-08-01T00:00:00"},
        ),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1", "claim": claim})
    assert updates["rule_version"] == 3


# ── team_settings·budget 응답 필드 계약 (풀스택 DB 스키마 2026-07-27) ──


async def test_escalation_threshold_is_amount_not_confidence():
    """team_settings.escalation_threshold는 금액 → force_escalation_amount.

    θ(confidence_threshold)는 백엔드가 모르는 LLM 내부 파라미터라 기본값을 유지한다.
    """
    with (
        patch(
            "app.graphs.review.nodes.load_context.get_team_settings",
            return_value={
                "auto_approve": True,
                "auto_approve_limit": 50_000,
                "escalation_threshold": 300_000,
            },
        ),
        patch(
            "app.graphs.review.nodes.load_context.get_context_status",
            return_value=_STUB_CONTEXT_STATUS,
        ),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1"})
    policy = updates["policy_params"]
    assert policy.force_escalation_amount == 300_000
    assert policy.confidence_threshold == 0.8


async def test_auto_approve_limit_null_means_no_auto_approval():
    """auto_approve_limit은 NULL 허용(자동승인 미사용 팀) — 예외 없이 0으로 처리."""
    with (
        patch(
            "app.graphs.review.nodes.load_context.get_team_settings",
            return_value={
                "auto_approve": False,
                "auto_approve_limit": None,
                "escalation_threshold": 300_000,
            },
        ),
        patch(
            "app.graphs.review.nodes.load_context.get_context_status",
            return_value=_STUB_CONTEXT_STATUS,
        ),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1"})
    assert updates["policy_params"].auto_approve_limit == 0


async def _budget_with_response(body: dict) -> dict:
    """mock_backend=False 경로로 get_budget_status를 호출하고 정규화 결과를 돌려준다."""
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)

    class _Stub:
        async def get(self, *args, **kwargs):
            return response

    with (
        patch(
            "app.tools.backend_client.get_settings",
            return_value=SimpleNamespace(mock_backend=False),
        ),
        patch("app.tools.backend_client._client", return_value=_Stub()),
    ):
        return await get_budget_status("org-1")


async def test_budget_status_normalizes_used_budget_key():
    """백엔드 DB 컬럼 표기(used_budget)를 내부 계약(spent)으로 흡수."""
    result = await _budget_with_response({"total_budget": 300_000, "used_budget": 118_000})
    assert result == {"total_budget": 300_000, "spent": 118_000}


async def test_budget_status_normalizes_camel_case_key():
    """프론트 API-026 표기(totalBudget/usedBudget)로 와도 동일 결과."""
    result = await _budget_with_response({"totalBudget": 300_000, "usedBudget": 118_000})
    assert result == {"total_budget": 300_000, "spent": 118_000}


async def test_escalation_threshold_absent_follows_admin_limit():
    """응답에 escalation_threshold가 없으면 관리자가 설정한 한도를 그대로 따른다.

    2026-08-05 마법사 2단계 화면 개편으로 금액 칸이 하나('관리자 승인 필수 금액')가
    되면서 백엔드가 escalation_threshold 컬럼을 삭제했다. 이때 모델 기본값 200,000을
    쓰면 min(한도, 200,000)이 되어 **관리자가 50만을 설정해도 20만부터 관리자 확인**이
    된다 — 2026-07-31 사고("관리자가 30만을 골라도 심사는 20만으로 동작")와 같은 유형이다.
    """
    with (
        patch(
            "app.graphs.review.nodes.load_context.get_team_settings",
            return_value={"auto_approve": True, "auto_approve_limit": 500_000},
        ),
        patch(
            "app.graphs.review.nodes.load_context.get_context_status",
            return_value=_STUB_CONTEXT_STATUS,
        ),
    ):
        updates = await load_context({"team_id": "org-1", "expense_id": "exp-1"})
    policy = updates["policy_params"]
    assert policy.force_escalation_amount == 500_000
    assert effective_auto_approve_limit(policy) == 500_000  # 200,000으로 축소되지 않는다


async def test_budget_status_skips_explicit_null_alias():
    """명시 null은 건너뛰고 다음 표기 후보를 쓴다.

    백엔드가 전 필드를 직렬화해 {"spent": null, "usedBudget": 118000}을 보내는 경우,
    키 존재만 보고 None을 집으면 지출이 0원으로 잡혀 잔액이 실제보다 많아진다 —
    과다 승인 방향의 오류라 §8에 정면으로 어긋난다.
    """
    result = await _budget_with_response(
        {"total_budget": 300_000, "spent": None, "usedBudget": 118_000}
    )
    assert result == {"total_budget": 300_000, "spent": 118_000}


async def test_budget_status_raises_when_no_alias_present():
    """어느 표기도 없으면 KeyError — budget_auditor가 error 소견으로 잡아 에스컬레이션된다.

    0으로 때우면 '잔액 0 → 반려'라는 틀린 근거가 만들어진다.
    """
    import pytest

    with pytest.raises(KeyError):
        await _budget_with_response({"total_budget": 300_000})
