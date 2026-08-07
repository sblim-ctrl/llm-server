"""upsert — 신규 판번호 발급 + 활성화 + 구판 비활성화, 원자적 전환 (§4.4-a).

판번호는 백엔드에서 받지 않는다(2026-08-07 결정) — 여기서 팀·doc_type별
MAX(version)+1로 직접 발급한다. 재인덱싱 중에도 구판으로 심사가 계속되고,
완료 시 한 트랜잭션에서 전환된다. search_rules(3주차)는 version을 명시
고정해 조회하므로(app/tools/search_rules.py 참고) 신구 판이 섞인 상태를
심사가 보는 일은 없다 — active 필터가 아니라 버전 고정이 그 역할을 한다.
"""

from app.db.pool import get_pool
from app.graphs.indexing.state import IndexingState
from app.tools.vector_utils import to_vector_literal


async def upsert(state: IndexingState) -> dict:
    team_id, doc_type = state["team_id"], state["doc_type"]
    chunks, embeddings = state["chunks"], state["embeddings"]

    async with get_pool().connection() as conn:
        async with conn.transaction():
            # 같은 팀·doc_type 인덱싱을 직렬화 — 다음 판번호 발급이 겹치면 두 인덱싱
            # 세트가 같은 번호로 활성화돼 심사가 신구 조항이 섞인 결과를 본다.
            # 현재 워커는 단일 프로세스·순차 폴링이라 실제 경합은 없지만
            # (docker-compose.yml replicas: 1), 발급 로직 자체의 정확성을 위해 건다.
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (team_id,))
            row = await (
                await conn.execute(
                    """SELECT COALESCE(MAX(version), 0) + 1 AS next
                   FROM context_chunks WHERE team_id = %s AND doc_type = %s""",
                    (team_id, doc_type),
                )
            ).fetchone()
            version = row["next"]

            for text, vec in zip(chunks, embeddings, strict=True):
                await conn.execute(
                    """INSERT INTO context_chunks
                       (team_id, doc_type, version, chunk_text, embedding, active)
                       VALUES (%s, %s, %s, %s, %s::vector, true)""",
                    (team_id, doc_type, version, text, to_vector_literal(vec)),
                )
            # 신규 판 활성화와 같은 트랜잭션에서 구판 비활성화 → 원자적 전환
            await conn.execute(
                """UPDATE context_chunks SET active = false
                   WHERE team_id = %s AND doc_type = %s AND version <> %s AND active""",
                (team_id, doc_type, version),
            )

    return {"chunks_indexed": len(chunks), "version": version}
