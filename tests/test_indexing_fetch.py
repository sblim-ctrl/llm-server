"""인덱싱 fetch — 회칙이 텍스트로 오든 파일로 오든 인덱싱까지 이어지는가 (T2).

회칙은 마법사 3단계에서 **직접 입력**되거나 **PDF·docx로 업로드**된다. 어느 쪽인지는
백엔드만 아는 사실이라 같은 엔드포인트가 형식만 달리 답하고, `fetch`가 분기한다.
이 설계 덕에 LLM-006 계약도 워커도 안 바뀐다.

파싱 실패는 반드시 예외로 올라와야 한다 — 빈 텍스트로 이어가면 인덱싱이 청크 0개로
'성공'하고 관리자는 회칙을 등록했다고 믿는데 심사는 회칙 없는 팀으로 돈다.
"""
import io
from unittest.mock import AsyncMock, patch

import docx
import pytest

from app.graphs.indexing.nodes.chunk import chunk
from app.graphs.indexing.nodes.fetch import fetch
from app.tools.backend_client import PolicyDocumentSource
from app.tools.document_parser import DocumentParseError

RULE_LINES = [
    "제1조 (목적) 이 회칙은 모임 활동비 집행 기준을 정한다.",
    "제2조 (회식비 한도) 1인당 회식비는 3만원을 초과할 수 없다.",
    "제3조 (금지 항목) 개인 용도 물품 구입은 지출로 인정하지 않는다.",
    "제4조 (도서 구입) 스터디 관련 도서는 인당 연 5만원 한도로 인정한다.",
]


def _docx(lines: list[str]) -> bytes:
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def _fetch(source: PolicyDocumentSource) -> dict:
    with patch("app.graphs.indexing.nodes.fetch.get_policy_document",
               AsyncMock(return_value=source)):
        return await fetch({"team_id": 1, "doc_type": "rule", "version": 1})


async def test_text_source_passes_through():
    out = await _fetch(PolicyDocumentSource(text="제1조 (목적) 텍스트로 등록된 회칙이다."))
    assert out["source_kind"] == "text"
    assert "제1조" in out["raw_text"]


async def test_file_source_is_parsed_to_text():
    out = await _fetch(PolicyDocumentSource(file_bytes=_docx(RULE_LINES), filename="회칙.docx"))
    assert out["source_kind"] == "file"
    for line in RULE_LINES:
        assert line in out["raw_text"]


async def test_uploaded_file_reaches_clause_level_chunks():
    """파일 회칙이 **조항 단위로 인덱싱되는지** — 이게 안 되면 회칙 검색 품질이 무너진다.

    관리자가 docx를 올렸을 때 조항 4개가 청크 4개가 되어야, 회칙 심사관이 "제2조
    회식비 한도"를 정확히 집어올 수 있다. 한 덩어리로 뭉치면 검색이 엉뚱한 조항을 준다.
    """
    state = await _fetch(PolicyDocumentSource(file_bytes=_docx(RULE_LINES),
                                              filename="회칙.docx"))
    state.update({"team_id": 1, "doc_type": "rule", "version": 1})
    out = await chunk(state)

    assert len(out["chunks"]) == len(RULE_LINES)
    assert out["chunks"][1].startswith("제2조")


async def test_unparseable_file_raises_instead_of_indexing_nothing():
    """스캔본 PDF 등 파싱 실패는 예외로 올라와 잡을 failed로 만든다.

    조용히 넘어가면 회칙이 등록됐는데 심사에는 반영 안 된 상태가 되고, 관리자는
    그 사실을 알 방법이 없다.
    """
    with pytest.raises(DocumentParseError):
        await _fetch(PolicyDocumentSource(file_bytes=b"%PDF-1.4\n%%EOF", filename="scan.pdf"))


async def test_empty_source_raises():
    """백엔드가 텍스트도 파일도 안 주면 계약 위반이다 — 빈 인덱스를 만들지 않는다."""
    with pytest.raises(DocumentParseError):
        await _fetch(PolicyDocumentSource())
