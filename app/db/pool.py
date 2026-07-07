"""psycopg3 비동기 커넥션 풀 + 잡 테이블 헬퍼 (ADR-4)."""
import json
import logging
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            get_settings().database_url, min_size=1, max_size=10, open=False,
            kwargs={"row_factory": dict_row},
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    assert _pool is not None, "pool not opened — lifespan에서 open_pool() 필요"
    return _pool


async def apply_schema() -> None:
    """schema.sql을 idempotent하게 적용 (TODO: alembic 전환)."""
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    async with get_pool().connection() as conn:
        await conn.execute(sql)
    logger.info("DB schema applied")


# ── jobs 헬퍼 ─────────────────────────────────────────────

async def insert_job(team_id: str, job_type: str, payload: dict[str, Any],
                     expense_id: str | None = None, max_attempts: int = 3) -> str:
    async with get_pool().connection() as conn:
        row = await (await conn.execute(
            """INSERT INTO jobs (expense_id, team_id, type, payload, max_attempts)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (expense_id, team_id, job_type, json.dumps(payload), max_attempts),
        )).fetchone()
    return str(row["id"])


async def get_job(job_id: str) -> dict[str, Any] | None:
    async with get_pool().connection() as conn:
        return await (await conn.execute(
            "SELECT * FROM jobs WHERE id = %s", (job_id,),
        )).fetchone()


async def claim_next_job() -> dict[str, Any] | None:
    """FOR UPDATE SKIP LOCKED으로 경합 없이 잡 1건 선점 → running 전환."""
    async with get_pool().connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                """SELECT id FROM jobs
                   WHERE status = 'queued'
                   ORDER BY created_at
                   FOR UPDATE SKIP LOCKED
                   LIMIT 1"""
            )).fetchone()
            if row is None:
                return None
            return await (await conn.execute(
                """UPDATE jobs
                   SET status = 'running', attempts = attempts + 1, updated_at = now()
                   WHERE id = %s RETURNING *""",
                (row["id"],),
            )).fetchone()


async def finish_job(job_id: str, status: str, result: dict[str, Any] | None = None) -> None:
    async with get_pool().connection() as conn:
        await conn.execute(
            "UPDATE jobs SET status = %s, result = %s, updated_at = now() WHERE id = %s",
            (status, json.dumps(result) if result is not None else None, job_id),
        )
