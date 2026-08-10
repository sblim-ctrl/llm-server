"""apply_schema_locked·setup_checkpointer_locked — 다중 프로세스 동시 기동 직렬화 계약 (pool.py).

배경(2026-08-09 리뷰): checkpointer.setup()의 마이그레이션은 동시 실행에 안전하지
않아, 신규 DB에서 API(--workers 2) + 잡 워커가 같이 뜨면 UniqueViolation으로 일부
프로세스가 죽었다(3개 중 2개 사망 재현). 1차 수정(블로킹 pg_advisory_lock)은 대기
쿼리의 가상 트랜잭션이 setup()의 CREATE INDEX CONCURRENTLY와 순환 대기해 3개 전부
교착됐다 — 그래서 try-lock + 폴링이 계약이다. 여기서는 DB 없이 호출 순서 계약만
잠근다: setup은 잠금 획득 후에만, 실패해도 잠금 해제, 못 얻으면 폴링, 상한 초과 시
명시적 실패. 실제 Postgres 3프로세스 동시 기동 생존은 리뷰 회신의 실측 절차가 담당.

추가 배경(2026-08-10 교차 검증): 위 수정이 막는 건 checkpointer.setup()의 경쟁뿐이고,
그보다 먼저 잠금 없이 실행되는 apply_schema()에 같은 클래스의 결함이 남아 있었다 —
schema.sql의 CREATE EXTENSION IF NOT EXISTS vector가 신규 DB 동시 실행에서
UniqueViolation(pg_extension_name_index)으로 죽는다(순수 apply_schema() 동시 호출
3/3 재현, 실제 API+워커 토폴로지에서도 3개 중 2개 사망 1회 재현). apply_schema_locked가
같은 try-lock+폴링 패턴으로 이를 막는다 — 아래 테스트는 두 함수에 동일한 계약을 검증한다.

2026-08-10 후속: 위 재현으로 발견된 apply_schema()의 잠금 미적용이 scripts/·eval/ 14개
호출부에도 그대로 남아 있어, 잠금을 apply_schema() 자체에 내장했다(apply_schema_locked는
하위 호환 별칭). 이 파일의 _patch_apply_schema는 이제 내부 함수 _apply_schema_unlocked를
패치한다 — pool.apply_schema 자체가 잠금 로직이 됐기 때문이다.
"""

import psycopg
import pytest

from app.db import pool


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeConn:
    """try-lock 응답 시퀀스를 정해 두고 실행 순서를 기록한다 (소진 후엔 False)."""

    def __init__(self, log, grants):
        self.log = log
        self._grants = list(grants)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.log.append("close")
        return False

    unlock_fails = False

    async def execute(self, sql, params=None):
        if "pg_try_advisory_lock" in sql:
            g = self._grants.pop(0) if self._grants else False
            self.log.append(f"try:{g}")
            return _FakeCursor((g,))
        if "pg_advisory_unlock" in sql:
            self.log.append("unlock")
            if self.unlock_fails:
                raise ConnectionError("연결 유실 재현")
        return _FakeCursor((True,))


class _FakeCheckpointer:
    def __init__(self, log, fail=False):
        self.log = log
        self.fail = fail

    async def setup(self):
        self.log.append("setup")
        if self.fail:
            raise RuntimeError("마이그레이션 실패 재현")


def _patch(monkeypatch, log, grants):
    async def _connect(*args, **kwargs):
        return _FakeConn(log, grants)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", staticmethod(_connect))
    monkeypatch.setattr(pool, "_SETUP_LOCK_POLL_SEC", 0.001)  # 폴링 대기 최소화


async def test_setup_runs_only_after_lock_granted(monkeypatch):
    """첫 시도에 잠금을 얻으면: 획득 → setup → 해제 → 연결 정리."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])

    await pool.setup_checkpointer_locked(_FakeCheckpointer(log))

    assert log == ["try:True", "setup", "unlock", "close"]


async def test_setup_polls_with_trylock_until_free(monkeypatch):
    """잠금이 차 있으면 블로킹 대기가 아니라 try-lock 폴링으로 기다린다.

    블로킹 pg_advisory_lock 대기는 활성 쿼리로 남아 setup()의 CREATE INDEX
    CONCURRENTLY와 교착한다(모듈 docstring) — try 호출이 여러 번 찍히는 것이
    그 계약의 증거다.
    """
    log: list[str] = []
    _patch(monkeypatch, log, grants=[False, False, True])

    await pool.setup_checkpointer_locked(_FakeCheckpointer(log))

    assert log == ["try:False", "try:False", "try:True", "setup", "unlock", "close"]


async def test_setup_failure_still_unlocks(monkeypatch):
    """setup이 죽어도 잠금은 풀린다 — 안 풀리면 다른 프로세스 기동이 영영 막힌다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])

    with pytest.raises(RuntimeError, match="마이그레이션 실패"):
        await pool.setup_checkpointer_locked(_FakeCheckpointer(log, fail=True))

    assert log == ["try:True", "setup", "unlock", "close"]


async def test_setup_success_survives_unlock_failure(monkeypatch):
    """unlock이 실패해도(연결 유실) setup 성공이 예외로 바뀌지 않는다 —
    연결 종료가 세션 잠금을 함께 푼다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])
    _FakeConn.unlock_fails = True
    try:
        await pool.setup_checkpointer_locked(_FakeCheckpointer(log))
    finally:
        _FakeConn.unlock_fails = False

    assert log == ["try:True", "setup", "unlock", "close"]


async def test_setup_gives_up_after_max_wait(monkeypatch):
    """상한을 넘도록 잠금을 못 얻으면 조용히 돌지 않고 명시적으로 실패한다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[])  # 영원히 False
    monkeypatch.setattr(pool, "_SETUP_LOCK_MAX_WAIT_SEC", 0.003)

    with pytest.raises(RuntimeError, match="잠금"):
        await pool.setup_checkpointer_locked(_FakeCheckpointer(log))

    assert "setup" not in log  # 잠금 없이 setup이 실행된 적 없다
    assert log[-1] == "close"


def _patch_apply_schema(monkeypatch, log, fail=False):
    async def _fake_apply_schema():
        log.append("apply_schema")
        if fail:
            raise RuntimeError("스키마 적용 실패 재현")

    monkeypatch.setattr(pool, "_apply_schema_unlocked", _fake_apply_schema)


async def test_schema_apply_runs_only_after_lock_granted(monkeypatch):
    """첫 시도에 잠금을 얻으면: 획득 → apply_schema → 해제 → 연결 정리."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])
    _patch_apply_schema(monkeypatch, log)

    await pool.apply_schema_locked()

    assert log == ["try:True", "apply_schema", "unlock", "close"]


async def test_schema_apply_polls_with_trylock_until_free(monkeypatch):
    """잠금이 차 있으면 setup_checkpointer_locked과 동일하게 try-lock 폴링으로 기다린다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[False, False, True])
    _patch_apply_schema(monkeypatch, log)

    await pool.apply_schema_locked()

    assert log == ["try:False", "try:False", "try:True", "apply_schema", "unlock", "close"]


async def test_schema_apply_failure_still_unlocks(monkeypatch):
    """apply_schema가 죽어도 잠금은 풀린다 — 안 풀리면 다른 프로세스 기동이 영영 막힌다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])
    _patch_apply_schema(monkeypatch, log, fail=True)

    with pytest.raises(RuntimeError, match="스키마 적용 실패"):
        await pool.apply_schema_locked()

    assert log == ["try:True", "apply_schema", "unlock", "close"]


async def test_schema_apply_success_survives_unlock_failure(monkeypatch):
    """unlock이 실패해도(연결 유실) apply_schema 성공이 예외로 바뀌지 않는다 —
    연결 종료가 세션 잠금을 함께 푼다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[True])
    _patch_apply_schema(monkeypatch, log)
    _FakeConn.unlock_fails = True
    try:
        await pool.apply_schema_locked()
    finally:
        _FakeConn.unlock_fails = False

    assert log == ["try:True", "apply_schema", "unlock", "close"]


async def test_schema_apply_gives_up_after_max_wait(monkeypatch):
    """상한을 넘도록 잠금을 못 얻으면 조용히 돌지 않고 명시적으로 실패한다."""
    log: list[str] = []
    _patch(monkeypatch, log, grants=[])  # 영원히 False
    _patch_apply_schema(monkeypatch, log)
    monkeypatch.setattr(pool, "_SETUP_LOCK_MAX_WAIT_SEC", 0.003)

    with pytest.raises(RuntimeError, match="잠금"):
        await pool.apply_schema_locked()

    assert "apply_schema" not in log  # 잠금 없이 apply_schema가 실행된 적 없다
    assert log[-1] == "close"


def test_schema_apply_and_checkpointer_setup_use_different_lock_keys():
    """두 잠금이 같은 정수 키로 겹치면 무관한 프로세스끼리 서로 막는다 — 반드시 달라야 한다."""
    assert pool.SCHEMA_APPLY_LOCK != pool.CHECKPOINTER_SETUP_LOCK


def test_apply_schema_locked_is_alias_for_apply_schema():
    """apply_schema_locked는 apply_schema()의 별칭이다 — 별도 함수가 아니라 같은 객체를
    가리켜야 app/main.py·app/worker.py를 고치지 않고도 동시 기동 잠금이 적용된다."""
    assert pool.apply_schema_locked is pool.apply_schema
