"""intake_receipt — 영수증 OCR·정규화 (Intake 에이전트, REQ-028).

TODO(3주차): GPT-4o Vision으로 Signed URL 영수증 파싱 (parse_receipt 툴).
목 모드: 청구 내용과 일치하는 영수증으로 취급. 영수증이 없으면 parse_ok=False.
"""
from app.graphs.review.state import ReviewState
from app.schemas.common import ReceiptData


async def intake_receipt(state: ReviewState) -> dict:
    claim = state["claim"]
    if not state.get("receipt_url"):
        # 영수증 미첨부 — mismatch_gate가 에스컬레이션 판단 근거로 사용
        return {"receipt_data": ReceiptData(parse_ok=False, parse_error="영수증 미첨부")}

    # TODO: chat_structured("intake", ...) Vision 호출로 교체
    return {"receipt_data": ReceiptData(
        amount=claim.amount, date=claim.date, merchant="(mock)", items=[claim.title],
    )}
