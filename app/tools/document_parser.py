"""회칙 파일(PDF·Word) → 텍스트 추출 (T2, 회의 4번 결정).

마법사 3단계에서 관리자가 회칙 파일을 올리면 백엔드가 저장하고 LLM-006으로 알린다.
우리는 BE-005로 **원본 바이트**를 받아 여기서 텍스트로 바꾼 뒤 인덱싱한다. 파싱을 우리가
맡는 이유는 백엔드가 텍스트만 주면 파싱 실패가 "회칙 등록했는데 심사엔 반영 안 됨"이라는
조용한 실패로 나타나서다(회신요청 6-3).

**설계 원칙 — 조용히 실패하지 않는다.**
이 모듈의 실패는 전부 예외다. 빈 문자열을 반환하지 않는다. 빈 문자열을 돌려주면 인덱싱이
청크 0개로 "성공"하고, 관리자는 회칙을 등록했다고 믿는데 심사는 회칙 없는 팀으로 도는
상태가 된다 — 이 프로젝트에서 반복된 사고 유형이다(intake parse_ok·digest advice).
예외를 던지면 인덱싱 잡이 failed로 남아 `GET /v1/jobs/{id}`로 원인이 보인다.

지원 형식은 **pdf·docx 둘뿐**이다(회의 4번). 그 외는 명시적 에러 — hwp·txt·이미지가
조용히 통과해 이상한 텍스트로 인덱싱되는 것을 막는다.
"""

import io
import logging
import re

logger = logging.getLogger(__name__)

# 파일 크기 상한 — 일반 회칙 문서는 1MB 미만이다. 실수로 올린 대용량 파일이 워커
# 메모리를 먹는 것을 막는다(워커는 1대가 순차 처리라 한 건이 메모리를 쥐면 전체가 막힌다).
MAX_FILE_BYTES = 10 * 1024 * 1024

# 추출 성공으로 볼 최소 글자 수. 스캔본 PDF는 텍스트 레이어가 없어 0자이거나, 페이지
# 머리글 조각만 몇 자 나온다. 회칙이라면 최소 이 정도는 나온다 — 그 아래면 "파일은
# 읽었지만 회칙 본문이 없다"로 보고 에러를 낸다.
MIN_TEXT_CHARS = 50

# 추출 텍스트 상한. 10MB 상한을 통과한 파일이라도 텍스트 위주 PDF면 수백 쪽이 나올 수
# 있고, 그러면 청크 수천 개 → 임베딩 수천 건이 된다. 워커는 1대가 순차 처리라 그 한 건이
# 다른 팀 인덱싱까지 몇 분간 막는다.
#
# 자르지 않고 **에러**를 내는 이유: 뒤를 잘라내면 잘린 조항이 심사에서 조용히 빠진다.
# 관리자는 회칙 전체가 반영된 줄 안다 — 이 모듈이 피하려는 바로 그 실패 유형이다.
# 50만 자는 A4 기준 대략 250쪽이라 정상 회칙은 절대 닿지 않는다(긴 회칙도 4만 자 수준).
MAX_TEXT_CHARS = 500_000

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"          # docx는 zip 컨테이너다


class DocumentParseError(Exception):
    """회칙 파일을 텍스트로 바꾸지 못했다. 메시지는 관리자에게 그대로 보여도 되는 수준으로 쓴다."""


class UnsupportedDocumentError(DocumentParseError):
    """지원하지 않는 형식 (pdf·docx 외)."""


class EmptyDocumentError(DocumentParseError):
    """파일은 열렸으나 회칙으로 쓸 텍스트가 없다 — 스캔본 PDF가 대표적."""


def _normalize(text: str) -> str:
    """추출 텍스트 정리 — 청킹이 조항 경계를 찾을 수 있는 형태로 만든다.

    PDF 추출물은 줄바꿈이 과하게 들어가고(레이아웃 줄 단위) 공백이 흩어진다.
    `chunk.py`의 `ARTICLE_PATTERN`(`제N조`)·`NUMBERED_PATTERN`이 걸리려면 조항 시작이
    줄 앞에 오고 문단이 빈 줄로 갈려 있어야 한다.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ")                 # PDF에 흔한 non-breaking space
    text = re.sub(r"[ \t]+", " ", text)              # 연속 공백 축약
    text = re.sub(r" *\n *", "\n", text)             # 줄 끝·앞 공백 제거
    text = re.sub(r"\n{3,}", "\n\n", text)           # 빈 줄 3개 이상 → 2개
    # "제 5 조" 처럼 흩어진 조항 번호를 붙인다 — ARTICLE_PATTERN이 공백을 허용하긴 하지만
    # 조항 시작을 줄 앞으로 올려야 NUMBERED_PATTERN 계열과 일관되게 잘린다.
    text = re.sub(r"(?<!\n)(제\s*\d+\s*조)", r"\n\1", text)
    return text.strip()


def _detect_kind(data: bytes, filename: str | None) -> str:
    """pdf | docx 판별. **파일 내용(매직 넘버)을 파일명보다 우선**한다.

    파일명은 사용자가 붙인 것이라 `회칙.pdf`인데 실제로는 docx인 경우가 실제로 있다.
    내용으로 판별하면 그런 경우도 올바르게 처리된다. 내용으로 판별이 안 될 때만
    확장자를 참고하고, 그것도 없으면 에러다(추측하지 않는다).
    """
    if data.startswith(_PDF_MAGIC):
        return "pdf"
    if data.startswith(_ZIP_MAGIC):
        # zip 컨테이너 — docx인지 확인한다. xlsx·pptx·일반 zip도 같은 매직이다.
        try:
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
            if "word/document.xml" in names:
                return "docx"
        except Exception:  # noqa: BLE001 — 손상 zip은 아래 공통 에러로 떨어뜨린다
            pass
        raise UnsupportedDocumentError(
            "지원하지 않는 파일 형식입니다. 회칙은 PDF 또는 Word(.docx) 파일로 올려 주세요."
        )

    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext in ("pdf", "docx"):
        # 내용은 못 알아봤는데 확장자만 맞는 경우 — 손상 파일일 가능성이 높다.
        raise DocumentParseError(
            f"파일을 열 수 없습니다(.{ext}). 파일이 손상되지 않았는지 확인해 주세요."
        )
    if ext == "doc":
        raise UnsupportedDocumentError(
            "구형 Word 형식(.doc)은 지원하지 않습니다. .docx로 저장해 다시 올려 주세요."
        )
    if ext == "hwp":
        raise UnsupportedDocumentError(
            "한글(.hwp) 파일은 지원하지 않습니다. PDF로 저장해 다시 올려 주세요."
        )
    raise UnsupportedDocumentError(
        "지원하지 않는 파일 형식입니다. 회칙은 PDF 또는 Word(.docx) 파일로 올려 주세요."
    )


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as e:
        raise DocumentParseError("PDF를 열 수 없습니다. 파일이 손상되었을 수 있습니다.") from e

    if reader.is_encrypted:
        # 빈 비밀번호로 열리는 PDF가 흔하다(권한 암호만 걸린 경우). 그것부터 시도한다.
        try:
            if reader.decrypt("") == 0:
                raise DocumentParseError(
                    "암호가 걸린 PDF는 읽을 수 없습니다. 암호를 푼 파일로 다시 올려 주세요."
                )
        except DocumentParseError:
            raise
        except Exception as e:  # noqa: BLE001 — pypdf가 암호화 방식별로 다른 예외를 낸다
            raise DocumentParseError(
                "암호가 걸린 PDF는 읽을 수 없습니다. 암호를 푼 파일로 다시 올려 주세요."
            ) from e

    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — 페이지 하나가 깨져도 나머지는 살린다
            logger.warning("PDF %d쪽 텍스트 추출 실패 — 건너뜀", i + 1)
    return "\n\n".join(p for p in parts if p.strip())


def _extract_docx(data: bytes) -> str:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 — python-docx는 손상 파일에 여러 예외를 낸다
        raise DocumentParseError(
            "Word 파일을 열 수 없습니다. 파일이 손상되었을 수 있습니다."
        ) from e

    parts = [p.text for p in document.paragraphs]
    # 표 안의 텍스트도 가져온다 — 회칙에 '한도 표'를 표로 넣는 경우가 있고, 문단만
    # 읽으면 그 조항이 통째로 빠진다(빠져도 에러가 안 나므로 조용한 누락이 된다).
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(p for p in parts if p.strip())


def extract_text(data: bytes, filename: str | None = None) -> str:
    """회칙 파일 바이트 → 인덱싱용 텍스트. 실패는 전부 예외다(빈 문자열 반환 없음).

    Raises:
        UnsupportedDocumentError: pdf·docx가 아닌 형식
        EmptyDocumentError: 파일은 열렸으나 본문 텍스트가 없음(스캔본 PDF 등)
        DocumentParseError: 손상·암호화 등 그 밖의 실패
    """
    if not data:
        raise EmptyDocumentError("빈 파일입니다. 회칙 내용이 담긴 파일을 올려 주세요.")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentParseError(
            f"파일이 너무 큽니다({len(data) / 1024 / 1024:.1f}MB). "
            f"{MAX_FILE_BYTES // 1024 // 1024}MB 이하로 줄여 주세요."
        )

    kind = _detect_kind(data, filename)
    raw = _extract_pdf(data) if kind == "pdf" else _extract_docx(data)
    text = _normalize(raw)

    if len(text) > MAX_TEXT_CHARS:
        raise DocumentParseError(
            f"회칙 분량이 너무 많습니다({len(text):,}자). 지출 심사에 쓰이는 조항만 담아 "
            f"{MAX_TEXT_CHARS:,}자 이하로 줄여 주세요."
        )

    if len(text) < MIN_TEXT_CHARS:
        # 여기서 빈 문자열을 돌려주면 인덱싱이 청크 0개로 '성공'하고, 관리자는 회칙을
        # 등록했다고 믿는데 심사는 회칙 없는 팀으로 돈다. 반드시 실패로 남긴다.
        raise EmptyDocumentError(
            "파일에서 회칙 내용을 읽지 못했습니다. 스캔한 이미지 PDF는 글자를 인식할 수 "
            "없으니, 텍스트가 들어 있는 PDF나 Word 파일로 다시 올려 주세요."
        )
    logger.info("회칙 파일 파싱 완료 — kind=%s, %d자", kind, len(text))
    return text
