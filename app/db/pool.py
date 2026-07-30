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
            get_settings().database_url,
            min_size=1,
            max_size=10,
            open=False,
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

async def insert_job(
    team_id: int,
    job_type: str,
    payload: dict[str, Any],
    expense_id: int | None = None,
    max_attempts: int = 3,
    dedupe_active: bool = False,
    external_job_id: str | None = None,
) -> str:
    """잡 생성. dedupe_active=True면 같은 expense_id의 활성(queued/running) 심사 잡이
    이미 있을 때 새 잡을 만들지 않고 기존 job_id를 반환한다 — 멱등 수락 (§8).
    동시 요청 경합은 uq_jobs_active_review 부분 유니크 인덱스가 DB 레벨에서 보장.

    external_job_id: 백엔드가 발급한 jobId (pull 모델). 활성 잡에 dedupe될 때는
    최신 external_job_id로 갱신한다 — 재제출 시 백엔드는 옛 jobId를 무효화하므로
    콜백이 최신 값을 echo해야 무시당하지 않는다 (이미 실행에 들어간 잡의 체크포인트
    상태까지는 못 바꾸므로, 그 경우 옛 jobId 콜백은 백엔드 폴링 안전망에 위임).
    """
    async with get_pool().connection() as conn:
        if dedupe_active and expense_id is not None:
            # 충돌 직후 기존 잡이 완료되는 좁은 틈이 있어 짧게 재시도 —
            # 전부 빗나가면 아래 일반 삽입으로 진행(그 시점엔 활성 잡이 없다는 뜻)
            for _ in range(3):
                row = await (
                    await conn.execute(
                        """INSERT INTO jobs (expense_id, team_id, type, payload,
                                             max_attempts, external_job_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (expense_id)
                       WHERE type = 'review' AND status IN ('queued', 'running')
                             AND expense_id IS NOT NULL
                       DO NOTHING
                       RETURNING id""",
                        (expense_id, team_id, job_type, json.dumps(payload),
                         max_attempts, external_job_id),
                    )
                ).fetchone()
                if row is not None:
                    return str(row["id"])
                existing = await (
                    await conn.execute(
                        """SELECT id, external_job_id FROM jobs
                       WHERE expense_id = %s AND type = %s AND status IN ('queued', 'running')
                       ORDER BY created_at LIMIT 1""",
                        (expense_id, job_type),
                    )
                ).fetchone()
                if existing is not None:
                    if (external_job_id is not None
                            and existing["external_job_id"] != external_job_id):
                        # 컬럼은 무조건 최신화(백엔드가 새 jobId로 폴링 조회하므로),
                        # payload의 job_id는 큐 대기 중일 때만 — 워커가 초기 상태를
                        # payload에서 만들기 때문 (이미 실행 중이면 체크포인트가 진실)
                        await conn.execute(
                            """UPDATE jobs
                               SET external_job_id = %s,
                                   payload = CASE WHEN status = 'queued'
                                       THEN payload || jsonb_build_object('job_id', %s::text)
                                       ELSE payload END,
                                   updated_at = now()
                               WHERE id = %s""",
                            (external_job_id, external_job_id, existing["id"]),
                        )
                    return str(existing["id"])
        row = await (
            await conn.execute(
                """INSERT INTO jobs (expense_id, team_id, type, payload,
                                     max_attempts, external_job_id)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (expense_id, team_id, job_type, json.dumps(payload),
                 max_attempts, external_job_id),
            )
        ).fetchone()
    return str(row["id"])


async def get_job(job_id: str) -> dict[str, Any] | None:
    """내부 UUID 또는 백엔드 발급 jobId(external_job_id) 어느 쪽으로도 조회 가능 —
    백엔드 폴링 fallback은 자기가 발급한 jobId로 물어본다."""
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """SELECT * FROM jobs
               WHERE id::text = %s OR external_job_id = %s
               ORDER BY created_at DESC LIMIT 1""",
                (job_id, job_id),
            )
        ).fetchone()


async def claim_next_job() -> dict[str, Any] | None:
    """FOR UPDATE SKIP LOCKED으로 경합 없이 잡 1건 선점 → running 전환."""
    async with get_pool().connection() as conn:
        async with conn.transaction():
            row = await (
                await conn.execute(
                    """SELECT id FROM jobs
                   WHERE status = 'queued'
                   ORDER BY created_at
                   FOR UPDATE SKIP LOCKED
                   LIMIT 1"""
                )
            ).fetchone()
            if row is None:
                return None
            return await (
                await conn.execute(
                    """UPDATE jobs
                   SET status = 'running', attempts = attempts + 1, updated_at = now()
                   WHERE id = %s RETURNING *""",
                    (row["id"],),
                )
            ).fetchone()


async def reclaim_stale_jobs(timeout_sec: int) -> list[str]:
    """고아 잡 회수 (B-7) — 워커 크래시로 running에 갇힌 잡을 재큐잉 (visibility timeout).

    updated_at은 claim·재큐 시점에 갱신되므로, timeout보다 오래 방치된 running은
    워커가 죽은 것으로 간주한다. 알려진 허용 동작: attempts==max에서 크래시한 잡은
    회수 후 1회 더 실행된 뒤 dead — 무한 루프 아님. 정상 실행이 timeout을 넘기면
    이중 실행 가능성이 있으나 단일 워커·p95 15s 전제에서 오탐 없음.
    """
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """UPDATE jobs SET status = 'queued', updated_at = now()
               WHERE status = 'running'
                 AND updated_at < now() - make_interval(secs => %s)
               RETURNING id""",
                (timeout_sec,),
            )
        ).fetchall()
    return [str(r["id"]) for r in rows]


async def finish_job(
    job_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    cost_usd: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    """잡 종료 기록. cost/tokens는 llm_meta 합산치 (B-7 계측) — 기본값 인자로 하위호환."""
    async with get_pool().connection() as conn:
        await conn.execute(
            """UPDATE jobs SET status = %s, result = %s, cost_usd = %s,
                   tokens_in = %s, tokens_out = %s, updated_at = now()
               WHERE id = %s""",
            (
                status,
                json.dumps(result) if result is not None else None,
                cost_usd,
                tokens_in,
                tokens_out,
                job_id,
            ),
        )
