"""LangSmith 배선 (B3, §4.3) — main.py(API)·worker.py 기동 시 호출.

별도 TracingWrapper 클래스는 두지 않는다 — langchain은 LANGCHAIN_* 환경변수만
있으면 모든 그래프 실행을 자동 트레이싱하고, 잡별 식별은 invoke config의
run_name/tags/metadata 태깅(C9 형식)으로 충분하다.

C9 태깅 형식(고정): run_name=f"{job_type}:{job_id}" · tags=[team_id] ·
metadata={"prompt_version": ...}. 신규 잡 핸들러 작성 시 langsmith_config()를
그대로 쓰면 형식이 유지된다.
"""
import logging
import os

from app.config import get_settings

logger = logging.getLogger(__name__)


def setup_langsmith() -> bool:
    """설정이 켜져 있으면 LANGCHAIN_* 환경변수 주입. 반환: 활성화 여부."""
    s = get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = s.langsmith_project
    os.environ["LANGCHAIN_API_KEY"] = s.langsmith_api_key
    logger.info("LangSmith tracing ON (project=%s)", s.langsmith_project)
    return True


def langsmith_config(job_type: str, job_id: str, team_id: int,
                     prompt_version: str | None = None, **configurable) -> dict:
    """그래프 invoke용 config — C9 태깅 형식. configurable(thread_id 등)은 병합."""
    config: dict = {
        "run_name": f"{job_type}:{job_id}",
        "tags": [str(team_id)],
        "metadata": {"prompt_version": prompt_version} if prompt_version else {},
    }
    if configurable:
        config["configurable"] = configurable
    return config
