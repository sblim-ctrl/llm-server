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
        "team_id": "t",
        "expense_id": "e-1",
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
    await worker.handle_job(_job("report", payload={"team_id": "t", "period": "2026-06"}))
    assert fin.calls and fin.calls[0][0][1] == "dead"
    assert cb.calls == []


async def test_dead_review_job_sends_escalate_callback(monkeypatch):
    fin, cb = Recorder(), Recorder(ret=True)
    monkeypatch.setattr(worker, "finish_job", fin)
    monkeypatch.setattr(worker, "send_callback", cb)

    async def boom(job):
        raise RuntimeError("graph fail")

    monkeypatch.setattr(worker, "run_review_job", boom)
    await worker.handle_job(_job("review"))
    assert fin.calls[0][0][1] == "dead"
    assert len(cb.calls) == 1
    assert cb.calls[0][0][0]["verdict"] == "escalate"


async def test_succeeded_job_records_meta_totals(monkeypatch):
    fin = Recorder()
    monkeypatch.setattr(worker, "finish_job", fin)

    async def fake_review(job):
        meta = LLMCallMeta(model="gpt-4o", tokens_in=100, tokens_out=20, cost_usd=0.002)
        return {"verdict": "approve"}, {"llm_meta": {"adjudicator": meta}}

    monkeypatch.setattr(worker, "run_review_job", fake_review)
    await worker.handle_job(_job("review", attempts=1))
    args, kwargs = fin.calls[0]
    assert args[1] == "succeeded"
    assert kwargs == {"cost_usd": 0.002, "tokens_in": 100, "tokens_out": 20}


async def test_retry_without_checkpoint_restarts_from_initial_state(monkeypatch):
    """B-7 방어: 체크포인트가 없으면 payload로 initial_state 재구성해 START부터."""
    claim = ExpenseClaim(
        title="t", amount=1000, category="식비", date="2026-07-01", description="d"
    )
    payload = {
        "expense_id": "e-1",
        "team_id": "t",
        "claim": claim.model_dump(),
        "receipt_signed_url": "mock://receipt?amount=1000",
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
