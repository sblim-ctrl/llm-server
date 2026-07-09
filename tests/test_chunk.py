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


def test_splits_by_numbered_list_when_no_articles():
    """조항 표기 없이 '1. 2. 3.' 번호 목록으로 쓴 규정도 항목 단위로 분할."""
    text = "1. 회비는 매월 1만원으로 한다\n2. 지출은 총무 승인을 받는다\n3. 영수증을 첨부한다"
    chunks = split_into_clauses(text)
    assert len(chunks) == 3
    assert chunks[1].startswith("2.")


def test_splits_by_circled_numbers():
    text = "① 회비 납부 규정\n② 지출 승인 규정\n③ 정산 규정"
    assert len(split_into_clauses(text)) == 3


def test_falls_back_to_fixed_size_when_single_blob():
    text = "가" * 1200  # 조항 구분도 문단 구분도 없는 긴 텍스트
    chunks = split_into_clauses(text)
    assert len(chunks) == 3  # overlap 포함 3청크
    assert all(len(c) <= 500 for c in chunks)


def test_fixed_fallback_respects_sentence_boundary_and_overlap():
    """구분자 없는 긴 문서 — 문장 중간에서 자르지 않고, 청크 간 맥락이 겹친다."""
    sentence = "모임의 모든 지출은 반드시 사전 협의를 거쳐 집행하여야 한다. "
    text = sentence * 20  # 약 700자, 빈 줄·번호 없음
    chunks = split_into_clauses(text)
    assert len(chunks) >= 2
    assert all(c.rstrip().endswith("다.") for c in chunks)  # 문장 경계에서 끊김
    assert chunks[1].split(".")[0] + "." in chunks[0]        # overlap으로 겹침 존재


def test_empty_text_returns_no_chunks():
    assert split_into_clauses("") == []
    assert split_into_clauses("   ") == []


def test_single_article_is_not_split():
    text = "제1조 (목적) 이것 뿐인 조항."
    chunks = split_into_clauses(text)
    assert len(chunks) == 1
