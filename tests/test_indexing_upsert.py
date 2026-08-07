"""upsert — 판번호 발급(MAX(version)+1) 배선 검증. 실 DB 없이 FakeConn으로 단위 테스트.

COALESCE(MAX(version), 0) + 1 계산 자체는 Postgres가 한다 — 여기서는 검증하지 않는다
(실DB가 필요한 영역, scripts/smoke_review.py --db 또는 수동 통합 테스트 몫). 이 테스트가
잠그는 것은 SELECT가 돌려준 next가 흔들림 없이 그대로 쓰이는지다: 모든 INSERT의
version이 그 값이고, UPDATE가 비활성화 대상에서 그 버전을 제외하며, 반환값 version도
같은 수인지 (app/graphs/indexing/nodes/upsert.py 참고).

FakeConn/FakeConnCtx/FakePool은 tests/test_worker_recovery.py의 DB 목킹 패턴을
transaction()·cursor.fetchone() 지원으로 확장한 것이다.
"""

from app.graphs.indexing.nodes import upsert as upsert_mod


class FakeCursor:
    def __init__(self, row=None):
        self._row = row

    async def fetchone(self):
        return self._row


class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, next_version: int):
        self.next_version = next_version
        self.executed: list[tuple[str, tuple]] = []

    def transaction(self):
        return _NullCtx()

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "COALESCE(MAX(version)" in sql:
            return FakeCursor({"next": self.next_version})
        return FakeCursor()


class FakeConnCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def connection(self):
        return FakeConnCtx(self.conn)


async def test_upsert_issues_next_version_and_uses_it_consistently(monkeypatch):
    conn = FakeConn(next_version=3)
    monkeypatch.setattr(upsert_mod, "get_pool", lambda: FakePool(conn))

    out = await upsert_mod.upsert(
        {
            "team_id": 1,
            "doc_type": "rule",
            "chunks": ["제1조", "제2조"],
            "embeddings": [[0.1, 0.2], [0.3, 0.4]],
        }
    )

    assert out == {"chunks_indexed": 2, "version": 3}

    insert_calls = [c for c in conn.executed if "INSERT INTO context_chunks" in c[0]]
    assert len(insert_calls) == 2
    assert all(params[2] == 3 for _, params in insert_calls)  # (team_id, doc_type, version, ...)

    update_calls = [c for c in conn.executed if "UPDATE context_chunks" in c[0]]
    assert len(update_calls) == 1
    _, update_params = update_calls[0]
    assert update_params == (1, "rule", 3)  # team_id, doc_type, version <> 3(신판 제외)


async def test_upsert_first_indexing_starts_at_version_1(monkeypatch):
    """이 팀의 첫 인덱싱(MAX가 NULL)이면 COALESCE가 1을 준다."""
    conn = FakeConn(next_version=1)
    monkeypatch.setattr(upsert_mod, "get_pool", lambda: FakePool(conn))

    out = await upsert_mod.upsert(
        {"team_id": 5, "doc_type": "rule", "chunks": ["제1조"], "embeddings": [[0.1]]}
    )
    assert out["version"] == 1
