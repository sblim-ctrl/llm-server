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
from app.llm.client import chat_structured, chat_structured_vision
from app.llm.prompts import load_prompt
from app.schemas.common import ReceiptData
from app.tools.backend_client import get_receipt_by_path

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 영수증 바이트의 실제 형식 판별 — **파일명이 아니라 내용(매직 넘버)으로** 본다
# (document_parser._detect_kind와 같은 원칙: 확장자는 사용자가 붙인 것이라 믿을 수 없다).
#
# 왜 필요한가: chat_structured_vision의 media_type 기본값이 "image/jpeg"인데
# intake가 이 인자를 한 번도 넘기지 않아, 무엇이 오든 data:image/jpeg로 감싸 보냈다.
# PNG는 관대한 디코더 덕에 통과하곤 했지만 **PDF는 Vision이 받지 못해 전건 판독 실패**
# → receipt_unreadable → 에스컬레이션이 됐다 (2026-08-11 배포 데모에서 발견).
_MAGIC_MEDIA_TYPES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_PDF_MAGIC = b"%PDF-"
# PDF 텍스트 레이어를 영수증으로 인정할 최소 길이. 회칙용 MIN_TEXT_CHARS(50자)보다
# 낮다 — 카드전표는 "승인 33,236원 2026-07-23 ANTHROPIC" 수준으로도 판독에 충분하고,
# 금액·날짜가 없으면 어차피 parse_receipt_text가 parse_ok=False로 떨어뜨린다.
_MIN_PDF_RECEIPT_CHARS = 10


def detect_media_type(data: bytes) -> str | None:
    """영수증 바이트의 media type. 이미지면 문자열, PDF면 "application/pdf", 미상이면 None."""
    if data.startswith(_PDF_MAGIC):
        return "application/pdf"
    for magic, media_type in _MAGIC_MEDIA_TYPES:
        if data.startswith(magic):
            return media_type
    # WEBP: RIFF....WEBP (4~8바이트가 크기라 건너뛴다)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def pdf_receipt_text(data: bytes) -> str:
    """PDF 영수증에서 텍스트 레이어를 뽑는다. 실패·스캔본이면 빈 문자열.

    카드전표·전자영수증 PDF는 대부분 텍스트 레이어가 있어 Vision 없이 읽힌다.
    스캔 이미지 PDF는 여기서 빈 문자열이 나오고, 호출부가 판독 불능으로 처리한다.
    """
    from app.tools.document_parser import _extract_pdf, _normalize

    try:
        return _normalize(_extract_pdf(data))
    except Exception:  # noqa: BLE001 — 손상·암호화 등 어떤 실패도 판독 불능으로 수렴(§8)
        logger.warning("PDF 영수증 텍스트 추출 실패 — 판독 불능으로 처리", exc_info=True)
        return ""


def parse_receipt_text(text: str) -> ReceiptData:
    """백엔드가 추출해 준 영수증 텍스트에서 금액·날짜를 뽑는다 (정규식·결정적).

    실모드에서는 `_intake_from_text`가 LLM 구조화 추출을 먼저 시도하고, 실패하면
    이 함수로 떨어진다. 목 모드·테스트는 이 경로만 쓴다 — 결정적이라 재현이 쉽다.
    상호·품목은 정규식으로 안정적으로 뽑기 어려워 비운다(LLM 경로가 채운다).
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


async def _intake_from_text(text: str) -> dict:
    """추출 텍스트 → ReceiptData. 실모드면 LLM 구조화 추출, 아니면 정규식.

    풀스택 협의 2026-08-04(8번)에서 OCR 추출값에 **상호명**이 필요하다고 정해졌다.
    정규식으로는 상호명을 안정적으로 못 뽑는다 — 영수증 텍스트 형식이 제각각이고
    상호는 위치·표기가 일정하지 않다. 그래서 Vision 경로와 같은 `intake` 프롬프트로
    텍스트도 구조화 추출한다(이미지 대신 텍스트를 넣는 것뿐이라 프롬프트는 공용).

    실패는 정규식으로 떨어뜨린다 — 금액·날짜만이라도 살리는 편이 판독 불능보다 낫다.
    그마저 실패하면 parse_ok=False가 되고 가드레일이 관리자 확인으로 보낸다(§8).
    """
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        return {"receipt_data": parse_receipt_text(text)}
    try:
        spec = load_prompt("intake")
        data, meta = await chat_structured(
            agent="intake",
            system=spec.system_with_few_shot(),
            user=f"(영수증 추출 텍스트) {text}",
            schema=ReceiptData,
            mock_response=parse_receipt_text(text),
            prompt_version=spec.version,
        )
        return {"receipt_data": data, "llm_meta": {"intake": meta}}
    except Exception:
        logger.exception("영수증 텍스트 구조화 추출 실패 — 정규식으로 폴백")
        return {"receipt_data": parse_receipt_text(text)}


def _mock_receipt_from_url(url: str, default_amount: int, default_date: str) -> ReceiptData:
    params = parse_qs(urlparse(url).query)
    amount = int(params["amount"][0]) if "amount" in params else default_amount
    date = params["date"][0] if "date" in params else default_date
    return ReceiptData(amount=amount, date=date, merchant="(mock)", items=[])


async def intake_receipt(state: ReviewState) -> dict:
    claim = state["claim"]
    receipt_ref = state.get("receipt_path") or state.get("receipt_url")

    # 백엔드가 추출 텍스트를 주면 Vision 없이 처리 (우선 경로)
    receipt_text = state.get("receipt_text")
    if receipt_text:
        return await _intake_from_text(receipt_text)

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

            # PDF 영수증은 Vision이 받지 못한다 — 텍스트 레이어를 뽑아 텍스트 경로로
            # 태운다(카드전표·전자영수증이 대부분 여기 해당). 스캔본이면 텍스트가
            # 안 나오고 판독 불능으로 수렴한다(§8).
            if isinstance(image, bytes) and detect_media_type(image) == "application/pdf":
                text = pdf_receipt_text(image)
                if len(text) >= _MIN_PDF_RECEIPT_CHARS:
                    logger.info("PDF 영수증 텍스트 추출 — %d자, 텍스트 경로로 처리", len(text))
                    return await _intake_from_text(text)
                return {"receipt_data": ReceiptData(
                    parse_ok=False,
                    parse_error="PDF 영수증에서 글자를 읽지 못했습니다 "
                                "(스캔 이미지 PDF로 보입니다) — 관리자 확인 필요")}

            # 실제 형식으로 감싼다 — media_type 기본값(image/jpeg) 고정이 오판의 원인이었다.
            # bytes가 아니거나(URL 경로) 미상 형식이면 종전 기본값을 그대로 쓴다.
            media_type = detect_media_type(image) if isinstance(image, bytes) else None

            spec = load_prompt("intake")
            data, meta = await chat_structured_vision(
                agent="intake",
                system=spec.system_with_few_shot(),
                image=image if image is not None else receipt_ref,
                schema=ReceiptData,
                media_type=media_type or "image/jpeg",
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
