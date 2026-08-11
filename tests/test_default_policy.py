"""기본 정책 모드 — 회칙 미등록 팀 심사 (마법사 3단계 '건너뛰기').

마법사 3단계는 회칙 등록을 "나중에 등록해도 돼요. 없으면 기본 정책 모드로 시작해요"라고
안내한다(프로토타입 10/38). 전에는 그 상태에서 rule_auditor가 무조건 pass여서 회칙 축이
통째로 비어 있었다.

핵심 검증 두 가지:
- 근거에 금액 한도 조항이 섞이지 않을 것 (가드레일과 중복이고, 팀이 합의한 금액도 아님)
- 어떤 경우에도 fail이 나가지 않을 것 (팀이 동의한 적 없는 기준으로 반려하지 않는다)
"""
import pytest

from app.graphs.review.nodes.rule_auditor import _audit_by_default_policy
from app.schemas.common import ExpenseClaim
from app.tools.policy_defaults import (
    FALLBACK_TEAM_TYPE,
    default_conduct_rules,
    load_templates,
)

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]

CLAIM = ExpenseClaim(
    title="모임 다과", amount=45_000, category="다과",
    date="2026-07-10", description="정기 모임 간식",
)


# ── 근거 선별 (금액 조항 제외) ──────────────────────────


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_default_rules_exclude_amount_clauses(team_type):
    """금액 한도 조항은 근거에서 빠진다 — 가드레일이 이미 보고, 합의된 금액도 아니다."""
    rules = default_conduct_rules(team_type)
    assert rules, f"{team_type}: 성격 조항이 하나도 없으면 모드가 무의미하다"
    assert not any("원" in r and ("한도" in r or "초과" in r) for r in rules)
    # placeholder가 남아 사용자에게 그대로 노출되는 일도 없어야 한다
    assert not any("{" in r for r in rules)


@pytest.mark.parametrize("team_type", TEAM_TYPES)
def test_default_rules_are_subset_of_template(team_type):
    """지어낸 조항이 아니라 템플릿 원문 그대로여야 한다."""
    base = load_templates()[team_type]["base_rules"]
    assert set(default_conduct_rules(team_type)) <= set(base)


def test_unknown_team_type_falls_back():
    """유형 조회 실패(load_context fail-open)로 낯선 값이 와도 심사가 멈추지 않는다."""
    assert default_conduct_rules("듣도보도못한유형") == default_conduct_rules(FALLBACK_TEAM_TYPE)


def test_rules_cached_as_tuple():
    """lru_cache 반환값이 밖에서 변형되지 않도록 tuple이어야 한다."""
    assert isinstance(default_conduct_rules("스터디"), tuple)


# ── 심사 동작 ───────────────────────────────────────────


async def test_default_policy_used_when_no_rules_indexed():
    """회칙이 없어도 rule 소견이 남는다 — 예전처럼 빈 pass로 끝나지 않는다."""
    out = await _audit_by_default_policy(
        {"team_type": "동아리/학생회"}, CLAIM, members=[])
    opinion = out["opinions"]["rule"]
    assert opinion.auditor == "rule"
    assert opinion.evidence, "기본 조항을 근거로 남겨야 관리자가 판단 이유를 안다"
    assert set(opinion.evidence) <= set(default_conduct_rules("동아리/학생회"))


async def test_default_policy_never_rejects():
    """fail은 warn으로 낮춘다 — 팀이 동의한 적 없는 기준으로 반려하지 않는다."""
    from unittest.mock import patch

    from app.schemas.common import LLMCallMeta, Opinion

    async def _fail_opinion(**kwargs):
        return (
            Opinion(auditor="rule", verdict="fail", summary="개인 용도 물품"),
            LLMCallMeta(model="gpt-4o-mini", mock=True, prompt_version="default_policy/v2"),
        )

    with patch("app.graphs.review.nodes.rule_auditor.chat_structured", _fail_opinion):
        out = await _audit_by_default_policy(
            {"team_type": "동아리/학생회"}, CLAIM, members=[])

    opinion = out["opinions"]["rule"]
    assert opinion.verdict == "warn", "이 모드에서 반려 판정은 나가면 안 된다"
    assert "반려 아님" in opinion.summary


async def test_default_policy_records_llm_meta():
    """비용·버전 계측 대상 — 새 경로도 llm_meta에 남아야 한다."""
    out = await _audit_by_default_policy(
        {"team_type": "스터디"}, CLAIM, members=[])
    meta = out["llm_meta"]["default_policy"]
    assert meta.prompt_version == "default_policy/v2"


async def test_missing_team_type_does_not_crash():
    """team_type이 상태에 없어도(조회 실패) 기본 유형으로 심사한다."""
    out = await _audit_by_default_policy({}, CLAIM, members=[])
    assert out["opinions"]["rule"].verdict in {"pass", "warn"}


# ── 영수증 상태 컨텍스트 ────────────────────────────────
#
# 기본 조항에 "모든 지출은 영수증을 첨부해야 한다"가 있는데 user 메시지에 첨부
# 여부가 없으면, 모델이 "첨부 불명확"으로 헤지해 정상 첨부 건까지 warn을 낸다 —
# 2026-08-11 프론트 데모(팀2 expense 9)에서 실제 재현. 아래는 intake 결과별로
# user 메시지에 상태 한 줄이 정확히 들어가는지 본다.


async def _capture_user_message(state) -> str:
    from unittest.mock import patch

    from app.schemas.common import LLMCallMeta, Opinion

    captured = {}

    async def _spy(**kwargs):
        captured.update(kwargs)
        return (
            Opinion(auditor="rule", verdict="pass", summary="ok"),
            LLMCallMeta(model="gpt-4o-mini", mock=True, prompt_version="default_policy/v2"),
        )

    with patch("app.graphs.review.nodes.rule_auditor.chat_structured", _spy):
        await _audit_by_default_policy(state, CLAIM, members=[])
    return captured["user"]


async def test_user_message_states_receipt_parsed_ok():
    """정상 첨부·판독 건은 그 사실이 명시된다 — 헤지 warn의 원인 제거."""
    from app.schemas.common import ReceiptData

    user = await _capture_user_message({
        "team_type": "동아리/학생회",
        "receipt_data": ReceiptData(amount=45_000, date="2026-07-10"),
    })
    assert "영수증 상태: 첨부됨, 정상 판독" in user


async def test_user_message_states_receipt_missing():
    """미첨부 건은 미첨부로 명시된다 — '증빙이 없는 지출' warn 근거가 되도록."""
    from app.schemas.common import ReceiptData

    user = await _capture_user_message({
        "team_type": "동아리/학생회",
        "receipt_data": ReceiptData(parse_ok=False, parse_error="영수증 미첨부"),
    })
    assert "영수증 상태: 영수증 미첨부" in user


async def test_user_message_states_receipt_unreadable():
    """판독 실패는 실패 사유가 그대로 실린다 (에스컬레이션은 가드레일 몫)."""
    from app.schemas.common import ReceiptData

    user = await _capture_user_message({
        "team_type": "동아리/학생회",
        "receipt_data": ReceiptData(
            parse_ok=False, parse_error="영수증 판독 실패 (Vision OCR 오류)"),
    })
    assert "영수증 상태: 영수증 판독 실패" in user


async def test_user_message_without_receipt_data_says_unknown():
    """그래프 밖 직접 호출(intake 미실행)에서는 사실대로 '정보 없음' — 지어내지 않는다."""
    user = await _capture_user_message({"team_type": "동아리/학생회"})
    assert "영수증 상태: 정보 없음" in user
