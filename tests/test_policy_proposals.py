"""회칙 초안 제안 흐름 (풀스택 협의 2026-08-04 7번).

"AI 추천 → 요청 → 있으면 반환·없으면 없다고 반환 → 승인/거절"이 회의록의 흐름이다.
승인·거절 기록(PATCH /v1/proposals/{id})과 저장소는 이미 있던 것을 그대로 쓰므로,
여기서 검증할 것은 **초안이 제안 흐름에 제대로 얹혔는가**다.

특히 '재사용'이 핵심이다 — LLM은 부를 때마다 다른 문장을 내므로, 저장하지 않으면
관리자가 화면을 새로 고칠 때마다 회칙이 바뀐다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.api.drafts import (
    RULE_DRAFT, create_policy_proposal, read_policy_proposal,
)
from app.schemas.writers import (
    PolicyDraft, PolicyParamsSuggestion, PolicyProposalRequest,
)

REQ = PolicyProposalRequest(
    team_id=9001, team_type="스터디", team_name="알고리즘 스터디",
    initial_budget=500_000, dues=20_000, description="주 1회 알고리즘 문제 풀이",
)


def _draft(first_rule: str = "조항 A") -> PolicyDraft:
    return PolicyDraft(
        rules=[first_rule, "조항 B"],
        policy_params=PolicyParamsSuggestion(auto_approve_limit=50_000,
                                             force_escalation_amount=200_000),
        recommended_categories=["교육", "식비"], notes="테스트",
    )


def _row(proposal_id: str, draft: PolicyDraft, status: str = "proposed") -> dict:
    return {"id": proposal_id, "team_id": 9001, "type": RULE_DRAFT,
            "payload": draft.model_dump(mode="json"), "status": status}


# ── 생성 ──────────────────────────────────────────────────────────────────

async def test_creates_and_saves_when_none_exists():
    with patch("app.api.drafts.list_proposals", AsyncMock(return_value=[])), \
         patch("app.api.drafts._generate", AsyncMock(return_value=_draft())), \
         patch("app.api.drafts.save_proposal", AsyncMock(return_value="p-1")) as save:
        out = await create_policy_proposal(REQ)

    assert out.proposal_id == "p-1"
    assert out.status == "proposed"
    assert out.reused is False
    assert out.draft.rules[0] == "조항 A"
    # proposals에 rule_draft 종류로 남는다 — budget·rule_amendment와 같은 테이블
    assert save.await_args.args[1] == RULE_DRAFT


async def test_reuses_existing_open_proposal_instead_of_regenerating():
    """버튼을 다시 눌러도 같은 초안을 봐야 한다 — LLM을 다시 부르지 않는다."""
    saved = _draft("먼저 만든 조항")
    with patch("app.api.drafts.list_proposals",
               AsyncMock(return_value=[_row("p-1", saved)])), \
         patch("app.api.drafts._generate", AsyncMock()) as gen, \
         patch("app.api.drafts.save_proposal", AsyncMock()) as save:
        out = await create_policy_proposal(REQ)

    assert out.proposal_id == "p-1"
    assert out.reused is True
    assert out.draft.rules[0] == "먼저 만든 조항"
    gen.assert_not_awaited()      # LLM 호출 없음 — 비용·일관성 둘 다
    save.assert_not_awaited()


async def test_regenerate_makes_a_new_proposal_and_keeps_the_old_one():
    """'다시 생성'은 새 제안을 하나 더 만든다 — 이전 것을 지우지 않아 이력이 남는다."""
    saved = _draft("먼저 만든 조항")
    with patch("app.api.drafts.list_proposals",
               AsyncMock(return_value=[_row("p-1", saved)])), \
         patch("app.api.drafts._generate", AsyncMock(return_value=_draft("새 조항"))), \
         patch("app.api.drafts.save_proposal", AsyncMock(return_value="p-2")):
        out = await create_policy_proposal(REQ.model_copy(update={"regenerate": True}))

    assert out.proposal_id == "p-2"
    assert out.reused is False
    assert out.draft.rules[0] == "새 조항"


async def test_decided_proposal_does_not_block_new_generation():
    """이미 승인·거절된 초안은 '있는 것'으로 치지 않는다."""
    done = _row("p-old", _draft("옛 조항"), status="accepted")
    with patch("app.api.drafts.list_proposals", AsyncMock(return_value=[done])), \
         patch("app.api.drafts._generate", AsyncMock(return_value=_draft("새 조항"))), \
         patch("app.api.drafts.save_proposal", AsyncMock(return_value="p-2")):
        out = await create_policy_proposal(REQ)

    assert out.proposal_id == "p-2"
    assert out.reused is False


# ── 조회 ──────────────────────────────────────────────────────────────────

async def test_read_returns_null_when_nothing_saved():
    """'초안이 아직 없음'은 오류가 아니라 정상 상태라 200 + null이다."""
    with patch("app.api.drafts.list_proposals", AsyncMock(return_value=[])):
        assert await read_policy_proposal(team_id=9001) is None


async def test_read_returns_open_proposal():
    with patch("app.api.drafts.list_proposals",
               AsyncMock(return_value=[_row("p-1", _draft())])):
        out = await read_policy_proposal(team_id=9001)

    assert out is not None
    assert out.proposal_id == "p-1"
    assert out.status == "proposed"
    assert out.reused is True


async def test_read_skips_decided_and_takes_latest_open():
    """list_proposals는 최신순이다 — 결정된 것을 건너뛰고 가장 최근 미결정을 준다."""
    rows = [_row("p-3", _draft("최신"), status="dismissed"),
            _row("p-2", _draft("두 번째")),
            _row("p-1", _draft("가장 오래된"))]
    with patch("app.api.drafts.list_proposals", AsyncMock(return_value=rows)):
        out = await read_policy_proposal(team_id=9001)

    assert out.proposal_id == "p-2"


# ── 요청 계약 ─────────────────────────────────────────────────────────────

def test_request_carries_the_same_fields_as_wizard_draft():
    """초안을 만드는 재료는 마법사 3단계와 같다 — 달라질 이유가 없다."""
    d = REQ.to_draft_request()
    assert d.team_type == "스터디" and d.team_name == "알고리즘 스터디"
    assert d.initial_budget == 500_000 and d.dues == 20_000
    assert d.description == "주 1회 알고리즘 문제 풀이"


def test_request_requires_team_id():
    with pytest.raises(ValueError):
        PolicyProposalRequest(team_type="스터디", team_name="x", initial_budget=1000)
