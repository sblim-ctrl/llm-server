"""readyz LLM 준비 점검 (§4 Sprint 2 'readyz OpenAI 점검')."""
from unittest.mock import AsyncMock, patch

from app.api import health
from app.api.health import check_llm_ready


def _settings(**over):
    return health.get_settings().model_copy(update=over)


async def test_mock_mode_is_ready_without_key():
    with patch.object(health, "get_settings",
                      return_value=_settings(mock_llm=True, openai_api_key="")):
        assert await check_llm_ready() == (True, "mock")


async def test_real_mode_missing_key_not_ready():
    with patch.object(health, "get_settings",
                      return_value=_settings(mock_llm=False, openai_api_key="")):
        ok, status = await check_llm_ready()
    assert ok is False and status == "missing_key"


async def test_real_mode_shallow_ok_without_api_call():
    """실키 있으면 얕은 확인은 API 호출 없이 configured (probe 비용 0)."""
    with patch.object(health, "get_settings",
                      return_value=_settings(mock_llm=False, openai_api_key="sk-x")):
        assert await check_llm_ready(deep=False) == (True, "configured")


async def test_deep_check_unreachable():
    """deep이고 OpenAI가 안 뜨면 unreachable → not_ready."""
    fake = AsyncMock()
    fake.models.list = AsyncMock(side_effect=RuntimeError("down"))
    with (patch.object(health, "get_settings",
                       return_value=_settings(mock_llm=False, openai_api_key="sk-x")),
          patch("openai.AsyncOpenAI", return_value=fake)):
        ok, status = await check_llm_ready(deep=True)
    assert ok is False and status == "unreachable"


async def test_deep_check_reachable():
    fake = AsyncMock()
    fake.models.list = AsyncMock(return_value=[])
    with (patch.object(health, "get_settings",
                       return_value=_settings(mock_llm=False, openai_api_key="sk-x")),
          patch("openai.AsyncOpenAI", return_value=fake)):
        assert await check_llm_ready(deep=True) == (True, "configured")
