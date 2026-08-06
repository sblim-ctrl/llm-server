"""search_references — 회칙 참고 규정 문서 검색 (PolicyDrafter RAG).

팀 전용이 아닌 전역(global) 자료라 context_chunks의 team_id 자리에 고정
센티널 값을 써서 재사용한다 — 벡터DB를 새로 늘리지 않고 기존 인덱싱
인프라(pgvector, embed_texts)를 그대로 쓰기 위한 선택.

주의: 목 모드 임베딩은 해시 기반이라 의미적 유사도가 없다 — 검색 메커니즘
(SQL·스코프) 자체는 검증되지만 "관련 문서가 상위로 오는지"는 실제 임베딩
(OpenAI 키)이 붙어야 확인된다 (search_rules.py와 동일한 한계).
"""

from app.db.pool import get_pool
from app.llm.client import embed_texts
from app.tools.vector_utils import to_vector_literal

# context_chunks.team_id 센티널 (전역 자료). team_id가 BIGINT로 전환된 뒤로는
# 문자열 센티널을 넣을 수 없다(T9 후속) — 실 백엔드 team_id는 항상 양수이므로
# 0을 "팀 없음"으로 예약한다.
REFERENCE_SCOPE = 0


async def search_references(query: str, top_k: int = 3) -> list[dict]:
    query_vec = (await embed_texts([query]))[0]
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT chunk_text, embedding <=> %s::vector AS distance
               FROM context_chunks
               WHERE team_id = %s AND doc_type = 'reference' AND active
               ORDER BY distance
               LIMIT %s""",
                (to_vector_literal(query_vec), REFERENCE_SCOPE, top_k),
            )
        ).fetchall()
    return [{"text": r["chunk_text"], "distance": r["distance"]} for r in rows]
