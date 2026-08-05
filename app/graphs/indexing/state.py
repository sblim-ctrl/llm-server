"""컨텍스트 인덱싱 파이프라인 상태 (§4.4-a). LLM 미사용 — embeddings만 호출."""
from typing import TypedDict


class IndexingState(TypedDict, total=False):
    team_id: int
    doc_type: str   # rule | category (params는 인덱싱 대상 아님 — app/worker.py 참고)
    version: int
    raw_text: str
    chunks: list[str]
    embeddings: list[list[float]]
    chunks_indexed: int
