"""execute_decision — 실행은 백엔드 소유, 우리는 판정만 확정한다 (C2 콜백 단일화).

이 노드는 전에 백엔드 approve/reject API를 직접 호출했는데, 그 API는 백엔드에
없다(`백엔드_요구_내부API_명세.md` §3 ⑨⑩ "미사용 예정"). 목 모드가 가짜 성공을
돌려줘서 골든셋·테스트에서는 정상으로 보였고, 실연동 첫 호출에서 404로 죽어
자동 승인·반려가 한 건도 성립하지 않았을 것이다.

핵심 검증은 '외부 호출이 일어나지 않는다'는 것이다 — 목 모드에서는 성공처럼
보이므로 반환값만 봐서는 회귀를 잡을 수 없다.
"""
from unittest.mock import AsyncMock, patch

from app.graphs.review.nodes.execute_decision import execute_decision


def _state(verdict: str = "approve") -> dict:
    return {"verdict": verdict, "expense_id": "exp-1", "job_id": "job-1",
            "reasons": None}


async def test_does_not_call_backend_execute_apis():
    """승인·반려 어느 쪽도 백엔드 실행 API를 부르지 않는다 (규율 3).

    backend_client를 통째로 감시해서, 이 노드가 어떤 경로로도 외부 호출을 하지
    않음을 확인한다. 목 모드는 가짜 성공을 주므로 반환값 검사로는 부족하다.
    """
    for verdict in ("approve", "reject"):
        with patch("app.tools.backend_client.approve_expense",
                   new=AsyncMock()) as approve, \
             patch("app.tools.backend_client.reject_expense",
                   new=AsyncMock()) as reject:
            await execute_decision(_state(verdict))
            assert not approve.called, f"{verdict}: 승인 API를 호출하면 안 된다"
            assert not reject.called, f"{verdict}: 반려 API를 호출하면 안 된다"


async def test_records_delegation_with_verdict():
    out = await execute_decision(_state("reject"))
    result = out["execution_result"]
    assert result["status"] == "delegated_to_backend"
    assert result["verdict"] == "reject"


async def test_idempotency_key_is_job_id():
    """콜백 중복 도착 시 백엔드가 이중 처리를 막을 수 있도록 job_id를 남긴다.

    콜백 페이로드의 jobId와 같은 값이어야 백엔드가 대조할 수 있다.
    """
    out = await execute_decision(_state())
    assert out["execution_result"]["idempotency_key"] == "job-1"


async def test_no_network_dependency():
    """백엔드가 꺼져 있어도 동작한다 — 실행 위임이라 외부 의존이 없다."""
    with patch("app.tools.backend_client._client",
               side_effect=AssertionError("HTTP 클라이언트를 만들면 안 된다")):
        out = await execute_decision(_state())
    assert out["execution_result"]["status"] == "delegated_to_backend"
