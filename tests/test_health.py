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


# ── 운영 설정 가드 (배포 시 환경변수 누락 감지) ──


def test_mock_mode_config_always_ready():
    """목 모드는 개발·테스트라 기본값이 정상이다."""
    with patch.object(health, "get_settings", return_value=_settings(mock_llm=True)):
        assert health.check_config_ready() == (True, "mock")


def test_real_mode_default_token_not_ready():
    """실모드에 개발용 기본 토큰이 남아 있으면 인증이 없는 것과 같다.

    리포를 볼 수 있으면 누구나 아는 값이라 그대로 뜨면 안 된다.
    """
    with patch.object(health, "get_settings", return_value=_settings(
            mock_llm=False, openai_api_key="sk-x",
            service_token=health.DEFAULT_SERVICE_TOKEN, mock_backend=False)):
        ok, status = health.check_config_ready()
    assert ok is False and status == "default_service_token"


def test_real_mode_mock_backend_not_ready():
    """실모드 LLM이 목 백엔드 데이터로 진짜 판정을 내리는 상태를 막는다."""
    with patch.object(health, "get_settings", return_value=_settings(
            mock_llm=False, openai_api_key="sk-x",
            service_token="real-token", mock_backend=True)):
        ok, status = health.check_config_ready()
    assert ok is False and status == "mock_backend_in_real_mode"


def test_real_mode_properly_configured_is_ready():
    with patch.object(health, "get_settings", return_value=_settings(
            mock_llm=False, openai_api_key="sk-x",
            service_token="real-token", mock_backend=False)):
        assert health.check_config_ready() == (True, "ok")
