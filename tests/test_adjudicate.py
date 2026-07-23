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
