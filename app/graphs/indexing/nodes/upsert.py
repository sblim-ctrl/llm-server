"""upsert — 신규 버전 활성화 + 구버전 비활성화, 원자적 전환 (§4.4-a).

재인덱싱 중에도 구버전으로 심사가 계속되고, 완료 시 한 트랜잭션에서 전환된다.
search_rules(3주차) 같은 검색 쿼리(WHERE active)는 신구 버전이 섞인 상태를 절대 보지 않는다.
"""
from app.db.pool import get_pool
from app.graphs.indexing.state import IndexingState


def _to_vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


async def upsert(state: IndexingState) -> dict:
    team_id, doc_type, version = state["team_id"], state["doc_type"], state["version"]
    chunks, embeddings = state["chunks"], state["embeddings"]

    async with get_pool().connection() as conn:
        async with conn.transaction():
            for text, vec in zip(chunks, embeddings, strict=True):
                await conn.execute(
                    """INSERT INTO context_chunks
                       (team_id, doc_type, version, chunk_text, embedding, active)
                       VALUES (%s, %s, %s, %s, %s::vector, true)""",
                    (team_id, doc_type, version, text, _to_vector_literal(vec)),
                )
            # 신규 버전 활성화와 같은 트랜잭션에서 구버전 비활성화 → 원자적 전환
            await conn.execute(
                """UPDATE context_chunks SET active = false
                   WHERE team_id = %s AND doc_type = %s AND version <> %s AND active""",
                (team_id, doc_type, version),
            )

    return {"chunks_indexed": len(chunks)}
