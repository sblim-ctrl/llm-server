"""chunk — 원문을 조항 단위로 분할 (§4.4-a).

split_into_clauses는 순수 함수 — 단위 테스트 대상 (rule_auditor·guardrail_gate와 동일 원칙).

우선순위 (구조가 명확한 것부터):
  ① "제N조" 조항 번호        — 표준 회칙 형식
  ② 번호 목록 ("1." "1)" "①") — 조항 표기가 없는 규정·내규
  ③ 빈 줄 문단                — 자유 서식 문서
  ④ 문장 경계 존중 + overlap 고정 분할 — 구분자가 전혀 없는 문서 (최후 폴백)

TODO(3주차+): PDF·이미지 회칙은 Indexer 앞단에 파서 추가 (§12 회칙 형식 다양화)
"""
import re

from app.graphs.indexing.state import IndexingState

ARTICLE_PATTERN = re.compile(r"(?=제\s*\d+\s*조)")
NUMBERED_PATTERN = re.compile(r"(?=^\s*(?:\d{1,2}[.)]|[①-⑮])\s*)", re.MULTILINE)
MAX_CHUNK_CHARS = 500
OVERLAP_CHARS = 100          # 고정 분할 시 맥락 유지용 겹침
MIN_SENTENCE_CUT = 100       # 문장 경계 컷이 너무 앞이면(청크가 너무 짧아지면) 무시


def _fixed_chunks(text: str) -> list[str]:
    """구분자 없는 텍스트 — 문장 경계를 존중하며 overlap을 두고 자른다."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        if end < len(text):
            # 범위 안 마지막 문장 끝(마침표+공백/개행)에서 자르기
            cut = max(text.rfind(". ", start, end), text.rfind(".\n", start, end),
                      text.rfind("다. ", start, end))
            if cut > start + MIN_SENTENCE_CUT:
                end = cut + 2
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return chunks


def split_into_clauses(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    articles = [p.strip() for p in ARTICLE_PATTERN.split(text) if p.strip()]
    if len(articles) > 1:
        return articles

    numbered = [p.strip() for p in NUMBERED_PATTERN.split(text) if p.strip()]
    if len(numbered) > 1:
        return numbered

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs

    return _fixed_chunks(text)


async def chunk(state: IndexingState) -> dict:
    return {"chunks": split_into_clauses(state["raw_text"])}
