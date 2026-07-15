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
                     expense_id: str | None = None, max_attempts: int = 3,
                     dedupe_active: bool = False) -> str:
    """잡 생성. dedupe_active=True면 같은 expense_id의 활성(queued/running) 심사 잡이
    이미 있을 때 새 잡을 만들지 않고 기존 job_id를 반환한다 — 멱등 수락 (§8).
    동시 요청 경합은 uq_jobs_active_review 부분 유니크 인덱스가 DB 레벨에서 보장.
    """
    async with get_pool().connection() as conn:
        if dedupe_active and expense_id is not None:
            # 충돌 직후 기존 잡이 완료되는 좁은 틈이 있어 짧게 재시도 —
            # 전부 빗나가면 아래 일반 삽입으로 진행(그 시점엔 활성 잡이 없다는 뜻)
            for _ in range(3):
                row = await (await conn.execute(
                    """INSERT INTO jobs (expense_id, team_id, type, payload, max_attempts)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (expense_id)
                       WHERE type = 'review' AND status IN ('queued', 'running')
                             AND expense_id IS NOT NULL
                       DO NOTHING
                       RETURNING id""",
                    (expense_id, team_id, job_type, json.dumps(payload), max_attempts),
                )).fetchone()
                if row is not None:
                    return str(row["id"])
                existing = await (await conn.execute(
                    """SELECT id FROM jobs
                       WHERE expense_id = %s AND type = %s AND status IN ('queued', 'running')
                       ORDER BY created_at LIMIT 1""",
                    (expense_id, job_type),
                )).fetchone()
                if existing is not None:
                    return str(existing["id"])
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
