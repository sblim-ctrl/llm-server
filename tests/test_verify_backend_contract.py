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
    [("기타", "로"), ("교육", "으로"), ("장소_대관", "으로"), ("식비", "로"), ("", "로")],
)
def test_particle_matches_final_consonant(word, expected):
    """배포 당일 사람이 읽는 문구라 조사를 맞춘다 — '교육으로'지 '교육로'가 아니다."""
    assert _euro(word) == expected
