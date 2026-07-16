"""send_callback 재시도 (A-5) — 3회 지수 백오프, 최종 실패는 False (예외 금지).

실모드 경로 검증을 위해 mock_backend=False 설정과 _post_callback을 패치한다.
백오프 sleep도 패치 — 테스트가 3초를 실제로 기다리지 않도록.
"""
from unittest.mock import AsyncMock, patch

import httpx

from app.tools import backend_client
from app.tools.backend_client import send_callback

PAYLOAD = {"jobId": "be-1", "verdict": "approve"}


def _real_mode_settings():
    settings = backend_client.get_settings().model_copy(update={"mock_backend": False})
    return patch("app.tools.backend_client.get_settings", return_value=settings)


async def test_succeeds_first_try_without_retry():
    post = AsyncMock(return_value=None)
    with _real_mode_settings(), patch.object(backend_client, "_post_callback", post):
        assert await send_callback(PAYLOAD) is True
    assert post.await_count == 1


async def test_retries_then_succeeds():
    post = AsyncMock(side_effect=[httpx.ConnectError("down"), None])
    with (_real_mode_settings(),
          patch.object(backend_client, "_post_callback", post),
          patch("app.tools.backend_client.asyncio.sleep", AsyncMock()) as slept):
        assert await send_callback(PAYLOAD) is True
    assert post.await_count == 2
    assert slept.await_count == 1          # 1회 실패 → 1회 백오프


async def test_exhausts_three_attempts_and_returns_false():
    post = AsyncMock(side_effect=httpx.ConnectError("down"))
    with (_real_mode_settings(),
          patch.object(backend_client, "_post_callback", post),
          patch("app.tools.backend_client.asyncio.sleep", AsyncMock()) as slept):
        assert await send_callback(PAYLOAD) is False   # 예외 아님 — 폴링 fallback 위임
    assert post.await_count == 3
    # 백오프는 마지막 실패 뒤엔 없다: 1s, 2s 두 번뿐
    assert [c.args[0] for c in slept.await_args_list] == [1.0, 2.0]


async def test_mock_mode_skips_http_entirely():
    post = AsyncMock()
    with patch.object(backend_client, "_post_callback", post):
        assert await send_callback(PAYLOAD) is True    # 기본 설정 = mock_backend
    assert post.await_count == 0
