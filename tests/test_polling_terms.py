"""폴링 경로(GET /v1/jobs/{job_id})의 사용자 노출 용어 — #71.

#68이 admin·override 등 시스템 표기를 콜백 직전에 한국어로 치환하게 했지만, 치환은
`build_callback_payload`에서만 일어난다. `worker.py`는 치환 **전** 원본 opinions를
`jobs.result`에 저장하고, 콜백이 유실되면 백엔드가 `GET /v1/jobs/{job_id}`(§7.1
안전망)로 그 원본을 그대로 받는다. 같은 심사가 경로에 따라 다른 문구로 나가던 자리다.

여기서 고정하는 것:
  ① 저장된 원본을 조회하면 콜백과 **같은** 문구가 나온다
  ② 치환 규칙이 콜백과 한 벌이다 (문자열 비교로 직접 대조)
  ③ 심사 잡이 아닌 결과(`dead`의 error/message 등)는 손대지 않는다
  ④ 금지 용어 스캐너가 폴링 응답까지 덮는다
"""

from app.api.jobs import translate_result_terms
from app.eval_support import scan_job_result_terms
from app.graphs.review.nodes.callback import translate_precedent_citation

RAW_CITATION = "(reject/ADMIN, override) 개인 용도 물품 — 사유: 회칙 제3조"
RAW_AGENT_CITATION = "(approve/AGENT) 스터디 교재 구입"


def _job_result(cases: list[str]) -> dict:
    """worker.py가 jobs.result에 저장하는 모양 (opinions는 model_dump된 dict)."""
    return {
        "verdict": "escalate",
        "reasons": {"requester": "관리자 확인이 필요합니다.", "admin": "유사 판례 검토 필요"},
        "opinions": [
            {"auditor": "precedent", "verdict": "warn", "summary": "유사 판례 1건",
             "similar_cases": cases},
            {"auditor": "budget", "verdict": "pass", "summary": "총예산 잔액 충분",
             "similar_cases": []},
        ],
    }


def test_polling_result_translates_citations():
    """① 저장된 원본이 조회 시점에 한국어로 바뀐다 — 폴링으로 시스템 표기가 새지 않는다."""
    out = translate_result_terms(_job_result([RAW_CITATION, RAW_AGENT_CITATION]))
    cases = out["opinions"][0]["similar_cases"]

    assert "ADMIN" not in cases[0] and "override" not in cases[0]
    assert cases[0].startswith("(관리자 반려·AI 추천 번복)")
    assert cases[1].startswith("(AI 자동 승인)")


def test_polling_translation_matches_callback_rule():
    """② 콜백과 같은 규칙이어야 한다 — 두 경로가 같은 심사를 다르게 표기하면 안 된다."""
    out = translate_result_terms(_job_result([RAW_CITATION]))
    assert out["opinions"][0]["similar_cases"][0] == translate_precedent_citation(RAW_CITATION)


def test_polling_translation_keeps_everything_else():
    """치환은 판례 인용 접두에만 닿는다 — 다른 필드·본문은 그대로."""
    src = _job_result([RAW_CITATION])
    out = translate_result_terms(src)

    assert out["verdict"] == src["verdict"]
    assert out["reasons"] == src["reasons"]
    assert out["opinions"][1] == src["opinions"][1]  # 인용 없는 소견은 손대지 않는다
    assert "사유: 회칙 제3조" in out["opinions"][0]["similar_cases"][0]  # 본문 보존


def test_polling_translation_ignores_non_review_results():
    """③ 심사 잡이 아닌 결과는 모양이 달라도 깨지지 않고 그대로 통과한다."""
    dead = {"error": "DocumentParseError", "message": "회칙 파일을 읽지 못했습니다"}
    assert translate_result_terms(dead) == dead
    assert translate_result_terms(None) is None
    assert translate_result_terms({"opinions": "not-a-list"}) == {"opinions": "not-a-list"}


def test_scanner_catches_untranslated_polling_result():
    """④ 스캐너가 폴링 응답을 덮는다 — 치환 전은 잡히고 치환 후는 깨끗하다.

    이 검사가 없으면 다음에 출구가 하나 더 생겨도 같은 방식으로 조용히 샌다.
    """
    raw = _job_result([RAW_CITATION])
    assert scan_job_result_terms(raw), "치환 전 원본은 금지 용어로 잡혀야 한다"
    assert scan_job_result_terms(translate_result_terms(raw)) == []


def test_scanner_ignores_non_dict_result():
    assert scan_job_result_terms(None) == []
    assert scan_job_result_terms("dead") == []


def test_polling_opinion_order_matches_callback_contract():
    """⑥ 폴링 opinions도 콜백과 같은 순서 계약 (#86).

    worker는 삽입 순서(evidence 맨 앞, 병렬 3종은 완료 순서)로 저장한다 — 배열
    순서로 카드를 그리는 수신 측에서 2026-08-11 데모 카드 스왑을 만든 성질이다.
    """
    from app.api.jobs import order_result_opinions

    stored = {"verdict": "escalate", "opinions": [
        {"auditor": "evidence", "verdict": "pass", "summary": "일치"},
        {"auditor": "precedent", "verdict": "warn", "summary": "유사 판례"},
        {"auditor": "rule", "verdict": "pass", "summary": "위반 없음"},
        {"auditor": "budget", "verdict": "pass", "summary": "잔액 충분"},
    ]}
    out = order_result_opinions(stored)
    assert [o["auditor"] for o in out["opinions"]] == ["rule", "budget", "precedent", "evidence"]
    assert stored["opinions"][0]["auditor"] == "evidence"  # 원본은 불변 (순수 함수)


def test_polling_opinion_order_is_one_rule_with_callback():
    """⑥-2 순서 규칙이 콜백과 **한 벌**이다 — 같은 내용을 두 함수에 넣어 직접 대조.

    콜백 쪽이 순서를 바꾸면(예: evidence를 앞으로) 이 대조가 깨져서, 두 경로가
    조용히 갈라지는 회귀(#71과 같은 계열)를 막는다. 신설 심사관(미등록 키)이 뒤로
    가는 규칙까지 함께 잠근다.
    """
    from app.api.jobs import order_result_opinions
    from app.graphs.review.nodes.callback import ordered_opinions

    auditors = ["evidence", "precedent", "future_new", "rule", "budget"]
    by_callback = ordered_opinions({a: a for a in auditors})
    by_polling = order_result_opinions({"opinions": [{"auditor": a} for a in auditors]})
    assert [o["auditor"] for o in by_polling["opinions"]] == by_callback


def test_polling_opinion_order_ignores_non_review_results():
    """⑥-3 심사 잡이 아닌 결과는 정렬도 손대지 않는다 (치환 ③과 같은 방어)."""
    from app.api.jobs import order_result_opinions

    dead = {"error": "DocumentParseError", "message": "회칙 파일을 읽지 못했습니다"}
    assert order_result_opinions(dead) == dead
    assert order_result_opinions(None) is None
    assert order_result_opinions({"opinions": "not-a-list"}) == {"opinions": "not-a-list"}


async def test_read_job_endpoint_applies_translation():
    """⑤ **엔드포인트가 실제로 치환을 태우는지** — 함수만 검사하면 배선이 빠져도 통과한다.

    실제로 위 ①~④만 있을 때 `read_job`에서 치환 호출을 지우는 뮤테이션이 전부
    통과했다(2026-08-12). 순수 함수 테스트는 배선을 증명하지 못한다.
    """
    from datetime import datetime
    from unittest.mock import AsyncMock, patch

    from app.api.jobs import read_job

    job_row = {
        "id": "job-1", "status": "succeeded", "attempts": 1,
        "result": _job_result([RAW_CITATION]),
        "created_at": datetime(2026, 8, 12), "updated_at": datetime(2026, 8, 12),
    }
    with patch("app.api.jobs.get_job", new=AsyncMock(return_value=job_row)):
        resp = await read_job("job-1")

    # 정렬(#86)로 위치가 바뀔 수 있으니 인덱스가 아니라 auditor로 찾는다
    by_auditor = {o["auditor"]: o for o in resp.result["opinions"]}
    cited = by_auditor["precedent"]["similar_cases"][0]
    assert "ADMIN" not in cited and "override" not in cited
    assert scan_job_result_terms(resp.result) == []
    # ⑥ 배선 — 저장 순서(precedent, budget)가 응답에서 계약 순서(budget, precedent)로.
    # read_job에서 order_result_opinions 호출을 지우는 뮤테이션은 여기서만 잡힌다.
    assert [o["auditor"] for o in resp.result["opinions"]] == ["budget", "precedent"]
