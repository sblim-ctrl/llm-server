"""A-6 Vision OCR — 헬퍼·intake 배선 단위 테스트 (전부 목/패치, 실키 무접촉).

실제 영수증 이미지 검증(완료 기준)은 실키 후 A-9에서 수행.
"""
import base64
from unittest.mock import AsyncMock, patch

import pytest

from app.graphs.review.nodes import intake_receipt as intake_mod
from app.graphs.review.nodes.intake_receipt import intake_receipt
from app.llm.client import chat_structured_vision, vision_image_url
from app.schemas.common import ExpenseClaim, LLMCallMeta, ReceiptData

CLAIM = ExpenseClaim(title="교재", amount=32000, category="도서", date="2026-07-01")


# ── vision_image_url (순수 함수) ─────────────────────────

def test_bytes_become_base64_data_url():
    url = vision_image_url(b"\x89PNG fake", media_type="image/png")
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG fake"


def test_http_url_passthrough():
    assert vision_image_url("https://r/1.jpg") == "https://r/1.jpg"


# ── chat_structured_vision 목 모드 ───────────────────────

async def test_vision_mock_mode_returns_mock_response():
    mock = ReceiptData(amount=18000, date="2026-07-10")
    data, meta = await chat_structured_vision(
        agent="intake", system="s", image=b"img", schema=ReceiptData,
        mock_response=mock, prompt_version="intake/v1")
    assert data is mock
    assert meta.mock is True and meta.model  # 라우팅 모델 기록


async def test_vision_mock_mode_requires_mock_response():
    with pytest.raises(RuntimeError):
        await chat_structured_vision(agent="intake", system="s", image=b"img",
                                     schema=ReceiptData)


# ── intake_receipt 실모드 배선 ───────────────────────────

def _real_mode():
    s = intake_mod.get_settings().model_copy(
        update={"mock_llm": False, "openai_api_key": "sk-test"})
    return patch.object(intake_mod, "get_settings", return_value=s)


async def test_real_mode_vision_path_returns_data_and_meta():
    vision_data = ReceiptData(amount=32000, date="2026-07-01", merchant="서점")
    fake_vision = AsyncMock(return_value=(vision_data, LLMCallMeta(model="gpt-4o")))
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path", AsyncMock(return_value=b"img")),
          patch.object(intake_mod, "chat_structured_vision", fake_vision)):
        out = await intake_receipt({"claim": CLAIM, "receipt_path": "/api/internal/r/1"})
    assert out["receipt_data"].merchant == "서점"
    assert out["llm_meta"]["intake"].model == "gpt-4o"   # B-7 계측·콜백 합산 재료
    assert fake_vision.await_args.kwargs["image"] == b"img"


async def test_real_mode_backend_none_falls_back_to_url():
    """MOCK_BACKEND 혼합 모드 — fetch가 None이면 URL을 그대로 Vision에 (A-9 스모크 경로)."""
    fake_vision = AsyncMock(return_value=(ReceiptData(amount=1), LLMCallMeta(model="gpt-4o")))
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path", AsyncMock(return_value=None)),
          patch.object(intake_mod, "chat_structured_vision", fake_vision)):
        await intake_receipt({"claim": CLAIM, "receipt_url": "https://r/1.jpg"})
    assert fake_vision.await_args.kwargs["image"] == "https://r/1.jpg"


async def test_real_mode_vision_failure_is_unreadable_not_crash():
    """Vision 실패 → parse_ok=False (guardrail receipt_unreadable → escalate, §8)."""
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path", AsyncMock(return_value=b"img")),
          patch.object(intake_mod, "chat_structured_vision",
                       AsyncMock(side_effect=ValueError("파싱 실패")))):
        out = await intake_receipt({"claim": CLAIM, "receipt_path": "/r/1"})
    assert out["receipt_data"].parse_ok is False


# ── 목 규약 불변 (골든셋 회귀 보증) ──────────────────────

async def test_mock_mode_conventions_unchanged():
    out = await intake_receipt({"claim": CLAIM,
                                "receipt_path": "mock://receipt?amount=25000"})
    assert out["receipt_data"].amount == 25000            # mock:// 오버라이드
    out = await intake_receipt({"claim": CLAIM, "receipt_url": "https://r/1"})
    assert out["receipt_data"].amount == CLAIM.amount     # 청구 일치 목
    out = await intake_receipt({"claim": CLAIM})
    assert out["receipt_data"].parse_ok is False          # 미첨부
