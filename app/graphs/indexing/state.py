"""컨텍스트 인덱싱 파이프라인 상태 (§4.4-a). LLM 미사용 — embeddings만 호출."""

from typing import TypedDict


class IndexingState(TypedDict, total=False):
    team_id: int
    doc_type: str  # rule | category (params는 인덱싱 대상 아님 — app/worker.py 참고)
    # 회칙 판번호 — upsert가 MAX(version)+1로 발급한다(내부 색인 세대 번호, §4.4-a).
    # 백엔드에서 받던 값이 아니다 — 백엔드는 회칙을 팀당 1건 덮어쓰기로 관리해 버전
    # 개념이 없다(2026-08-07 결정, T11 회신). 입력이 아니라 upsert 산출값이다.
    version: int
    raw_text: str
    # text | file — 회칙이 직접 입력으로 왔는지 파일(PDF·docx)로 왔는지 (T2).
    # 로그·잡 결과에서 "이 팀 회칙이 파일에서 나온 것인지" 되짚을 때 쓴다.
    source_kind: str
    chunks: list[str]
    embeddings: list[list[float]]
    chunks_indexed: int
