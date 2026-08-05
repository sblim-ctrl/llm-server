"""영수증 추출 텍스트 파싱 테스트 — 백엔드가 텍스트를 주는 경로 (팀 방향 2026-07-09)."""
from app.graphs.review.nodes.intake_receipt import parse_receipt_text


def test_parses_amount_and_date():
    text = "OO식당\n2026-07-08\n삼겹살 2인분 32,000원\n합계 45,000원"
    r = parse_receipt_text(text)
    assert r.parse_ok is True
    assert r.amount == 45_000   # 최대 금액 = 합계 가정
    assert r.date == "2026-07-08"


def test_plain_number_amount():
    r = parse_receipt_text("결제금액 18000원")
    assert r.amount == 18_000


def test_no_amount_marks_unparseable():
    r = parse_receipt_text("읽을 수 없는 영수증입니다")
    assert r.parse_ok is False   # → 가드레일 receipt_unreadable로 에스컬레이션


# ── 실모드 구조화 추출 (풀스택 협의 2026-08-04 8번 — 상호명 필요) ─────────────

from unittest.mock import AsyncMock, patch  # noqa: E402

from app.graphs.review.nodes.intake_receipt import _intake_from_text  # noqa: E402
from app.schemas.common import ReceiptData  # noqa: E402

TEXT = "교보문고 광화문점\n2026-07-08\n알고리즘 교재 2권\n합계 32,000원"


async def test_mock_mode_uses_regex_only():
    """목 모드는 결정적 경로만 쓴다 — 테스트 재현성 때문."""
    result = await _intake_from_text(TEXT)
    assert result["receipt_data"].amount == 32_000
    assert result["receipt_data"].merchant is None      # 정규식은 상호를 안 뽑는다
    assert "llm_meta" not in result


async def test_real_mode_extracts_merchant_and_items():
    """실모드는 intake 프롬프트로 상호·품목까지 뽑는다 (Vision 경로와 같은 프롬프트)."""
    parsed = ReceiptData(amount=32_000, date="2026-07-08", merchant="교보문고 광화문점",
                         items=["알고리즘 교재 2권"], parse_ok=True)
    with patch("app.graphs.review.nodes.intake_receipt.get_settings") as gs, \
         patch("app.graphs.review.nodes.intake_receipt.chat_structured",
               AsyncMock(return_value=(parsed, {}))):
        gs.return_value.mock_llm = False
        gs.return_value.openai_api_key = "sk-test"
        result = await _intake_from_text(TEXT)

    assert result["receipt_data"].merchant == "교보문고 광화문점"
    assert result["receipt_data"].items == ["알고리즘 교재 2권"]
    assert "intake" in result["llm_meta"]


async def test_real_mode_failure_falls_back_to_regex():
    """추출이 실패해도 금액·날짜는 살린다 — 판독 불능보다 낫다."""
    with patch("app.graphs.review.nodes.intake_receipt.get_settings") as gs, \
         patch("app.graphs.review.nodes.intake_receipt.chat_structured",
               AsyncMock(side_effect=RuntimeError("openai down"))):
        gs.return_value.mock_llm = False
        gs.return_value.openai_api_key = "sk-test"
        result = await _intake_from_text(TEXT)

    assert result["receipt_data"].parse_ok is True
    assert result["receipt_data"].amount == 32_000
    assert "llm_meta" not in result
