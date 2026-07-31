"""공유 httpx 클라이언트 (성능 고도화) — 싱글턴·정리·재생성 동작."""

from app.tools import backend_client
from app.tools.backend_client import _client, close_backend_client


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
