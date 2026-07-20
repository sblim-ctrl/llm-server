"""intake_receipt — 영수증 OCR·정규화 (Intake 에이전트, REQ-028, A-6).

영수증 참조는 두 경로로 온다 (우선순위 순):
- receipt_path — 실계약(pull 모델): 백엔드가 준 '조회 경로'로 Agent 토큰 재요청
  (bravo 설계서 4절). 실모드에선 get_receipt_by_path(seam) → GPT-4o Vision OCR.
- receipt_url  — 구 계약 잔재: 직접 그래프 호출(smoke·seed_demo)·목 오버라이드용.

실모드(A-6): fetch(bytes) → chat_structured_vision(읽기 전용 intake 프롬프트,
스키마 강제) → ReceiptData. 어떤 실패(경로 fetch·Vision 예외·스키마 불일치)도
parse_ok=False로 수렴 — guardrail_gate의 receipt_unreadable 에스컬레이션 경로
불변 (§8: 어떤 실패도 자동 승인으로 이어지지 않는다).

목 모드 규약 (path/url 공통 — A-6 이후에도 불변, 골든셋 30건 회귀 유지):
- 참조 없음                    → parse_ok=False (영수증 미첨부)
- "mock://receipt?amount=45000&date=2026-07-01" → 해당 값으로 영수증 생성
  (청구와 다른 값을 주면 불일치 케이스를 만들 수 있다 — 골든셋·테스트용)
- 그 외 경로                   → 청구 내용과 일치하는 영수증

TODO(P2 컷 후보, 업무분장 A-6): receipt_text 경로의 실모드 gpt-4o-mini 구조화
추출 승격 — 데모 필수는 Vision 경로뿐이라 정규식 파서 유지.
"""
import logging
import re
from urllib.parse import parse_qs, urlparse

from app.config import get_settings
from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured_vision
from app.llm.prompts import load_prompt
from app.schemas.common import ReceiptData
from app.tools.backend_client import get_receipt_by_path

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_receipt_text(text: str) -> ReceiptData:
    """백엔드가 추출해 준 영수증 텍스트에서 금액·날짜를 뽑는다.

    [팀 방향 2026-07-09] 저장 방식 확정 전 — 텍스트 수신 경로 우선 지원.
    TODO(실키 연결 후): 정규식 대신 gpt-4o-mini 구조화 추출로 교체 (상호·품목 포함).
    """
    amounts = [int(m.replace(",", "")) for m in _AMOUNT_RE.findall(text)]
    date_match = _DATE_RE.search(text)
    return ReceiptData(
        amount=max(amounts) if amounts else None,   # 합계가 최대 금액이라는 가정 (mock)
        date=date_match.group(0) if date_match else None,
        merchant=None, items=[],
        parse_ok=bool(amounts),
        parse_error=None if amounts else "텍스트에서 금액을 찾지 못함",
    )


def _mock_receipt_from_url(url: str, default_amount: int, default_date: str) -> ReceiptData:
    params = parse_qs(urlparse(url).query)
    amount = int(params["amount"][0]) if "amount" in params else default_amount
    date = params["date"][0] if "date" in params else default_date
    return ReceiptData(amount=amount, date=date, merchant="(mock)", items=[])


async def intake_receipt(state: ReviewState) -> dict:
    claim = state["claim"]
    receipt_ref = state.get("receipt_path") or state.get("receipt_url")

    # 백엔드가 추출 텍스트를 주면 Vision 없이 그대로 파싱 (우선 경로)
    receipt_text = state.get("receipt_text")
    if receipt_text:
        return {"receipt_data": parse_receipt_text(receipt_text)}

    if not receipt_ref:
        # 영수증 미첨부 — guardrail_gate가 에스컬레이션 판단 근거로 사용
        return {"receipt_data": ReceiptData(parse_ok=False, parse_error="영수증 미첨부")}

    if receipt_ref.startswith("mock://receipt"):
        return {"receipt_data": _mock_receipt_from_url(receipt_ref, claim.amount, claim.date)}

    # 실모드(A-6): 조회 경로 → 이미지 fetch → Vision 읽기 전용 추출
    s = get_settings()
    if not s.mock_llm and s.openai_api_key:
        try:
            # MOCK_BACKEND=true 혼합 모드(실키 스모크)면 fetch가 None — URL을 그대로
            # Vision에 넘긴다 (공개 이미지 URL 시나리오, A-9 스모크 경로)
            image = await get_receipt_by_path(receipt_ref)
            spec = load_prompt("intake")
            data, meta = await chat_structured_vision(
                agent="intake",
                system=spec.system_with_few_shot(),
                image=image if image is not None else receipt_ref,
                schema=ReceiptData,
                prompt_version=spec.version,
            )
            return {"receipt_data": data, "llm_meta": {"intake": meta}}
        except Exception:
            logger.exception("Vision OCR 실패 — 판독 불능으로 처리 (→ escalate, §8)")
            return {"receipt_data": ReceiptData(
                parse_ok=False, parse_error="영수증 판독 실패 (Vision OCR 오류)")}

    # 목 모드 — 청구 일치 영수증 가정
    return {"receipt_data": ReceiptData(
        amount=claim.amount, date=claim.date, merchant="(mock)", items=[claim.title],
    )}
