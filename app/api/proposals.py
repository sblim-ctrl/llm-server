"""proposals API — 제안 잡 등록·관리자 결정 기록 (§6, §9 수락률 지표의 기록 경로)."""

from fastapi import APIRouter, HTTPException

from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.proposals import (
    ProposalPatch,
    RuleAmendmentRequest,
)  # [MVP 제외] budget_planner — ProposalBudgetRequest 제거
from app.tools.proposal_store import update_proposal_status

router = APIRouter(prefix="/v1", tags=["proposals"])


# [MVP 제외] budget_planner — MVP 이후 복원: 아래 라우트 전체 주석 해제 + import 복원 필요
# @router.post("/proposals/budget", response_model=AnalyzeAccepted, status_code=202)
# async def create_budget_proposal_job(req: ProposalBudgetRequest) -> AnalyzeAccepted:
#     job_id = await insert_job(
#         team_id=req.team_id, job_type="proposal_budget", payload=req.model_dump(mode="json")
#     )
#     return AnalyzeAccepted(job_id=job_id)


@router.post("/proposals/rule-amendment", response_model=AnalyzeAccepted, status_code=202)
async def create_rule_amendment_job(req: RuleAmendmentRequest) -> AnalyzeAccepted:
    job_id = await insert_job(
        team_id=req.team_id, job_type="proposal_rule_amendment", payload=req.model_dump(mode="json")
    )
    return AnalyzeAccepted(job_id=job_id)


@router.patch("/proposals/{proposal_id}")
async def decide_proposal(proposal_id: str, patch: ProposalPatch) -> dict:
    outcome = await update_proposal_status(proposal_id, patch.status, patch.decided_by)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="proposal not found")
    if outcome == "already_decided":
        raise HTTPException(status_code=409, detail="proposal already decided")
    return {"proposal_id": proposal_id, "status": patch.status}
