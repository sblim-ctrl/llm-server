"""setup_checkpointer_locked — 다중 프로세스 동시 기동 직렬화 계약 (pool.py).

배경(2026-08-09 리뷰): checkpointer.setup()의 마이그레이션은 동시 실행에 안전하지
않아, 신규 DB에서 API(--workers 2) + 잡 워커가 같이 뜨면 UniqueViolation으로 일부
프로세스가 죽었다(3개 중 2개 사망 재현). 1차 수정(블로킹 pg_advisory_lock)은 대기
쿼리의 가상 트랜잭션이 setup()의 CREATE INDEX CONCURRENTLY와 순환 대기해 3개 전부
교착됐다 — 그래서 try-lock + 폴링이 계약이다. 여기서는 DB 없이 호출 순서 계약만
잠근다: setup은 잠금 획득 후에만, 실패해도 잠금 해제, 못 얻으면 폴링, 상한 초과 시
명시적 실패. 실제 Postgres 3프로세스 동시 기동 생존은 리뷰 회신의 실측 절차가 담당.
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
