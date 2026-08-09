"""회칙·정책 초안 API — 마법사 3단계와 회칙·정책 관리 화면 (§7.2).

§2.2 'LLM 호출은 워커만' 원칙의 명시적 예외: 마법사 UX가 즉시 응답을 요구하고
§7.2가 동기로 정의함. 초안 생성이 느려지면 잡 방식으로 전환한다.

## 두 경로가 있다 (풀스택 협의 2026-08-04 7번)

**마법사 3단계** — `POST /v1/policy-draft`. 모임을 막 만든 참이라 저장할 팀 맥락이
아직 얕고, 관리자가 그 자리에서 고쳐 확정한다. 저장 없이 결과만 돌려준다(종전 그대로).

**회칙·정책 관리 화면** — `POST /v1/policy-proposals`로 만들고 `GET`으로 다시 꺼낸다.
회의록의 "생성된 메시지가 있으면 반환, 없으면 없다고 반환"이 이 조회다. 만든 초안을
`proposals`에 남기는 이유는 셋이다.

1. 관리자가 버튼을 여러 번 눌러도 **같은 초안**을 본다. LLM은 부를 때마다 다른 문장을
   내므로, 저장하지 않으면 화면을 새로 고칠 때마다 회칙이 바뀐다.
2. 승인·거절이 기록된다. `PATCH /v1/proposals/{id}`가 이미 그 경로이고,
   §9 수락률 지표가 여기서 나온다.
3. 매번 LLM을 태우지 않아 비용·지연이 준다.

`budget_planner`·`rule_amendment`가 쓰는 흐름과 같다 — 새 저장소를 만들지 않았다.
"""

from fastapi import APIRouter, HTTPException

from app.graphs.writers.policy_draft import policy_draft_graph
from app.schemas.ids import BigIntQuery
from app.schemas.writers import (
    PolicyDraft,
    PolicyDraftRequest,
    PolicyProposal,
    PolicyProposalRequest,
)
from app.tools.proposal_store import list_proposals, save_proposal

router = APIRouter(prefix="/v1", tags=["drafts"])

# proposals.type 값. budget·rule_amendment와 같은 테이블을 쓰되 종류로 구분한다.
RULE_DRAFT = "rule_draft"


async def _generate(req: PolicyDraftRequest) -> PolicyDraft:
    state = await policy_draft_graph.ainvoke({"request": req})
    if not state.get("verified"):
        # 검증 실패한 초안은 절대 반환하지 않는다 (환각 수치 차단)
        raise HTTPException(status_code=500, detail=f"초안 검증 실패: {state.get('verify_error')}")
    return state["draft"]


async def _latest_open_proposal(team_id: int) -> PolicyProposal | None:
    """가장 최근의 미결정(proposed) 회칙 초안. 승인·거절된 것은 제외한다."""
    rows = await list_proposals(team_id, RULE_DRAFT)
    row = next((r for r in rows if r["status"] == "proposed"), None)
    if row is None:
        return None
    return PolicyProposal(
        proposal_id=str(row["id"]),
        team_id=team_id,
        status=row["status"],
        draft=PolicyDraft.model_validate(row["payload"]),
        reused=True,
    )


@router.post("/policy-draft", response_model=PolicyDraft)
async def create_policy_draft(req: PolicyDraftRequest) -> PolicyDraft:
    """마법사 1~3단계 통합 요청 (LLM-005 전면 개정) — 저장 없이 결과만 돌려준다.

    `rule_source=ai`면 'AI 초안' 버튼 시점에 호출되어 `rules`에 회칙 초안이 담기고,
    그 외(file·manual·skip)는 '설정 완료' 시점 1회 호출로 `rules`가 빈 배열이다.
    승인 정책은 제안하지 않는다 — 기준 금액(`force_escalation_amount`)은 사용자
    입력이 원천이며 저장은 백엔드 team_settings 소관이다 (개정안 §1-3).
    """
    return await _generate(req)


@router.post(
    "/policy-proposals",
    response_model=PolicyProposal,
    summary="회칙 초안 생성·저장 (회칙·정책 관리 화면)",
)
async def create_policy_proposal(req: PolicyProposalRequest) -> PolicyProposal:
    """회칙 초안을 만들어 `proposals`에 남기고 돌려준다.

    아직 결정되지 않은 초안이 이미 있으면 **새로 만들지 않고 그것을 돌려준다**
    (`reused=true`). 관리자가 버튼을 다시 눌렀을 때 회칙이 바뀌면 안 되기 때문이다.
    일부러 새로 만들려면 `regenerate=true`를 주시면 된다 — 그때는 이전 초안을 그대로
    두고 새 제안을 하나 더 만든다(이력이 남는다).

    관리자가 확인한 뒤에는 `PATCH /v1/proposals/{proposalId}`로 `accepted`·`dismissed`를
    기록해 주시면 된다. 승인된 회칙을 백엔드가 저장하신 다음에는
    `POST /v1/context/refresh`를 보내 주셔야 심사에 반영된다 — 그 알림이 없으면
    회칙을 등록해도 AI는 계속 모르는 상태다.
    """
    if not req.regenerate:
        existing = await _latest_open_proposal(req.team_id)
        if existing is not None:
            return existing

    draft = await _generate(req.to_draft_request())
    proposal_id = await save_proposal(req.team_id, RULE_DRAFT, draft.model_dump(mode="json"))
    return PolicyProposal(
        proposal_id=proposal_id, team_id=req.team_id, status="proposed", draft=draft, reused=False
    )


@router.get(
    "/policy-proposals",
    response_model=PolicyProposal | None,
    summary="저장된 회칙 초안 조회 (없으면 null)",
)
async def read_policy_proposal(team_id: BigIntQuery) -> PolicyProposal | None:
    """아직 결정되지 않은 회칙 초안을 돌려준다. 없으면 `null`이다.

    회의록의 "생성된 메시지가 있으면 반환, 없으면 없다고 반환"이 이 동작이다.
    404가 아니라 200 + `null`인 이유: '초안이 아직 없음'은 오류가 아니라 정상 상태이고,
    화면은 그때 "AI 초안 생성하기" 버튼을 보여주면 된다.
    """
    return await _latest_open_proposal(team_id)
