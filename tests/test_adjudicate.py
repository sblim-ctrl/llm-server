"""adjudicate user 메시지 빌더 — 소견 근거(조항·수치·판례) 전달 계약 검증.

build_adjudication_user의 출력 형식은 adjudicator/v3+ few_shot input이 미러링한다 —
형식이 바뀌면 프롬프트 few_shot도 함께 갱신해야 한다 (adjudicate.py docstring).
"""

from app.graphs.review.nodes.adjudicate import (
    _MAX_ITEM_CHARS,
    _MAX_LIST_ITEMS,
    build_adjudication_user,
)
from app.graphs.review.nodes.precedent_auditor import _precedent_lines
from app.schemas.common import Opinion


def _opinions() -> dict[str, Opinion]:
    return {
        "rule": Opinion(
            auditor="rule",
            verdict="pass",
            summary="교재 구입을 인정하는 조항에 부합",
            evidence=["스터디 관련 도서는 인당 연 5만원 한도로 인정한다."],
        ),
        "budget": Opinion(
            auditor="budget",
            verdict="pass",
            summary="총예산 잔액 충분: 승인 후 잔액 150,000원",
            figures={
                "total_budget": 300000,
                "spent": 118000,
                "remaining": 182000,
                "remaining_after": 150000,
            },
        ),
        "precedent": Opinion(
            auditor="precedent",
            verdict="warn",
            summary="유사 반려 판례 1건",
            similar_cases=["(reject/ADMIN) [식비] 야식비 — 52,000원 — 사유: 한도 초과"],
        ),
    }


def test_threshold_is_first_line():
    user = build_adjudication_user(_opinions(), 0.8)
    assert user.splitlines()[0] == (
        "판정 임계값: 0.8 — confidence가 이 값 미만이면 시스템이 자동 에스컬레이션합니다."
    )


def test_evidence_figures_similar_cases_blocks_rendered():
    user = build_adjudication_user(_opinions(), 0.8)
    assert "[rule] pass: 교재 구입을 인정하는 조항에 부합" in user
    assert "  근거 조항:\n  - 스터디 관련 도서는 인당 연 5만원 한도로 인정한다." in user
    assert (
        "  수치: total_budget=300,000 / spent=118,000 / remaining=182,000 / remaining_after=150,000"
    ) in user
    assert "  유사 판례:\n  - (reject/ADMIN) [식비] 야식비 — 52,000원 — 사유: 한도 초과" in user


def test_empty_blocks_omitted():
    opinions = {"rule": Opinion(auditor="rule", verdict="warn", summary="관련 조항 없음")}
    user = build_adjudication_user(opinions, 0.8)
    assert "근거 조항" not in user and "수치" not in user and "유사 판례" not in user
    assert user.endswith("[rule] warn: 관련 조항 없음")


def test_item_count_and_length_caps():
    opinions = {
        "rule": Opinion(
            auditor="rule",
            verdict="pass",
            summary="다수 조항",
            evidence=[f"조항{i} " + "가" * 400 for i in range(_MAX_LIST_ITEMS + 2)],
        )
    }
    user = build_adjudication_user(opinions, 0.8)
    items = [ln for ln in user.splitlines() if ln.startswith("  - ")]
    assert len(items) == _MAX_LIST_ITEMS
    assert all(len(ln) <= len("  - ") + _MAX_ITEM_CHARS for ln in items)


def test_precedent_lines_expose_decided_by_and_override():
    cases = [
        {
            "decision": "reject",
            "decided_by": "ADMIN",
            "is_override": True,
            "expense_summary": "[식비] 야식비 — 52,000원",
            "reason": "한도 초과",
        },
        {
            "decision": "approve",
            "decided_by": "AGENT",
            "is_override": False,
            "expense_summary": "[다과] 커피 — 9,000원",
            "reason": None,
        },
    ]
    lines = _precedent_lines(cases).splitlines()
    assert lines[0] == "- (reject/ADMIN, override) [식비] 야식비 — 52,000원 — 사유: 한도 초과"
    assert lines[1] == "- (approve/AGENT) [다과] 커피 — 9,000원 — 사유: 사유 없음"


def test_precedent_lines_empty_marker():
    assert _precedent_lines([]) == "(없음)"


# ── E4: 가드레일 판정이 LLM 판정보다 위다 (2026-08-04 검토 회신) ──────────
#
# `route_after_guardrail`은 `escalate`만 걸러 내고 `reject_candidate`(예산 부족)는
# adjudicate로 보낸다. 여기서 gate_result를 대조하지 않으면, 잔액이 없다는 결정적
# 판정이 난 건에 실모드 LLM이 approve를 내는 순간 그대로 콜백까지 나간다.
#
# **목 모드는 `_mock_result`가 게이트를 존중해 reject를 내므로 골든셋으로는 원리적으로
# 검출되지 않는다** — 그래서 여기가 유일한 그물이다. LLM 응답을 직접 주입해 확인한다.

import logging  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.graphs.review.nodes.adjudicate import AdjudicationResult, adjudicate  # noqa: E402
from app.schemas.common import (  # noqa: E402
    ExpenseClaim,
    GateResult,
    LLMCallMeta,
    PolicyParams,
)


def _state(gate_decision: str, rules: list[str] | None = None) -> dict:
    # claim은 `_mock_result(state)`가 읽는다 — chat_structured를 목으로 바꿔도
    # mock_response 인자가 먼저 평가되므로 상태에 있어야 한다.
    return {
        "claim": ExpenseClaim(title="테스트 지출", amount=30_000, date="2026-08-01"),
        "opinions": _opinions(),
        "policy_params": PolicyParams(confidence_threshold=0.8),
        "gate_result": GateResult(decision=gate_decision, triggered_rules=rules or []),
        "team_members": [],
    }


def _llm(verdict: str, confidence: float = 0.95):
    """adjudicator가 이 판정을 냈다고 가정한다 (실모드 응답 주입)."""
    result = AdjudicationResult(
        verdict=verdict, confidence=confidence,
        reason_requester="요청자용 사유", reason_admin="관리자용 사유",
    )
    meta = LLMCallMeta(model="test", prompt_version="adjudicator/test")
    return patch(
        "app.graphs.review.nodes.adjudicate.chat_structured",
        AsyncMock(return_value=(result, meta)),
    )


async def test_llm_cannot_flip_reject_candidate_to_approve(caplog):
    """예산 부족으로 반려 후보가 된 건은 LLM이 승인해도 escalate로 강등된다.

    §8 "어떤 실패도 자동 승인으로 이어지지 않는다"가 확률이 아니라 보장이 되는 자리.
    """
    with _llm("approve"), caplog.at_level(logging.WARNING):
        out = await adjudicate(_state("reject_candidate", ["budget_insufficient"]))
    assert out["verdict"] == "escalate"
    assert "강등" in caplog.text, "조용히 뒤집으면 안 된다 — 사람이 볼 로그가 남아야 한다"


async def test_reject_candidate_confirmed_as_reject_is_untouched():
    """LLM이 게이트와 같은 방향(reject)을 내면 그대로 둔다 — 정상 경로."""
    with _llm("reject"):
        out = await adjudicate(_state("reject_candidate", ["budget_insufficient"]))
    assert out["verdict"] == "reject"


async def test_proceed_path_can_still_approve():
    """가드레일이 통과시킨 건은 종전대로 승인된다 — 강등이 과잉 적용되면 안 된다."""
    with _llm("approve"):
        out = await adjudicate(_state("proceed"))
    assert out["verdict"] == "approve"


@pytest.mark.parametrize("gate_decision", ["proceed", "reject_candidate"])
async def test_low_confidence_still_escalates(gate_decision):
    """확신도 미달은 게이트 판정과 무관하게 escalate (기존 계약 유지)."""
    with _llm("approve", confidence=0.5):
        out = await adjudicate(_state(gate_decision))
    assert out["verdict"] == "escalate"
