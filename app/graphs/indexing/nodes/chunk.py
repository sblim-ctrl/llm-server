"""chunk — 원문을 조항 단위로 분할 (§4.4-a).

split_into_clauses는 순수 함수 — 단위 테스트 대상 (rule_auditor·guardrail_gate와 동일 원칙).
우선순위: 조항 번호("제N조") 기준 → 없으면 빈 줄 문단 기준 → 그래도 없으면 고정 길이.
"""
import re

from app.graphs.indexing.state import IndexingState

ARTICLE_PATTERN = re.compile(r"(?=제\s*\d+\s*조)")
MAX_CHUNK_CHARS = 500


def split_into_clauses(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    articles = [p.strip() for p in ARTICLE_PATTERN.split(text) if p.strip()]
    if len(articles) > 1:
        return articles

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs

    # TODO(3주차+): 토큰 기준 분할·PDF 파서 추가 시 이 폴백 개선 (§12 회칙 형식 다양화)
    return [text[i:i + MAX_CHUNK_CHARS] for i in range(0, len(text), MAX_CHUNK_CHARS)]


async def chunk(state: IndexingState) -> dict:
    return {"chunks": split_into_clauses(state["raw_text"])}
