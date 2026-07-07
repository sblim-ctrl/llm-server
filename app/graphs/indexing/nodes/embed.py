"""embed — 청크별 임베딩 생성."""
from app.graphs.indexing.state import IndexingState
from app.llm.client import embed_texts


async def embed(state: IndexingState) -> dict:
    if not state["chunks"]:
        return {"embeddings": []}
    vectors = await embed_texts(state["chunks"])
    return {"embeddings": vectors}
