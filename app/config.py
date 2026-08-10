"""환경 설정 — .env 로드 (pydantic-settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 개발용 기본 토큰. 리포를 볼 수 있는 사람은 누구나 아는 값이므로 운영에서 이 값이
# 남아 있으면 인증이 사실상 없는 것과 같다. /readyz가 실모드에서 이 값을 감지해
# not_ready로 떨어뜨린다(app/api/health.py check_config_ready).
DEFAULT_SERVICE_TOKEN = "dev-service-token-change-me"  # noqa: S105

# 개발용 기본 토큰(아웃바운드용). 리포를 볼 수 있는 사람은 누구나 아는 값이므로 운영에서
# 이 값이 남아 있으면 백엔드 호출 인증이 사실상 없는 것과 같다. /readyz가 실모드에서
# 이 값을 감지해 not_ready로 떨어뜨린다(app/api/health.py check_config_ready).
DEFAULT_BACKEND_SERVICE_TOKEN = "dev-backend-service-token-change-me"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB
    database_url: str = "postgresql://budgetops:budgetops@localhost:5433/budgetops_llm"

    # 인증
    service_token: str = DEFAULT_SERVICE_TOKEN
    backend_service_token: str = DEFAULT_BACKEND_SERVICE_TOKEN

    # LLM
    openai_api_key: str = ""
    mock_llm: bool = True

    # 백엔드 (풀스택 팀)
    backend_base_url: str = "http://localhost:8080"
    mock_backend: bool = True

    # 워커
    worker_poll_interval_sec: float = 2.0
    job_max_attempts: int = 3
    # B-7 고아 잡 회수 — running으로 방치된 잡을 재큐잉하는 한계 시간 (p95 15s 대비 충분)
    worker_visibility_timeout_sec: int = 300

    # 관측 (B3 — langsmith_tracing=true + api_key 설정 시 기동 코드가 LANGCHAIN_* env 주입)
    langsmith_tracing: bool = False
    langsmith_project: str = "budgetops-llm"
    langsmith_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
