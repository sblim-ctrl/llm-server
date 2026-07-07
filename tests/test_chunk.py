"""컨텍스트 인덱싱 청크 분할 단위 테스트 (§4.4-a)."""
from app.graphs.indexing.nodes.chunk import split_into_clauses


def test_splits_by_article_number():
    text = "제1조 (목적) 활동비 집행 기준.\n제2조 (한도) 회식비 3만원.\n제3조 (금지) 개인 물품 금지."
    chunks = split_into_clauses(text)
    assert len(chunks) == 3
    assert chunks[0].startswith("제1조")
    assert chunks[1].startswith("제2조")
    assert chunks[2].startswith("제3조")


def test_falls_back_to_paragraphs_when_no_articles():
    text = "첫 번째 문단입니다.\n\n두 번째 문단입니다.\n\n세 번째 문단입니다."
    chunks = split_into_clauses(text)
    assert len(chunks) == 3


def test_falls_back_to_fixed_size_when_single_blob():
    text = "가" * 1200  # 조항 구분도 문단 구분도 없는 긴 텍스트
    chunks = split_into_clauses(text)
    assert len(chunks) == 3  # 500자씩 3청크
    assert all(len(c) <= 500 for c in chunks)


def test_empty_text_returns_no_chunks():
    assert split_into_clauses("") == []
    assert split_into_clauses("   ") == []


def test_single_article_is_not_split():
    text = "제1조 (목적) 이것 뿐인 조항."
    chunks = split_into_clauses(text)
    assert len(chunks) == 1
