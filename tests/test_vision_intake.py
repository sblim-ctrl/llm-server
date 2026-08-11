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


# ── 영수증 형식 판별 · PDF 경로 (2026-08-11 배포 데모 결함) ──────────────────
#
# media_type 기본값(image/jpeg) 고정 탓에 무엇이 오든 data:image/jpeg로 감싸 보냈다.
# PDF는 Vision이 받지 못해 전건 판독 실패 → receipt_unreadable → 에스컬레이션이었다.

from app.graphs.review.nodes.intake_receipt import detect_media_type  # noqa: E402


def test_detect_media_type_reads_magic_bytes_not_extension():
    assert detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_media_type(b"GIF89a...") == "image/gif"
    assert detect_media_type(b"RIFF\x00\x00\x00\x00WEBPrest") == "image/webp"
    assert detect_media_type(b"%PDF-1.7 rest") == "application/pdf"
    assert detect_media_type(b"who knows") is None


async def test_png_receipt_is_not_labeled_as_jpeg():
    """PNG를 image/jpeg로 감싸던 것이 결함의 절반이었다."""
    fake_vision = AsyncMock(return_value=(ReceiptData(amount=1), LLMCallMeta(model="gpt-4o")))
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path",
                       AsyncMock(return_value=b"\x89PNG\r\n\x1a\nbody")),
          patch.object(intake_mod, "chat_structured_vision", fake_vision)):
        await intake_receipt({"claim": CLAIM, "receipt_path": "/r/1"})
    assert fake_vision.await_args.kwargs["media_type"] == "image/png"


async def test_pdf_receipt_uses_text_layer_instead_of_vision():
    """텍스트 레이어가 있는 PDF(카드전표·전자영수증)는 Vision 없이 읽힌다."""
    fake_vision = AsyncMock()
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path",
                       AsyncMock(return_value=b"%PDF-1.7 fake")),
          patch.object(intake_mod, "pdf_receipt_text",
                       lambda _d: "ANTHROPIC CLAUDE SUB 33,236원 2026-07-23 승인"),
          patch.object(intake_mod, "chat_structured_vision", fake_vision)):
        out = await intake_receipt({"claim": CLAIM, "receipt_path": "/r/1"})
    fake_vision.assert_not_awaited()                       # Vision에 안 보낸다
    assert out["receipt_data"].parse_ok is True
    assert out["receipt_data"].amount == 33236


async def test_scanned_pdf_without_text_is_unreadable_with_clear_reason():
    """스캔 이미지 PDF는 판독 불능 — 다만 사유가 'Vision 오류'가 아니라 원인을 밝힌다."""
    with (_real_mode(),
          patch.object(intake_mod, "get_receipt_by_path",
                       AsyncMock(return_value=b"%PDF-1.7 scanned")),
          patch.object(intake_mod, "pdf_receipt_text", lambda _d: "")):
        out = await intake_receipt({"claim": CLAIM, "receipt_path": "/r/1"})
    assert out["receipt_data"].parse_ok is False
    assert "PDF" in out["receipt_data"].parse_error


def test_pdf_receipt_text_returns_empty_on_corrupt_file():
    """손상 PDF는 예외를 밖으로 던지지 않는다 — 판독 불능으로 수렴(§8)."""
    from app.graphs.review.nodes.intake_receipt import pdf_receipt_text
    assert pdf_receipt_text(b"%PDF-1.7 truncated garbage") == ""
