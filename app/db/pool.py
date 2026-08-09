"""psycopg3 비동기 커넥션 풀 + 잡 테이블 헬퍼 (ADR-4)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import psycopg
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


# advisory lock 키(int4 쌍의 첫 축). 두 번째 축: setup은 0 고정, HITL 재개는
# hashtext(job_id) — reviews_stream.resume_review와 네임스페이스가 겹치지 않는다.
CHECKPOINTER_SETUP_LOCK = "checkpointer_setup"
_SETUP_LOCK_POLL_SEC = 0.5
_SETUP_LOCK_MAX_WAIT_SEC = 120.0


async def setup_checkpointer_locked(checkpointer: Any) -> None:
    """checkpointer.setup()을 advisory lock으로 직렬화 — 다중 프로세스 동시 기동 안전.

    setup()의 마이그레이션(테이블 생성 + checkpoint_migrations INSERT)은 동시 실행에
    안전하지 않다: 신규 DB에서 API(--workers 2) + 잡 워커, 총 3개 프로세스가 같이
    뜨면 UniqueViolation(checkpoint_migrations_pkey)으로 일부가 죽는다(2026-08-09
    재현 — 3개 중 2개 사망, 첫 배포·데모 전 볼륨 초기화 시나리오).

    잠금 대기는 반드시 **try-lock + sleep 폴링**이어야 한다. 블로킹
    pg_advisory_lock()으로 기다리면 그 대기 쿼리가 가상 트랜잭션을 쥔 채 살아 있고,
    잠금을 쥔 쪽의 setup()이 실행하는 CREATE INDEX CONCURRENTLY는 모든 동시 가상
    트랜잭션의 종료를 기다리므로 서로를 영원히 기다린다 — 2026-08-09 검증에서 3개
    프로세스 전부 교착으로 재현됐다. try-lock은 즉시 반환돼 대기 세션이 idle이
    되므로 인덱스 생성이 진행된다. 세션 수준 잠금이라 잠근 프로세스가 죽어도
    연결이 닫히며 함께 풀린다.
    """
    async with await psycopg.AsyncConnection.connect(
            get_settings().database_url, autocommit=True) as conn:
        waited = 0.0
        while True:
            got = (await (await conn.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s), 0)",
                (CHECKPOINTER_SETUP_LOCK,))).fetchone())[0]
            if got:
                break
            if waited >= _SETUP_LOCK_MAX_WAIT_SEC:
                raise RuntimeError(
                    "checkpointer setup 잠금을 "
                    f"{_SETUP_LOCK_MAX_WAIT_SEC:.0f}초 내에 얻지 못했다 — "
                    "다른 프로세스의 setup이 멈춰 있는지 확인할 것")
            await asyncio.sleep(_SETUP_LOCK_POLL_SEC)
            waited += _SETUP_LOCK_POLL_SEC
        try:
            await checkpointer.setup()
        finally:
            try:
                await conn.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s), 0)",
                    (CHECKPOINTER_SETUP_LOCK,))
            except Exception:
                # 연결이 죽어 unlock이 실패해도 세션 종료가 잠금을 함께 푼다 —
                # 여기서 예외를 흘리면 setup()의 원인 예외를 가린다
                logger.warning("checkpointer setup 잠금 해제 실패 — 연결 종료로 대체",
                               exc_info=True)


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
                        (
                            expense_id,
                            team_id,
                            job_type,
                            json.dumps(payload),
                            max_attempts,
                            external_job_id,
                        ),
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
                    if (
                        external_job_id is not None
                        and existing["external_job_id"] != external_job_id
                    ):
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
                (expense_id, team_id, job_type, json.dumps(payload), max_attempts, external_job_id),
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


async def get_context_status(team_id: int) -> dict[str, Any]:
    """팀의 활성 회칙 인덱스 요약 — 조항 수·버전·인덱싱 시각.

    인덱싱 이력이 없으면 chunk_count 0에 나머지는 None으로 돌려준다(예외 아님).
    회칙이 없는 것은 정상 상태이며, 그 팀은 유형별 기본 정책으로 심사된다.

    이 함수의 반환값 중 version은 GET /v1/context/status 응답에는 실리지 않는다
    (2026-08-07 결정 — 백엔드는 회칙 버전을 안 쓴다). load_context가 심사 시작
    시점의 회칙 판번호를 rule_version에 고정하는 용도로만 이 함수를 재사용한다.
    """
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """SELECT COUNT(*) AS chunk_count,
                          MAX(version) AS version,
                          MAX(created_at) AS indexed_at
                   FROM context_chunks
                   WHERE team_id = %s AND active AND doc_type = 'rule'""",
                (team_id,),
            )
        ).fetchone()
    return row or {"chunk_count": 0, "version": None, "indexed_at": None}


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
