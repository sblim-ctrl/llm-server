"""LLM 클라이언트 — models.yaml 라우팅 + 목 모드.

MOCK_LLM=true(기본)면 OpenAI 호출 없이 결정적 응답을 돌려준다.
실모드 전환 시 이 파일만 바뀌고 노드 코드는 그대로다.
TODO(2주차): RetryPolicy(지수 백오프 3회, 노드 타임아웃 30s), PIIMasker 미들웨어 (§4.3)
"""
import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_MODELS_PATH = Path(__file__).resolve().parents[2] / "models.yaml"
_EMBEDDING_DIM = 1536


@lru_cache
def model_for(agent: str) -> str:
    routing = yaml.safe_load(_MODELS_PATH.read_text(encoding="utf-8"))
    return routing["agents"][agent]


@lru_cache
def embedding_model() -> str:
    routing = yaml.safe_load(_MODELS_PATH.read_text(encoding="utf-8"))
    return routing["embeddings"]


async def chat_structured(agent: str, system: str, user: str, schema: type[T],
                          mock_response: T | None = None) -> T:
    """구조화 출력 LLM 호출. 목 모드면 mock_response를 그대로 반환."""
    settings = get_settings()
    if settings.mock_llm or not settings.openai_api_key:
        if mock_response is None:
            raise RuntimeError(f"MOCK_LLM인데 {agent}의 mock_response가 없음")
        logger.info("MOCK LLM call: agent=%s model=%s", agent, model_for(agent))
        return mock_response

    from langchain_openai import ChatOpenAI  # 지연 임포트 — 목 모드에선 불필요

    llm = ChatOpenAI(model=model_for(agent), api_key=settings.openai_api_key, timeout=30)
    structured = llm.with_structured_output(schema)
    return await structured.ainvoke([("system", system), ("user", user)])


def _mock_embedding(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """해시 기반 결정적 벡터. 의미 유사도는 없지만 차원·재현성은 보장 (개발용)."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (seed * (dim // len(seed) + 1))[:dim]
    return [(b / 127.5) - 1.0 for b in raw]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """임베딩 생성. 목 모드면 결정적 목 벡터를 반환 (§4.4-a 인덱싱 파이프라인)."""
    settings = get_settings()
    if settings.mock_llm or not settings.openai_api_key:
        logger.info("MOCK embeddings: %d개 텍스트, model=%s", len(texts), embedding_model())
        return [_mock_embedding(t) for t in texts]

    from langchain_openai import OpenAIEmbeddings  # 지연 임포트 — 목 모드에선 불필요

    embeddings = OpenAIEmbeddings(model=embedding_model(), api_key=settings.openai_api_key)
    return await embeddings.aembed_documents(texts)
