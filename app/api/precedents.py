"""POST /v1/precedents — 관리자 결정 수신 → 판례 저장 (REQ-042 학습 루프의 입구).

에스컬레이션된 건을 관리자가 결정하면 백엔드가 이 엔드포인트로 push한다.
저장된 판례는 다음 심사부터 PrecedentAuditor가 인용한다.
"""
from fastapi import APIRouter

from app.schemas.precedent import PrecedentCreate, PrecedentCreated
from app.tools.precedent_store import save_precedent, summarize_claim

router = APIRouter(prefix="/v1", tags=["precedents"])


@router.post("/precedents", response_model=PrecedentCreated, status_code=201)
async def create_precedent(req: PrecedentCreate) -> PrecedentCreated:
    precedent_id = await save_precedent(
        team_id=req.team_id,
        summary=summarize_claim(req.claim),
        decision=req.decision,
        decided_by="ADMIN",
        reason=req.reason,
        is_override=req.is_override,
        rule_version=req.rule_version,
    )
    return PrecedentCreated(precedent_id=precedent_id)
