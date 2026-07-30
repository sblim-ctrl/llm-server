"""search_precedents — 유사 판례 검색 (§5.1). PrecedentAuditor 전용 툴.

비활성(active=false) 판례는 제외. team_id 필터 강제 (멀티테넌시, §6).
"""
from app.db.pool import get_pool
from app.llm.client import embed_texts
from app.tools.vector_utils import to_vector_literal


async def search_precedents(team_id: int, query: str, top_k: int = 3) -> list[dict]:
    query_vec = (await embed_texts([query]))[0]
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            """SELECT expense_summary, decision, decided_by, reason, is_override,
                      embedding <=> %s::vector AS distance
               FROM precedents
               WHERE team_id = %s AND active AND embedding IS NOT NULL
               ORDER BY distance
               LIMIT %s""",
            (to_vector_literal(query_vec), team_id, top_k),
        )).fetchall()
    return [dict(r) for r in rows]
