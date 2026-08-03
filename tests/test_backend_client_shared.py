"""공유 httpx 클라이언트 (성능 고도화) — 싱글턴·정리·재생성 동작 + 응답 키 정규화."""

import pytest

from app.tools import backend_client
from app.tools.backend_client import _client, _normalize_budget, close_backend_client


async def test_client_is_reused_and_closed():
    c1 = _client()
    assert _client() is c1  # 호출마다 재생성하지 않음 (연결 풀 재사용)
    await close_backend_client()
    assert c1.is_closed
    assert backend_client._http_client is None  # 정리 후 상태 초기화


async def test_client_recreated_after_close():
    c1 = _client()
    await close_backend_client()
    c2 = _client()
    assert c2 is not c1 and not c2.is_closed  # 종료 후 재요청 시 새로 생성
    await close_backend_client()  # 테스트 뒷정리


# ── 예산 응답 키 정규화 (DB 표기 used_budget / API 표기 usedBudget) ──


def test_normalize_budget_accepts_all_spellings():
    expected = {"total_budget": 300_000, "spent": 118_000}
    assert _normalize_budget({"total_budget": 300_000, "spent": 118_000}) == expected
    assert _normalize_budget({"total_budget": 300_000, "used_budget": 118_000}) == expected
    assert _normalize_budget({"totalBudget": 300_000, "usedBudget": 118_000}) == expected


def test_normalize_budget_raises_when_key_missing():
    """0으로 때우지 않는다 — budget_auditor가 error 소견으로 잡아 에스컬레이션되어야 한다."""
    with pytest.raises(KeyError):
        _normalize_budget({"total_budget": 300_000})
