"""워커 신뢰성 단위 테스트 (B-7) — 전부 monkeypatch, DB 무접촉.

reclaim SQL 자체·kill -9 복구는 수동 시나리오(실 DB)로 검증 — 여기서는
배선(호출 여부·인자)과 분기 로직만 검증한다.
"""

from types import SimpleNamespace

import app.worker as worker
from app.schemas.common import ExpenseClaim, LLMCallMeta


def _job(job_type, **over):
    job = {
        "id": "00000000-0000-0000-0000-000000000001",
        "type": job_type,
        "team_id": 11,
        "expense_id": 101,
        "attempts": 3,
        "max_attempts": 3,
        "payload": {},
    }
    job.update(over)
    return job


class Recorder:
    def __init__(self, ret=None):
        self.calls = []
        self.ret = ret

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.ret


async def test_review_result_keeps_observability_dropped_from_callback(monkeypatch):
    """콜백에서 뺀 관측값이 jobs.result에 남는지 (화면_대조_2026-08-03 §4·§5).

    이게 깨지면 콜백 정제가 곧 관측 유실이 된다 — 정제의 전제 조건이라 고정한다.
    """
    from app.schemas.common import Opinion

    final_state = {
        "claim": ExpenseClaim(title="회식", amount=30000, category="식비", date="2026-08-03"),
        "verdict": "approve",
        "confidence": 0.9,
        "opinions": {"rule": Opinion(auditor="rule", verdict="pass", summary="회칙 부합")},
        "mismatch": [],
        "llm_meta": {
            "adjudicator": LLMCallMeta(
                model="gpt-4o", prompt_version="adjudicator/v3", cost_usd=0.002
            )
        },
        "started_at": 100.0,
    }

    class _StubGraph:
        async def ainvoke(self, state, config=None):
            return final_state

    monkeypatch.setattr(worker, "_review_graph", _StubGraph())
    job = _job(
        "review", attempts=1, payload={"jobId": "be-1", "expenseId": 101, "organizationId": 11}
    )
    result, _ = await worker.run_review_job(job)

    assert result["opinions"] == [
        {
            "auditor": "rule",
            "verdict": "pass",
            "summary": "회칙 부합",
            "evidence": [],
            "figures": {},
            "similar_cases": [],
        }
    ]
    assert result["mismatch"] == []
    assert result["model_version"] == "gpt-4o"
    assert result["prompt_version"] == "adjudicator/v3"
    assert result["cost_usd"] == 0.002
    assert result["latency_ms"] > 0


def test_meta_totals_sums_and_handles_empty():
    metas = {
        "a": LLMCallMeta(model="gpt-4o", tokens_in=100, tokens_out=50, cost_usd=0.001),
        "b": LLMCallMeta(model="gpt-4o-mini", tokens_in=10, tokens_out=5, cost_usd=0.0005),
    }
    assert worker._meta_totals({"llm_meta": metas}) == (0.0015, 110, 55)
    assert worker._meta_totals({}) == (0.0, 0, 0)
    assert worker._meta_totals(None) == (0.0, 0, 0)


async def test_dead_non_review_job_sends_no_callback(monkeypatch):
    """B-7: §8 fail-safe 콜백은 지출 심사(review)에 한정 — report 잡 dead 시 미발송."""
    fin, cb = Recorder(), Recorder(ret=True)
    monkeypatch.setattr(worker, "finish_job", fin)
    monkeypatch.setattr(worker, "send_callback", cb)

    async def boom(state, config=None):
        raise RuntimeError("graph fail")

    monkeypatch.setattr(worker, "report_graph", SimpleNamespace(ainvoke=boom))
    await worker.handle_job(_job("report", payload={"team_id": 11, "period": "2026-06"}))
    assert fin.calls and fin.calls[0][0][1] == "dead"
    assert cb.calls == []


async def test_dead_review_job_sends_escalate_callback(monkeypatch):
    fin, cb = Recorder(), Recorder(ret=True)
    monkeypatch.setattr(worker, "finish_job", fin)
    monkeypatch.setattr(worker, "send_callback", cb)

    async def boom(job):
        raise RuntimeError("graph fail")

    # 레지스트리 디스패치(A-2)라 함수 attr가 아닌 JOB_HANDLERS 엔트리를 패치해야 한다
    monkeypatch.setitem(worker.JOB_HANDLERS, "review", boom)
    await worker.handle_job(_job("review"))
    assert fin.calls[0][0][1] == "dead"
    assert len(cb.calls) == 1
    # A-5 합집합: 정식 CallbackPayload camelCase 직렬화 — 백엔드 jobId echo 대조용
    assert cb.calls[0][0][0]["verdict"] == "escalate"
    assert "expenseId" in cb.calls[0][0][0]


async def test_succeeded_job_records_meta_totals(monkeypatch):
    fin = Recorder()
    monkeypatch.setattr(worker, "finish_job", fin)

    async def fake_review(job):
        meta = LLMCallMeta(model="gpt-4o", tokens_in=100, tokens_out=20, cost_usd=0.002)
        return {"verdict": "approve"}, {"llm_meta": {"adjudicator": meta}}

    monkeypatch.setitem(worker.JOB_HANDLERS, "review", fake_review)
    await worker.handle_job(_job("review", attempts=1))
    args, kwargs = fin.calls[0]
    assert args[1] == "succeeded"
    assert kwargs == {"cost_usd": 0.002, "tokens_in": 100, "tokens_out": 20}


async def test_retry_without_checkpoint_restarts_from_initial_state(monkeypatch):
    """B-7 방어: 체크포인트가 없으면 payload로 initial_state 재구성해 START부터."""
    claim = ExpenseClaim(
        title="t", amount=1000, category="식비", date="2026-07-01", description="d"
    )
    # pull 모델 5필드 payload (§0-2) — 지출 상세는 payload에 없고 load_context가 조회
    payload = {
        "jobId": "be-job-1",
        "expenseId": 101,
        "organizationId": 11,
        "receiptPath": "mock://receipt?amount=1000",
    }
    seen = []

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            seen.append(state)
            return {"claim": claim, "verdict": "approve"}

    class NoCkpt:
        async def aget(self, config):
            return None

    class HasCkpt:
        async def aget(self, config):
            return {"checkpoint": "exists"}

    monkeypatch.setattr(worker, "_review_graph", FakeGraph())
    monkeypatch.setattr(worker, "_checkpointer", NoCkpt())
    await worker.run_review_job(_job("review", attempts=2, payload=payload))
    assert isinstance(seen[-1], dict) and seen[-1]["job_id"]  # initial_state 재구성

    monkeypatch.setattr(worker, "_checkpointer", HasCkpt())
    await worker.run_review_job(_job("review", attempts=2, payload=payload))
    assert seen[-1] is None  # 체크포인트 있음 → 재개(input=None)


class FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))


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


async def test_retryable_failure_requeues_without_dead_or_callback(monkeypatch):
    """attempts < max_attempts 실패 → dead 처리·콜백 없이 재큐잉 UPDATE만 실행."""
    fin, cb = Recorder(), Recorder(ret=True)
    monkeypatch.setattr(worker, "finish_job", fin)
    monkeypatch.setattr(worker, "send_callback", cb)

    async def boom(job):
        raise RuntimeError("transient fail")

    monkeypatch.setitem(worker.JOB_HANDLERS, "review", boom)
    conn = FakeConn()
    monkeypatch.setattr(worker, "get_pool", lambda: FakePool(conn))

    job = _job("review", attempts=1, max_attempts=3)
    await worker.handle_job(job)

    assert fin.calls == []  # dead 처리 안 함
    assert cb.calls == []  # 콜백 미발송
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "queued" in sql
    assert params == (job["id"],)


async def test_poll_loop_reclaims_each_cycle(monkeypatch):
    """poll_loop이 매 사이클 reclaim_stale_jobs를 설정된 timeout으로 호출하는지."""
    import app.db.pool as pool

    rec = Recorder(ret=[])

    async def claim_and_stop():
        worker._shutdown.set()
        return None

    monkeypatch.setattr(pool, "reclaim_stale_jobs", rec)
    monkeypatch.setattr(pool, "claim_next_job", claim_and_stop)
    try:
        await worker.poll_loop()
    finally:
        worker._shutdown.clear()
    assert len(rec.calls) == 1
    assert rec.calls[0][0][0] == worker.get_settings().worker_visibility_timeout_sec


# ── 잡 핸들러 레지스트리 (C6 계약) ─────────────────────────────────────────


async def test_proposal_budget_handler_is_registered_and_honours_the_contract(monkeypatch):
    """레지스트리 등록을 지키는 테스트 — 2026-08-06 적대적 리뷰가 지적한 커버리지 공백.

    등록이 빠져도 `handle_job`은 `unknown_job_type`으로 **succeeded 처리**하므로
    실패로 드러나지 않는다. 예산관리 페이지가 조용히 비고 아무 데도 기록이 남지 않는다.

    핸들러 계약(팀 합의 7/20)은 `async (job) -> (result, final_state)`이고, final_state가
    llm_meta를 실어야 B-7 잡 비용 계측(_meta_totals)이 동작한다. 목 모드에서는 합산값이
    0이라 금액을 단언해도 의미가 없어, llm_meta가 실려 오는지를 본다.
    """
    import app.graphs.writers.budget_planner as bp

    assert worker.JOB_HANDLERS["proposal_budget"] is worker.run_proposal_budget_job

    async def fake_save_proposal(team_id, proposal_type, payload):
        return "pid-worker"

    monkeypatch.setattr(bp, "save_proposal", fake_save_proposal)
    result, final = await worker.run_proposal_budget_job(
        _job("proposal_budget", payload={"team_id": 1, "period": "2026-06"})
    )

    assert result["proposal_id"] == "pid-worker"
    assert set(result["payload"]) == {
        "category_analysis",
        "budget_status_analysis",
        "recommendation",
        "figures",
        "verified",
    }
    assert final is not None and "budget_planner" in final["llm_meta"], (
        "final_state에 llm_meta가 없으면 B-7 비용 계측이 조용히 0으로 죽는다"
    )
