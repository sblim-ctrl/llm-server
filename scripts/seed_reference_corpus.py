"""PolicyDrafter 참고 규정 코퍼스 시딩 — reference_docs/*.txt → pgvector.

실행: uv run python scripts/seed_reference_corpus.py  (llm-postgres 필요)
재실행 가능 — 매번 기존 참고자료를 지우고 다시 넣는다(버전 관리 불필요,
팀 회칙과 달리 재인덱싱 중 심사가 진행될 일이 없는 정적 전역 자료라서).
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, get_pool, open_pool  # noqa: E402
from app.graphs.indexing.nodes.chunk import split_into_clauses  # noqa: E402
from app.llm.client import embed_texts  # noqa: E402
from app.tools.search_references import REFERENCE_SCOPE  # noqa: E402
from app.tools.vector_utils import to_vector_literal  # noqa: E402

DOCS_DIR = ROOT / "reference_docs"


async def main() -> None:
    await open_pool()
    await apply_schema()
    try:
        async with get_pool().connection() as conn:
            await conn.execute(
                "DELETE FROM context_chunks WHERE team_id = %s AND doc_type = 'reference'",
                (REFERENCE_SCOPE,))

        total_chunks = 0
        for path in sorted(DOCS_DIR.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            chunks = split_into_clauses(text)
            embeddings = await embed_texts(chunks)

            async with get_pool().connection() as conn:
                for chunk_text, vec in zip(chunks, embeddings, strict=True):
                    await conn.execute(
                        """INSERT INTO context_chunks
                           (team_id, doc_type, version, chunk_text, embedding, active)
                           VALUES (%s, 'reference', 1, %s, %s::vector, true)""",
                        (REFERENCE_SCOPE, chunk_text, to_vector_literal(vec)),
                    )
            print(f"{path.name}: {len(chunks)}개 청크 인덱싱")
            total_chunks += len(chunks)

        print(f"\n총 {total_chunks}개 청크 시딩 완료 (team_id={REFERENCE_SCOPE})")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
