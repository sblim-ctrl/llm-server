"""POST /v1/policy-draft — 마법사 회칙·예산 초안 (동기, §7.2).

§2.2 'LLM 호출은 워커만' 원칙의 명시적 예외: 마법사 UX가 즉시 응답을 요구하고
§7.2가 동기로 정의함. 초안 생성이 느려지면 잡 방식으로 전환한다.
"""
from fastapi import APIRouter, HTTPException

from app.graphs.writers.policy_draft import policy_draft_graph
from app.schemas.writers import PolicyDraft, PolicyDraftRequest

router = APIRouter(prefix="/v1", tags=["drafts"])


@router.post("/policy-draft", response_model=PolicyDraft)
async def create_policy_draft(req: PolicyDraftRequest) -> PolicyDraft:
    state = await policy_draft_graph.ainvoke({"request": req})
    if not state.get("verified"):
        # 검증 실패한 초안은 절대 반환하지 않는다 (환각 수치 차단)
        raise HTTPException(status_code=500,
                            detail=f"초안 검증 실패: {state.get('verify_error')}")
    return state["draft"]
