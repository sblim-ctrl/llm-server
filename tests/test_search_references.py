"""search_references 관련 순수 로직 테스트 — 시딩 청킹 결과 검증 (DB 없이)."""
from pathlib import Path

from app.graphs.indexing.nodes.chunk import split_into_clauses

DOCS_DIR = Path(__file__).resolve().parents[1] / "reference_docs"


def test_reference_docs_folder_has_five_files():
    files = list(DOCS_DIR.glob("*.txt"))
    assert len(files) == 5


def test_each_reference_doc_splits_into_multiple_article_chunks():
    """참고 문서는 전부 '제N조' 형식이라 조항 단위로 잘 쪼개져야 한다.

    첫 청크는 '제1조' 이전의 제목 줄이라 '제'로 시작하지 않을 수 있음 —
    그 뒤(조항 본문)는 전부 '제N조' 형식이어야 한다.
    """
    for path in DOCS_DIR.glob("*.txt"):
        chunks = split_into_clauses(path.read_text(encoding="utf-8"))
        assert len(chunks) >= 5, f"{path.name}: 조항이 너무 적게 분할됨 ({len(chunks)}개)"
        assert all(c.startswith("제") for c in chunks[1:]), f"{path.name}: 조항 형식 아닌 청크 존재"
