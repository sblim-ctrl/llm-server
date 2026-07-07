"""search_rules — 회칙 조항 유사도 검색 (§5.1). RuleAuditor 전용 툴.

rule_version을 명시적으로 고정해서 조회한다 — 재인덱싱이 진행 중이어도
이미 시작된 심사는 시작 시점 버전 그대로 끝까지 사용 (§4.4 판정 일관성).
active 플래그만으로 거르면 재인덱싱 중 전환 타이밍에 따라 흔들릴 수 있어
버전 자체를 조건에 명시한다.

주의: MOCK_LLM 모드의 임베딩은 해시 기반이라 의미적 유사도가 없다 — 검색
쿼리(SQL)와 team_id·version 스코프가 맞는지만 검증 가능하고, "진짜 관련 조항이
상위로 오는지"는 실제 임베딩(OpenAI 키)이 붙어야 확인된다.
"""
from app.db.pool import get_pool
from app.llm.client import embed_texts
from app.tools.vector_utils import to_vector_literal


async def search_rules(team_id: str, query: str, version: int, top_k: int = 3) -> list[dict]:
    query_vec = (await embed_texts([query]))[0]
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            """SELECT chunk_text, embedding <=> %s::vector AS distance
               FROM context_chunks
               WHERE team_id = %s AND doc_type = 'rule' AND version = %s
               ORDER BY distance
               LIMIT %s""",
            (to_vector_literal(query_vec), team_id, version, top_k),
        )).fetchall()
    return [{"text": r["chunk_text"], "distance": r["distance"]} for r in rows]
