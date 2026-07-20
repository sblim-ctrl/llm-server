"""LLM 클라이언트 — models.yaml 라우팅 + 목 모드 + 하네스(B2).

MOCK_LLM=true(기본)면 OpenAI 호출 없이 결정적 응답을 돌려준다.
실모드 전환 시 이 파일만 바뀌고 노드 코드는 그대로다.

하네스(2026-07-15, 스프린트 B2):
- Retry: chat=ChatOpenAI(max_retries=3, timeout=30), embeddings=생성자 인자
  (OpenAIEmbeddings는 Runnable이 아니라 .with_retry() 불가 — §8 사각지대)
- PIIMasker: mask_with(멤버 명단)를 주면 user 프롬프트에 mask_names 적용 (§4.3)
- 호출 메타: 반환형이 tuple[T, LLMCallMeta] — 토큰·비용·지연을 노드가 state에
  적재(llm_meta reducer)해 콜백·판례·jobs 집계로 흐른다. usage 추출은
  with_structured_output(include_raw=True) 필수 (기본 모드는 AIMessage를 버림).
"""
import base64
import hashlib
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from app.config import get_settings
from app.middleware.pii_masker import mask_names
from app.schemas.common import LLMCallMeta

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_MODELS_PATH = Path(__file__).resolve().parents[2] / "models.yaml"
_EMBEDDING_DIM = 1536


@lru_cache
def _routing() -> dict:
    return yaml.safe_load(_MODELS_PATH.read_text(encoding="utf-8"))


def model_for(agent: str) -> str:
    return _routing()["agents"][agent]


def embedding_model() -> str:
    return _routing()["embeddings"]


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """models.yaml pricing(USD/1M tokens) 기준 비용. 단가 미등록 모델은 0 (경고만)."""
    price = _routing().get("pricing", {}).get(model)
    if price is None:
        logger.warning("pricing 미등록 모델: %s — cost 0으로 기록", model)
        return 0.0
    return (tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000


def prepare_user_prompt(user: str, mask_with: list[dict] | None) -> str:
    """LLM 전송 직전 user 프롬프트 마스킹 — 순수 함수 (단위 테스트 대상, §4.3).

    mask_with는 팀 멤버 명단([{name, role}]). None/빈 목록이면 원문 그대로 —
    마스킹 실패가 심사를 막지 않는다 (호출부가 명단 조회 실패 시 []를 넘김).
    """
    if not mask_with:
        return user
    return mask_names(user, mask_with)


async def chat_structured(agent: str, system: str, user: str, schema: type[T],
                          mock_response: T | None = None,
                          mask_with: list[dict] | None = None,
                          prompt_version: str = "") -> tuple[T, LLMCallMeta]:
    """구조화 출력 LLM 호출. 목 모드면 mock_response를 그대로 반환.

    반환: (파싱된 응답, 호출 메타). 실명은 mask_with가 주어지면 전송 전에 치환된다.
    """
    settings = get_settings()
    user = prepare_user_prompt(user, mask_with)
    model = model_for(agent)
    started = time.perf_counter()

    if settings.mock_llm or not settings.openai_api_key:
        if mock_response is None:
            raise RuntimeError(f"MOCK_LLM인데 {agent}의 mock_response가 없음")
        logger.info("MOCK LLM call: agent=%s model=%s", agent, model)
        meta = LLMCallMeta(model=model, prompt_version=prompt_version, mock=True,
                           latency_ms=int((time.perf_counter() - started) * 1000))
        return mock_response, meta

    return await _invoke_structured(agent, model, [("system", system), ("user", user)],
                                    schema, prompt_version, started)


async def _invoke_structured(agent: str, model: str, messages: list, schema: type[T],
                             prompt_version: str, started: float) -> tuple[T, LLMCallMeta]:
    """실모드 공통 경로 — 구조화 출력 + usage 추출 + 메타 (chat·vision 공유, A-3/A-6)."""
    settings = get_settings()
    from langchain_openai import ChatOpenAI  # 지연 임포트 — 목 모드에선 불필요

    llm = ChatOpenAI(model=model, api_key=settings.openai_api_key,
                     timeout=30, max_retries=3)
    structured = llm.with_structured_output(schema, include_raw=True)
    result = await structured.ainvoke(messages)
    if result.get("parsing_error"):
        raise ValueError(f"{agent} 구조화 출력 파싱 실패: {result['parsing_error']}")

    usage = getattr(result["raw"], "usage_metadata", None) or {}
    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)
    meta = LLMCallMeta(
        model=model, prompt_version=prompt_version,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost_usd(model, tokens_in, tokens_out),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return result["parsed"], meta


def vision_image_url(image: bytes | str, media_type: str = "image/jpeg") -> str:
    """Vision content block용 이미지 참조 — 순수 함수 (단위 테스트 대상, A-6).

    bytes(백엔드 프록시 fetch — v1.2 '영수증 조회 경로' 방향)는 base64 data URL로,
    str은 http(s) URL 그대로.
    """
    if isinstance(image, bytes):
        return f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
    return image


async def chat_structured_vision(agent: str, system: str, image: bytes | str,
                                 schema: type[T], mock_response: T | None = None,
                                 prompt_version: str = "",
                                 media_type: str = "image/jpeg",
                                 instruction: str = "이 영수증 이미지에서 데이터를 추출하세요.",
                                 ) -> tuple[T, LLMCallMeta]:
    """Vision 구조화 호출 (A-6, 실명세 'LLM 2단계' 중 1차 읽기 전용).

    image: 백엔드 프록시로 받은 bytes 또는 http(s) URL. Retry·타임아웃·메타는
    chat_structured와 동일 하네스(_invoke_structured) 재사용.
    """
    settings = get_settings()
    model = model_for(agent)
    started = time.perf_counter()

    if settings.mock_llm or not settings.openai_api_key:
        if mock_response is None:
            raise RuntimeError(f"MOCK_LLM인데 {agent}의 mock_response가 없음")
        logger.info("MOCK vision call: agent=%s model=%s", agent, model)
        meta = LLMCallMeta(model=model, prompt_version=prompt_version, mock=True,
                           latency_ms=int((time.perf_counter() - started) * 1000))
        return mock_response, meta

    from langchain_core.messages import HumanMessage  # 지연 임포트

    content = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": vision_image_url(image, media_type)}},
    ]
    messages = [("system", system), HumanMessage(content=content)]
    return await _invoke_structured(agent, model, messages, schema, prompt_version, started)


def _mock_embedding(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """해시 기반 결정적 벡터. 의미 유사도는 없지만 차원·재현성은 보장 (개발용).

    [C10] 바이트 동일 텍스트만 distance 0 — 이 성질에 목 E2E들이 의존하므로 변경 시 상호 리뷰.
    """
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

    embeddings = OpenAIEmbeddings(model=embedding_model(), api_key=settings.openai_api_key,
                                  timeout=30, max_retries=3)
    return await embeddings.aembed_documents(texts)
