"""카테고리 분류 단위 테스트 — 키워드 규칙(목·폴백)과 노드 동작."""
import pytest

from app.graphs.review.nodes.classify_category import classify_by_keywords, classify_category
from app.schemas.common import ExpenseClaim


@pytest.mark.parametrize("text,expected", [
    ("정기 회식 저녁 식사", "식비"),
    ("알고리즘 교재 2권 구입", "도서"),
    ("스터디룸 4시간 대관", "대관"),
    ("셔틀콕 1박스", "용품"),
    ("야근 택시비", "교통"),
    ("여름 MT 펜션", "대관"),      # '펜션' 키워드가 먼저 매칭
    ("현수막 제작", "홍보"),
    ("정체불명 지출", "기타"),
])
def test_keyword_classification(text, expected):
    assert classify_by_keywords(text) == expected


def _claim(category: str) -> ExpenseClaim:
    return ExpenseClaim(title="정기 회식", amount=30_000, category=category,
                        date="2026-07-08", description="팀 저녁 식사")


async def test_empty_category_gets_classified():
    result = await classify_category({"claim": _claim("")})
    assert result["category_source"] == "ai"
    assert result["claim"].category == "식비"


async def test_user_category_is_respected():
    """사용자가 직접 고른 카테고리는 분류 결과와 달라도 덮어쓰지 않는다."""
    result = await classify_category({"claim": _claim("행사")})
    assert result["category_source"] == "user"
    assert "claim" not in result  # claim 미변경
