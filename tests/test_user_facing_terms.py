"""사용자 노출 문구에 admin/override 등 비직관 용어가 섞이지 않는지 검증 (2026-08-11).

배경: 관리자를 "admin"이라 지칭하는 등 일반 사용자가 이해하기 어려운 표현이
화면에 노출된다는 피드백. 원인은 판례 인용 시스템 표기(`(reject/ADMIN)`)가
프롬프트 few_shot을 통해 판정 사유에 그대로 복제되고, mock 문구·코드 고정 문구에도
영문 필드명·내부 식별자가 섞여 있던 것이었다. `app.eval_support.scan_banned_terms`가
이 그물이고, `eval.run_eval`도 골든셋 실행마다 콜백 페이로드를 같은 방식으로 스캔한다
(하드 게이트) — 여기서는 개별 함수 단위로 회귀를 고정한다.
"""

from app.eval_support import scan_banned_terms, scan_callback_payload_terms
from app.graphs.review.nodes.adjudicate import _mock_result
from app.graphs.review.nodes.callback import (
    translate_precedent_citation,
    build_callback_payload,
)
from app.graphs.review.nodes.escalate import _escalation_detail
from app.graphs.review.nodes.precedent_auditor import _mock_opinion
from app.graphs.review.nodes.rule_auditor import _audit_by_default_policy
from app.graphs.writers.briefing import _handover_notes, _mock_briefing_text
from app.schemas.common import ExpenseClaim, GateResult, Mismatch, Opinion
from app.schemas.writers import BriefingFigures


def test_scan_ignores_clean_korean_text():
    assert scan_banned_terms("모임 예산 잔액이 부족하여 이번 지출은 승인이 어렵습니다.") == []


def test_scan_detects_each_banned_term():
    assert scan_banned_terms("(reject/ADMIN) 판례")
    assert scan_banned_terms("(approve/AGENT) 판례")
    assert scan_banned_terms("override 2건")
    assert scan_banned_terms("어긋나는 점 없음 (mock)")
    assert scan_banned_terms("fail-safe 에스컬레이션")
    assert scan_banned_terms("수치: admin_approve_support=1")
    assert scan_banned_terms("예산 잔액 부족: {'total_budget': 500000}")
    assert scan_banned_terms("잔액 {'remaining_after': -4000}")


# ── callback.py: 판례 인용 접두 치환 ──────────────────────────────────────


def test_translate_precedent_citation_admin_reject_override():
    out = translate_precedent_citation(
        "(reject/ADMIN, override) [식비] 야식비 — 52,000원. 심야 작업 야식 — 사유: 한도 초과"
    )
    assert out == (
        "(관리자 반려·AI 추천 번복) [식비] 야식비 — 52,000원. 심야 작업 야식 — 사유: 한도 초과"
    )
    assert scan_banned_terms(out) == []


def test_translate_precedent_citation_admin_approve_no_override():
    out = translate_precedent_citation("(approve/ADMIN) [행사_활동] 지역 리그 참가비 — 60,000원.")
    assert out == "(관리자 승인) [행사_활동] 지역 리그 참가비 — 60,000원."


def test_translate_precedent_citation_agent_no_override():
    out = translate_precedent_citation("(approve/AGENT) [식비] 정기 회식 — 88,000원.")
    assert out == "(AI 자동 승인) [식비] 정기 회식 — 88,000원."
    assert scan_banned_terms(out) == []


def test_translate_precedent_citation_unmatched_kept_as_is():
    assert translate_precedent_citation("자유 텍스트 — 표기 없음") == "자유 텍스트 — 표기 없음"


def test_build_callback_payload_translates_similar_cases():
    state = {
        "job_id": "job-1",
        "expense_id": 1,
        "team_id": 1,
        "claim": ExpenseClaim(title="야식비", amount=52_000, date="2026-08-01"),
        "verdict": "escalate",
        "opinions": {
            "precedent": Opinion(
                auditor="precedent",
                verdict="warn",
                summary="유사 사안에 대한 반려 판례 1건 발견 — 관리자 확인 권고",
                similar_cases=["(reject/ADMIN) [식비] 야식비 — 52,000원 — 사유: 한도 초과"],
            )
        },
    }
    payload = build_callback_payload(state)
    assert scan_callback_payload_terms(payload) == []
    assert payload.opinions[0].similar_cases == [
        "(관리자 반려) [식비] 야식비 — 52,000원 — 사유: 한도 초과"
    ]


# ── escalate.py: 영수증 불일치 사유의 필드 라벨 ───────────────────────────


def test_escalation_detail_mismatch_uses_korean_field_labels():
    state = {
        "gate_result": None,
        "mismatch": [Mismatch(field="amount", claimed="32000", receipt="45000")],
    }
    detail = _escalation_detail(state)
    assert "금액" in detail
    assert scan_banned_terms(detail) == []


# ── mock 경로 문구 ─────────────────────────────────────────────────────


def test_precedent_mock_opinion_has_no_banned_terms():
    cases = [
        {
            "decision": "reject",
            "decided_by": "ADMIN",
            "is_override": True,
            "expense_summary": "[식비] 야식비 — 52,000원",
            "reason": "한도 초과",
            "distance": 0.1,
        }
    ]
    opinion = _mock_opinion(cases)
    assert scan_banned_terms(opinion.summary) == []


def test_precedent_mock_opinion_support_path_has_no_banned_terms():
    cases = [
        {
            "decision": "approve",
            "decided_by": "ADMIN",
            "is_override": False,
            "expense_summary": "[행사_활동] 지역 리그 참가비 — 60,000원",
            "reason": None,
            "distance": 0.1,
        }
    ]
    opinion = _mock_opinion(cases)
    assert scan_banned_terms(opinion.summary) == []


def test_adjudicate_mock_result_has_no_banned_terms():
    state = {
        "claim": ExpenseClaim(title="다과 구입", amount=5_000, date="2026-08-01"),
        "gate_result": GateResult(
            decision="reject_candidate", triggered_rules=["budget_insufficient"]
        ),
        "opinions": {
            "budget": Opinion(
                auditor="budget",
                verdict="fail",
                summary="총예산 잔액 부족",
                figures={
                    "total_budget": 200_000,
                    "spent": 199_000,
                    "remaining": 1_000,
                    "remaining_after": -4_000,
                },
            )
        },
    }
    result = _mock_result(state)
    assert scan_banned_terms(result.reason_requester, result.reason_admin) == []


def test_adjudicate_mock_result_approve_path_has_no_banned_terms():
    state = {
        "claim": ExpenseClaim(title="스터디 교재", amount=32_000, date="2026-08-01"),
        "gate_result": GateResult(decision="proceed"),
        "opinions": {
            "budget": Opinion(
                auditor="budget",
                verdict="pass",
                summary="총예산 잔액 충분",
                figures={"remaining_after": 150_000},
            )
        },
    }
    result = _mock_result(state)
    assert scan_banned_terms(result.reason_requester, result.reason_admin) == []


async def test_default_policy_mock_opinion_has_no_banned_terms():
    claim = ExpenseClaim(title="정기 회식", amount=45_000, category="식비", date="2026-08-01")
    out = await _audit_by_default_policy({"team_type": None, "receipt_data": None}, claim, [])
    opinion = out["opinions"]["rule"]
    assert scan_banned_terms(opinion.summary) == []


def test_briefing_mock_text_has_no_banned_terms():
    figures = BriefingFigures(
        total_precedents=5,
        agent_decisions=3,
        admin_decisions=2,
        override_count=2,
        escalated_count=0,
        gap_categories=[],
    )
    text = _mock_briefing_text(figures)
    assert scan_banned_terms(text.summary) == []


def test_briefing_handover_notes_have_no_banned_terms():
    figures = BriefingFigures(
        total_precedents=5,
        agent_decisions=3,
        admin_decisions=2,
        override_count=2,
        escalated_count=0,
        gap_categories=[],
    )
    notes = _handover_notes(figures)
    assert scan_banned_terms(*notes) == []
