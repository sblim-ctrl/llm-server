"""배포 전 계약 검증 도구의 값 검사 (scripts/verify_backend_contract.py).

이 스크립트는 배포 당일 백엔드 내부 API가 우리 계약과 맞는지 몇 분 안에 보는
도구다. 종전에는 `check_keys`가 **키 존재만** 봐서 백엔드가 `"category": "도서"`
같은 구 어휘를 보내도 통과했다 — T7의 전제("9종만 온다")를 정작 배포 전 점검이
검증해 주지 못하고, 위반이 런타임 WARNING 로그에만 남았다(배포 당일 아무도 안 보는 자리).

여기서 잠그는 것은 "값을 실제로 본다"는 성질이다. 스크립트 자체는 실백엔드가
있어야 돌지만, 판정 함수는 순수 함수라 단위로 검증할 수 있다.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_backend_contract import (  # noqa: E402
    _euro,
    describe_category,
)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_category_is_the_contract(value):
    """지출 상세의 category는 **빈 값이 정상**이다 (BE-001 등록 시 null)."""
    grade, note = describe_category(value)
    assert grade == "ok", note


@pytest.mark.parametrize("value", ["식비", "장소_대관", "IT_인프라", "기타"])
def test_canonical_category_is_accepted(value):
    """9종 안의 값은 정상 범위 — 대개 첫 심사 콜백이 채운 값이 되돌아온 것이다."""
    grade, note = describe_category(value)
    assert grade == "info"
    assert value in note


@pytest.mark.parametrize(
    "value,folded",
    [
        ("교재/자료비", "교육"),       # 우리가 쓰던 구 28종
        ("숙박/여행비", "장소_대관"),
        ("행사", "행사_활동"),         # 백엔드 구 ENUM
        ("도서", "기타"),              # 대응표에 없는 구 어휘 → 기타
        ("듣도보도못한값", "기타"),
    ],
)
def test_out_of_catalog_category_is_reported_with_its_fold(value, folded):
    """9종 밖이면 **경고**하고, 읽기 경계에서 무엇으로 접히는지까지 알려준다.

    접히니까 심사는 정상이지만, 그 사실이 보이지 않으면 카테고리별 집계가
    조용히 뭉뚱그려진다 — 배포 당일 판단에 필요한 정보다.
    """
    grade, note = describe_category(value)
    assert grade == "warn", note
    assert value in note and folded in note


def test_value_check_actually_reads_the_value():
    """회귀 그물의 핵심 — 키 존재만 보던 시절로 돌아가면 여기서 잡힌다.

    같은 키에 서로 다른 값을 넣었을 때 판정이 갈려야 한다. 값을 안 읽으면
    셋 다 같은 결과가 나온다.
    """
    grades = {describe_category(v)[0] for v in ("", "식비", "교재/자료비")}
    assert grades == {"ok", "info", "warn"}


@pytest.mark.parametrize(
    "word,expected",
    [
        ("기타", "로"), ("교육", "으로"), ("장소_대관", "으로"), ("식비", "로"), ("", "로"),
        ("물", "로"),      # ㄹ 받침은 예외 — '물으로'가 아니다 (현 9종엔 없지만 규칙은 맞춘다)
    ],
)
def test_particle_matches_final_consonant(word, expected):
    """배포 당일 사람이 읽는 문구라 조사를 맞춘다 — '교육으로'지 '교육로'가 아니다."""
    assert _euro(word) == expected


# ── 호출부 — 판정 함수가 아니라 '기록되는가'를 본다 ──────────────
#
# 위 테스트들은 순수 함수만 덮는다. 정작 배포 당일 사람이 보는 것은 `run_checks`가
# 찍는 O/X 줄인데, 그 배선은 실백엔드가 있어야 도는 자리라 한 번도 실행된 적이 없었다.
# httpx.MockTransport로 가짜 백엔드를 세워 실제로 돌린다
# (2026-08-07 뮤테이션 검증: 이 그물이 없을 때 호출부 결함 4종이 전부 통과했다).

import argparse  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httpx  # noqa: E402

from scripts.verify_backend_contract import _results, run_checks  # noqa: E402

_MISSING = object()
_ARGS = argparse.Namespace(
    team_id=1, expense_id=1, receipt_path=None, base_url="http://mock"
)


def _run(detail_category=_MISSING, history=None):
    """가짜 백엔드로 run_checks를 돌리고 {항목명: (통과여부, 비고)}를 돌려준다."""
    history = [] if history is None else history

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/team-settings"):
            return httpx.Response(200, json={"auto_approve": True, "auto_approve_limit": 50000})
        if "/expenses/" in p:
            d = {"title": "점심", "amount": 12000, "date": "2026-08-07", "description": ""}
            if detail_category is not _MISSING:
                d["category"] = detail_category
            return httpx.Response(200, json=d)
        if p.endswith("/expenses"):
            return httpx.Response(200, json=history)
        if p.endswith("/policy-document"):
            return httpx.Response(404)
        if p.endswith("/budget"):
            return httpx.Response(200, json={"total_budget": 100, "spent": 10})
        if p.endswith("/profile"):
            return httpx.Response(200, json={"team_type": "동아리"})
        if p.endswith("/members"):
            return httpx.Response(200, json=[{"name": "김", "role": "회원"}])
        return httpx.Response(200, json={})

    _results.clear()
    # 무토큰 인증 점검만 client를 안 거치고 httpx.get을 직접 부른다 — 테스트가 실제
    # 소켓을 물지 않도록 막는다(안 막으면 연결 실패를 기다리느라 건당 몇 초씩 든다).
    with (
        patch("httpx.get", return_value=httpx.Response(401)),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="http://mock") as c,
    ):
        run_checks(_ARGS, c)
    return {name: (ok, note) for _, name, ok, note in _results}


def _row(history_category):
    return {"title": "a", "amount": 1, "date": "2026-06-01", "status": "APPROVED",
            "category": history_category}


DETAIL = "지출 상세의 category 계약"
HISTORY = "이력 category 값 분포"


def test_detail_without_category_passes():
    """지출 상세는 **빈 값이 정상**이다 (BE-001 등록 시 null)."""
    ok, note = _run()[DETAIL]
    assert ok is True, note


def test_detail_with_stale_vocabulary_is_reported_as_failure():
    """구 어휘가 실려 오면 X로 찍혀야 한다 — 이 PR이 막으려던 바로 그 경우.

    통과로 기록하면 배포 당일 화면이 아직 구 카테고리를 보낸다는 사실이 묻힌다.
    """
    ok, note = _run(detail_category="도서")[DETAIL]
    assert ok is False
    assert "도서" in note and "기타" in note      # 무엇으로 접히는지까지 보여준다


def test_detail_with_canonical_category_passes_as_reecho():
    """9종 값은 재심사 에코라 정상이다 — 실패로 찍으면 배포 당일 오탐이 된다."""
    ok, note = _run(detail_category="식비")[DETAIL]
    assert ok is True
    assert "식비" in note


def test_history_all_canonical_passes():
    ok, note = _run(history=[_row("식비"), _row("교통")])[HISTORY]
    assert ok is True, note
    assert "2건" in note


def test_history_with_stale_vocabulary_fails_and_shows_the_fold():
    """이력에 9종 밖 값이 섞이면 X — 몇 건이 무엇으로 접히는지까지 보여준다."""
    ok, note = _run(history=[_row("교재/자료비"), _row("식비"), _row(None)])[HISTORY]
    assert ok is False
    assert "9종 밖 1건" in note and "빈 값 1건" in note
    assert "교육" in note                          # 접히는 대상


def test_history_blank_count_is_the_blank_ones():
    """빈 값 집계가 다른 등급을 세면 안 된다 — 전부 9종이면 빈 값은 0건이다."""
    _, note = _run(history=[_row("식비"), _row("교통"), _row("비품")])[HISTORY]
    assert "빈 값 0건" in note


def test_history_rows_that_are_not_objects_do_not_vanish_silently():
    """계약을 어긴 행(문자열)이 섞이면 건수가 맞지 않는다는 게 드러나야 한다.

    조용히 걸러내면 "2건 중 0건 이상 없음"으로 통과해, 형태가 깨진 사실이 묻힌다.
    """
    res = _run(history=["망가진행", _row("식비")])
    ok, note = res[HISTORY]
    assert ok is False, note
    assert "형태가 아닌 행 1건" in note


def test_empty_history_skips_the_distribution_check():
    """빈 목록이면 분포를 셀 것이 없다 — 없는 항목을 통과로 위조하지 않는다."""
    assert HISTORY not in _run(history=[])
