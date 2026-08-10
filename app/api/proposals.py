"""proposals API — 제안 잡 등록·조회·관리자 결정 기록 (§6, §9 수락률 지표의 기록 경로)."""

from fastapi import APIRouter, HTTPException

from app.api.drafts import RULE_DRAFT
from app.db.pool import insert_job
from app.schemas.analyze import AnalyzeAccepted
from app.schemas.ids import BigIntQuery
from app.schemas.proposals import (
    ProposalBudgetRequest,
    ProposalOut,
    ProposalPatch,
    RuleAmendmentRequest,
)
from app.tools.proposal_store import list_proposals, update_proposal_status

router = APIRouter(prefix="/v1", tags=["proposals"])


@router.post("/proposals/budget", response_model=AnalyzeAccepted, status_code=202)
async def create_budget_proposal_job(req: ProposalBudgetRequest) -> AnalyzeAccepted:
    """예산관리 페이지 AI 메시지 생성 잡 접수 (LLM-016).

    결과는 `GET /v1/jobs/{job_id}` 또는 `GET /v1/proposals?type=budget`으로 받는다.
    payload는 Figma 확정 3블록(category_analysis·budget_status_analysis·recommendation)
    + figures + verified다.

    `verified=false`는 LLM이 만든 문장이 수치 검증을 통과하지 못해 집계값 기반의
    결정적 문구로 교체됐다는 뜻이다 — "쓸 수 없는 값"이라는 뜻이 아니다. 이 경우에도
    3블록(본문)은 언제나 안전한 값이므로 그대로 화면에 띄워도 된다. (예외: 동기 초안
    생성 API인 `POST /v1/policy-draft` 계열은 폴백 없이 5xx로 실패를 반환한다.)
    """
    job_id = await insert_job(
        team_id=req.team_id, job_type="proposal_budget", payload=req.model_dump(mode="json")
    )
    return AnalyzeAccepted(job_id=job_id)


@router.post("/proposals/rule-amendment", response_model=AnalyzeAccepted, status_code=202)
async def create_rule_amendment_job(req: RuleAmendmentRequest) -> AnalyzeAccepted:
    job_id = await insert_job(
        team_id=req.team_id, job_type="proposal_rule_amendment", payload=req.model_dump(mode="json")
    )
    return AnalyzeAccepted(job_id=job_id)


@router.get(
    "/proposals",
    response_model=list[ProposalOut],
    summary="제안 목록 조회 (LLM-015, type 미지정 시 마법사 회칙 초안 rule_draft 제외)",
)
async def read_proposals(
    team_id: BigIntQuery,
    type: str | None = None,
    status: str | None = None,
) -> list[ProposalOut]:
    """AI가 올린 제안 목록을 돌려준다. 없으면 빈 배열이다 — 404가 아니다 (LLM-015).

    `type` 미지정 시 마법사 회칙 초안(`rule_draft`)은 기본 제외한다. 그쪽은
    `GET /v1/policy-proposals`(LLM-019)가 다루는 별개 자원이라, 관리자 제안함
    목록에 섞이면 같은 초안이 두 화면에 중복 노출된다. `type=rule_draft`를
    명시하면 그때는 포함된다.
    """
    rows = await list_proposals(team_id, type)
    if type is None:
        rows = [r for r in rows if r["type"] != RULE_DRAFT]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return [
        ProposalOut(
            id=str(r["id"]),
            team_id=r["team_id"],
            type=r["type"],
            payload=r["payload"],
            status=r["status"],
            decided_by=r["decided_by"],
            created_at=r["created_at"].isoformat(),
            decided_at=r["decided_at"].isoformat() if r["decided_at"] else None,
        )
        for r in rows
    ]


@router.patch("/proposals/{proposal_id}")
async def decide_proposal(proposal_id: str, patch: ProposalPatch) -> dict:
    outcome = await update_proposal_status(proposal_id, patch.status, patch.decided_by)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="proposal not found")
    if outcome == "already_decided":
        raise HTTPException(status_code=409, detail="proposal already decided")
    return {"proposal_id": proposal_id, "status": patch.status}
