"""reviews_stream — SSE 포맷·노드 라벨 정합 + HITL 재개 동시성 계약.

전체 그래프 실행 검증은 골든셋(eval)·대시보드 수동 경로 담당 — 여기서는
의존성 없는 순수 부분만: SSE 직렬화 형식과, 타임라인 노드 목록이 실제 심사
그래프 배선과 일치하는지(노드 추가·개명 시 드리프트 감지)를 잠근다.

재개(resume_review) 동시성 계약(2026-08-09 리뷰에서 이중 저장 재현 후 추가):
잠금을 못 얻으면 실행 없이 409, 잠금 안 재확인에서 종결이면 409, 성공 경로는
그래프 재개가 정확히 1회에 잠금 해제까지 — DB 없이 가짜 연결/그래프로 검증한다.
실제 Postgres 경합 재현·해소는 리뷰 회신의 실측 절차가 담당.

재개 판정 기준(2026-08-10 리뷰): "관리자 결정 대기 중"인지는 snap.interrupts로만
정확히 판별된다 — snap.next는 진짜 interrupt() 대기뿐 아니라 아직 END에 도달하지
않은 모든 체크포인트(= 다른 요청이 지금 실행 중인 도중)에서도 채워진다. 실제
Postgres 체크포인터로 재현: 1스텝만 실행하고 중단한 체크포인트도 snap.next는
비어있지 않지만 snap.interrupts는 비어있었다.
"""
from types import SimpleNamespace

from app.api import reviews_stream
from app.api.reviews_stream import NODE_LABELS, DecisionRequest, _sse
from app.graphs.review.graph import build_review_graph


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeLockConn:
    """advisory lock 연결 대역 — try_lock 결과를 정해 두고 실행 SQL을 기록한다."""

    def __init__(self, grant: bool, unlock_fails: bool = False):
        self.grant = grant
        self.unlock_fails = unlock_fails
        self.executed: list[str] = []
        self.closed = False

    async def execute(self, sql, params=None):
        self.executed.append(sql)
        if "pg_try_advisory_lock" in sql:
            return _FakeCursor((self.grant,))
        if "pg_advisory_unlock" in sql and self.unlock_fails:
            raise ConnectionError("연결 유실 재현")
        return _FakeCursor((True,))

    async def close(self):
        self.closed = True

    @property
    def unlocked(self) -> bool:
        return any("pg_advisory_unlock" in s for s in self.executed)


class _FakeGraph:
    """hitl_graph 대역 — 상태 스냅숏 고정, 재개 호출 횟수 기록.

    interrupts는 기본 빈 튜플 — next_만 채우고 interrupts를 안 채우면 "실행 중이지만
    interrupt는 아직 없는" 상태를 표현한다(2026-08-10 리뷰가 재현한 바로 그 상태).
    진짜 interrupt 대기를 표현하려면 interrupts에 값을 채워야 한다.
    """

    def __init__(self, next_, interrupts=(), values=None):
        self._snap = SimpleNamespace(next=next_, interrupts=interrupts, values=values or {})
        self.resumed = 0

    async def aget_state(self, config):
        return self._snap

    def astream(self, *args, **kwargs):
        self.resumed += 1

        async def _gen():
            yield {"escalate": {}}

        return _gen()


def _patch_lock_conn(monkeypatch, conn):
    async def _connect(*args, **kwargs):
        return conn

    monkeypatch.setattr(reviews_stream, "AsyncConnection",
                        SimpleNamespace(connect=_connect))


async def test_resume_conflict_rejected_without_touching_graph(monkeypatch):
    """잠금을 못 얻으면(같은 잡 재개 중) 그래프를 건드리지 않고 409."""
    conn = _FakeLockConn(grant=False)
    _patch_lock_conn(monkeypatch, conn)
    monkeypatch.setattr(reviews_stream, "hitl_graph", None)  # 접근하면 즉사 → 검출

    resp = await reviews_stream.resume_review(
        "job-1", DecisionRequest(decision="approve"))

    assert resp.status_code == 409
    assert "재개 중" in resp.body.decode("utf-8")
    assert conn.closed  # 거절 경로도 연결을 정리한다


async def test_resume_recheck_inside_lock_returns_409_when_finished(monkeypatch):
    """잠금 획득 후 재확인 — 직전 재개가 종결한 잡이면 실행 없이 409 + 잠금 해제."""
    conn = _FakeLockConn(grant=True)
    _patch_lock_conn(monkeypatch, conn)
    graph = _FakeGraph(next_=())  # next·interrupts 둘 다 비어있음 = 종결/모르는 잡
    monkeypatch.setattr(reviews_stream, "hitl_graph", graph)

    resp = await reviews_stream.resume_review(
        "job-2", DecisionRequest(decision="approve"))

    assert resp.status_code == 409
    assert "대기 상태가 아닙니다" in resp.body.decode("utf-8")
    assert graph.resumed == 0
    assert conn.unlocked and conn.closed


async def test_resume_rejected_when_checkpoint_has_no_real_interrupt(monkeypatch):
    """snap.next만 채워지고 snap.interrupts가 비어있으면(= interrupt 없이 실행되던
    도중의 체크포인트) 409로 거절하고 그래프를 건드리지 않는다.

    snap.next만 보면 이 상태를 "관리자 결정 대기 중"으로 오판해 재개를 허용해
    버린다 — 이때 Command(resume=...)는 에러 없이 조용히 무시된 채 그래프가 원래
    로직대로 계속 실행된다(관리자가 보낸 결정이 아무 효과 없이 버려짐). 실제
    Postgres 체크포인터로 재현(2026-08-10 리뷰): 1스텝만 실행하고 중단한
    체크포인트는 snap.next=("intake_receipt",)였지만 snap.interrupts=()였다.
    """
    conn = _FakeLockConn(grant=True)
    _patch_lock_conn(monkeypatch, conn)
    # next_는 채워져 있지만(다음 노드가 있음) interrupts는 비어있다 — "실행 중이지만
    # interrupt는 아직 안 걸림" 상태. 종전 체크(`if not snap.next`)는 이걸 통과시켰다.
    graph = _FakeGraph(next_=("intake_receipt",), interrupts=())
    monkeypatch.setattr(reviews_stream, "hitl_graph", graph)

    resp = await reviews_stream.resume_review(
        "job-6", DecisionRequest(decision="approve"))

    assert resp.status_code == 409
    assert "대기 상태가 아닙니다" in resp.body.decode("utf-8")
    assert graph.resumed == 0  # 재개를 시도조차 하지 않는다 — 조용히 무시되지 않는다
    assert conn.unlocked and conn.closed


async def test_resume_success_runs_graph_once_and_releases_lock(monkeypatch):
    """성공 경로 — 재개는 정확히 1회, 스트림 종료 시 잠금 해제·연결 정리."""
    conn = _FakeLockConn(grant=True)
    _patch_lock_conn(monkeypatch, conn)
    graph = _FakeGraph(
        next_=("escalate",), interrupts=("fake-interrupt",), values={"team_id": 9002})
    monkeypatch.setattr(reviews_stream, "hitl_graph", graph)

    resp = await reviews_stream.resume_review(
        "job-3", DecisionRequest(decision="approve"))

    assert resp.status_code == 200
    body = "".join([chunk async for chunk in resp.body_iterator])
    assert "event: result" in body  # 재개가 끝까지 갔다
    assert graph.resumed == 1
    assert conn.unlocked and conn.closed  # 스트림이 끝나야 풀린다


async def test_resume_unlock_failure_does_not_break_response(monkeypatch):
    """연결이 죽어 unlock이 실패해도 응답·스트림 정리는 멀쩡하다.

    해제 예외가 밖으로 흐르면 종결 재확인 409가 500이 되거나 제너레이터 정리가
    오류로 끝난다 — 연결 종료가 세션 잠금을 함께 푸므로 삼키는 것이 계약.
    """
    conn = _FakeLockConn(grant=True, unlock_fails=True)
    _patch_lock_conn(monkeypatch, conn)
    graph = _FakeGraph(
        next_=("escalate",), interrupts=("fake-interrupt",), values={"team_id": 9002})
    monkeypatch.setattr(reviews_stream, "hitl_graph", graph)

    resp = await reviews_stream.resume_review(
        "job-5", DecisionRequest(decision="approve"))
    body = "".join([chunk async for chunk in resp.body_iterator])  # 예외 없이 완주

    assert "event: result" in body
    assert conn.closed  # unlock은 실패했지만 연결은 닫혔다 → 세션 잠금 해제


async def test_resume_stream_failure_still_releases_lock(monkeypatch):
    """재개 중 예외가 나도 잠금은 풀린다 — 안 풀리면 그 잡은 영영 재개 불가."""
    conn = _FakeLockConn(grant=True)
    _patch_lock_conn(monkeypatch, conn)
    graph = _FakeGraph(next_=("escalate",), interrupts=("fake-interrupt",), values={})

    def _boom(*args, **kwargs):
        raise RuntimeError("stream 실패 재현")

    graph.astream = _boom
    monkeypatch.setattr(reviews_stream, "hitl_graph", graph)

    resp = await reviews_stream.resume_review(
        "job-4", DecisionRequest(decision="approve"))
    body = "".join([chunk async for chunk in resp.body_iterator])

    assert "event: error" in body
    assert conn.unlocked and conn.closed


def test_sse_format_and_korean_passthrough():
    out = _sse("node", {"label": "회칙 심사관", "ms": 3})
    assert out.startswith("event: node\ndata: ")
    assert out.endswith("\n\n")                # SSE 이벤트 구분자
    assert '"회칙 심사관"' in out              # ensure_ascii=False — 한글 원문 유지


def test_node_labels_match_review_graph():
    """타임라인이 그리는 노드 == 실제 그래프 노드 (배선 변경 시 여기서 잡힌다)."""
    g = build_review_graph()
    graph_nodes = set(g.get_graph().nodes) - {"__start__", "__end__"}
    assert graph_nodes == set(NODE_LABELS)


def test_node_labels_order_follows_graph_wiring():
    """NODE_LABELS의 나열 순서가 그래프 배선의 위상 순서인지 — set 비교로는 못 잡는다.

    화면 단계 목록이 이 dict 순서 그대로 프론트에 실려 나가는데(steps 이벤트),
    2026-08-06 그래프 순서 변경(intake_receipt를 classify_category 앞으로) 때
    여기가 옛 순서로 남아 3번째 단계가 2번째보다 먼저 켜지는 표시 어긋남이 있었다.
    모든 간선 (u→v)에 대해 u가 v보다 먼저 나열돼야 한다로 잠근다 — 다음 순서
    변경 때는 이 테스트가 잡는다.
    """
    g = build_review_graph().get_graph()
    pos = {n: i for i, n in enumerate(NODE_LABELS)}
    for e in g.edges:
        if e.source in pos and e.target in pos:
            assert pos[e.source] < pos[e.target], (
                f"배선은 {e.source} → {e.target}인데 화면 단계 목록은 "
                f"{e.target}를 먼저 그린다 — NODE_LABELS 순서를 graph.py에 맞출 것"
            )
