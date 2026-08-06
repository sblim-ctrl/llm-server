"""제안 목록 조회 (LLM-015, `GET /v1/proposals`) — 회칙·정책 관리 화면.

회의 7번 항목("생성된 제안이 있으면 반환, 없으면 빈 배열")에 대응한다. 같은 `proposals`
테이블을 마법사 회칙 초안(`rule_draft`, `GET /v1/policy-proposals` = LLM-019)과 공유하지만
그쪽은 단건 조회 전용 별개 자원이다 — `type` 미지정 시 이 목록에는 섞이지 않는다.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.api import proposals as proposals_api
from app.api.drafts import RULE_DRAFT
from app.api.proposals import create_budget_proposal_job, read_proposals
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.proposals import ProposalBudgetRequest, ProposalOut

RULE_AMENDMENT = "rule_amendment"


def _row(
    type_: str = RULE_AMENDMENT,
    status: str = "proposed",
    decided_by: str | None = None,
    decided_at: datetime | None = None,
) -> dict:
    """`SELECT *`가 실제로 돌려주는 원형 타입(UUID·datetime)을 그대로 흉내 낸다."""
    return {
        "id": uuid.uuid4(),
        "team_id": 9001,
        "type": type_,
        "payload": {"summary": "개정 문안", "reason": "3회 이상 예외 처리"},
        "status": status,
        "decided_by": decided_by,
        "created_at": datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc),
        "decided_at": decided_at,
    }


# ── 빈 목록·타입 변환 ────────────────────────────────────────────────────────


async def test_returns_empty_list_when_no_proposals_exist():
    """제안이 없으면 빈 배열이다 — 404가 아니다 (LLM-015)."""
    with patch("app.api.proposals.list_proposals", AsyncMock(return_value=[])):
        out = await read_proposals(team_id=9001)

    assert out == []


async def test_converts_db_row_types_to_proposal_out_strings():
    """id는 UUID, created_at은 datetime으로 오는데 응답 스키마 필드는 문자열이다."""
    row = _row()
    with patch("app.api.proposals.list_proposals", AsyncMock(return_value=[row])):
        out = await read_proposals(team_id=9001, type=RULE_AMENDMENT)

    assert out == [
        ProposalOut(
            id=str(row["id"]),
            team_id=9001,
            type=RULE_AMENDMENT,
            payload=row["payload"],
            status="proposed",
            decided_by=None,
            created_at=row["created_at"].isoformat(),
            decided_at=None,
        )
    ]


# ── 필터 ─────────────────────────────────────────────────────────────────


async def test_passes_type_filter_through_to_list_proposals():
    with patch(
        "app.api.proposals.list_proposals", AsyncMock(return_value=[_row()])
    ) as list_proposals:
        await read_proposals(team_id=9001, type=RULE_AMENDMENT)

    list_proposals.assert_awaited_once_with(9001, RULE_AMENDMENT)


async def test_status_filter_keeps_only_matching_rows():
    rows = [_row(status="proposed"), _row(status="accepted")]
    with patch("app.api.proposals.list_proposals", AsyncMock(return_value=rows)):
        out = await read_proposals(team_id=9001, type=RULE_AMENDMENT, status="accepted")

    assert len(out) == 1
    assert out[0].status == "accepted"


# ── rule_draft 기본 제외 ──────────────────────────────────────────────────


async def test_excludes_rule_draft_by_default_when_type_not_specified():
    """마법사 회칙 초안은 관리자 제안함 용도가 아니다 — type 미지정 목록에 섞이지 않는다."""
    rows = [_row(type_=RULE_DRAFT), _row(type_=RULE_AMENDMENT)]
    with patch("app.api.proposals.list_proposals", AsyncMock(return_value=rows)):
        out = await read_proposals(team_id=9001)

    assert [p.type for p in out] == [RULE_AMENDMENT]


async def test_includes_rule_draft_when_type_explicitly_requested():
    row = _row(type_=RULE_DRAFT)
    with patch("app.api.proposals.list_proposals", AsyncMock(return_value=[row])):
        out = await read_proposals(team_id=9001, type=RULE_DRAFT)

    assert [p.type for p in out] == [RULE_DRAFT]


# ── 예산관리 AI 메시지 잡 등록 (LLM-016, `POST /v1/proposals/budget`) ──────────


async def test_budget_route_enqueues_proposal_budget_job():
    """202로 접수만 하고 워커가 3블록을 만든다 — 라우터는 LLM을 부르지 않는다."""
    with patch("app.api.proposals.insert_job", AsyncMock(return_value="job-1")) as insert_job:
        out = await create_budget_proposal_job(
            ProposalBudgetRequest(team_id=9001, period="2026-06")
        )

    assert out.job_id == "job-1"
    insert_job.assert_awaited_once_with(
        team_id=9001,
        job_type="proposal_budget",
        payload={"team_id": 9001, "period": "2026-06"},
    )


def test_budget_route_is_registered_as_202_accepted():
    """상태코드는 데코레이터에 선언돼 있어 코루틴 직접 호출로는 안 보인다 — 라우터를 본다."""
    route = next(
        r for r in proposals_api.router.routes if getattr(r, "path", None) == "/v1/proposals/budget"
    )
    assert route.status_code == 202
    assert route.response_model is AnalyzeAccepted
