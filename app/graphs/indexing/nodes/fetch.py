"""fetch — 팀 회칙·카테고리 원본 조회 (REQ-041 파이프라인 1단계). 읽기 전용.

회칙은 **텍스트로 등록될 수도, 파일(PDF·docx)로 등록될 수도** 있다(마법사 3단계).
어느 쪽인지는 백엔드만 아는 사실이라 같은 엔드포인트가 형식만 달리 답하고, 여기서
분기해 파일이면 텍스트로 바꾼다 (T2, 회의 4번 결정).

**파싱 실패는 그대로 던진다.** 빈 텍스트로 이어가면 인덱싱이 청크 0개로 '성공'하고,
관리자는 회칙을 등록했다고 믿는데 심사는 회칙 없는 팀으로 돈다. 예외를 던지면 잡이
failed로 남아 `GET /v1/jobs/{id}`에 사유가 보이고, 백엔드가 관리자에게 알릴 수 있다.
"""
import logging

from app.graphs.indexing.state import IndexingState
from app.tools.backend_client import get_policy_document
from app.tools.document_parser import DocumentParseError, extract_text

logger = logging.getLogger(__name__)


async def fetch(state: IndexingState) -> dict:
    source = await get_policy_document(state["team_id"], state["doc_type"], state["version"])

    if source.text is not None:
        return {"raw_text": source.text, "source_kind": "text"}

    if not source.file_bytes:
        # 텍스트도 파일도 없다 — 백엔드 응답이 계약과 다르다. 조용히 빈 인덱스를
        # 만들지 않고 실패로 남긴다.
        raise DocumentParseError(
            "회칙 원본을 받지 못했습니다(텍스트·파일 둘 다 비어 있음). "
            "백엔드 응답을 확인해 주세요."
        )

    try:
        text = extract_text(source.file_bytes, source.filename)
    except DocumentParseError:
        # 메시지는 관리자에게 그대로 보여도 되는 수준으로 쓰여 있다(document_parser).
        # 여기서 삼키지 않고 그대로 올려 잡 실패 사유로 남긴다.
        logger.error(
            "회칙 파일 파싱 실패 — team=%s version=%s filename=%r",
            state["team_id"], state["version"], source.filename,
        )
        raise

    logger.info(
        "회칙 파일에서 텍스트 추출 — team=%s filename=%r %d자",
        state["team_id"], source.filename, len(text),
    )
    return {"raw_text": text, "source_kind": "file"}
