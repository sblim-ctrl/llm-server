"""intake_receipt — 영수증 OCR·정규화 (Intake 에이전트, REQ-028).

TODO(키 발급 후): GPT-4o Vision으로 Signed URL 영수증 파싱 (parse_receipt 툴).

목 모드 규약:
- receipt_url 없음            → parse_ok=False (영수증 미첨부)
- "mock://receipt?amount=45000&date=2026-07-01" → 해당 값으로 영수증 생성
  (청구와 다른 값을 주면 불일치 케이스를 만들 수 있다 — 골든셋·테스트용)
- 그 외 URL                    → 청구 내용과 일치하는 영수증
"""
from urllib.parse import parse_qs, urlparse

from app.graphs.review.state import ReviewState
from app.schemas.common import ReceiptData


def _mock_receipt_from_url(url: str, default_amount: int, default_date: str) -> ReceiptData:
    params = parse_qs(urlparse(url).query)
    amount = int(params["amount"][0]) if "amount" in params else default_amount
    date = params["date"][0] if "date" in params else default_date
    return ReceiptData(amount=amount, date=date, merchant="(mock)", items=[])


async def intake_receipt(state: ReviewState) -> dict:
    claim = state["claim"]
    receipt_url = state.get("receipt_url")

    if not receipt_url:
        # 영수증 미첨부 — guardrail_gate가 에스컬레이션 판단 근거로 사용
        return {"receipt_data": ReceiptData(parse_ok=False, parse_error="영수증 미첨부")}

    if receipt_url.startswith("mock://receipt"):
        return {"receipt_data": _mock_receipt_from_url(receipt_url, claim.amount, claim.date)}

    # TODO: chat_structured("intake", ...) Vision 호출로 교체
    return {"receipt_data": ReceiptData(
        amount=claim.amount, date=claim.date, merchant="(mock)", items=[claim.title],
    )}
