"""fetch — 팀 회칙·카테고리 원문 조회 (REQ-041 파이프라인 1단계). 읽기 전용, 부수효과 없음."""
from app.graphs.indexing.state import IndexingState
from app.tools.backend_client import get_policy_document


async def fetch(state: IndexingState) -> dict:
    raw_text = await get_policy_document(state["team_id"], state["doc_type"], state["version"])
    return {"raw_text": raw_text}
