"""PolicyDrafter 개정 모드 — 반복 관리자 개입 기반 회칙 개정 제안 그래프 (§4.4-e, B-6).

policy_draft.py(신규 회칙 초안·동기 API)와 별도 그래프인 이유: 입력(판례 군집
vs 팀 소개)·데이터 소스·실행 경로(비동기 잡 vs 동기 API)가 완전히 다르다 —
설계서 §4.4-e도 독립 그래프로 기술.

detect(툴) → summarize_gap(결정적) → draft_amendment(LLM은 문안만) →
verify(placeholder·근거 검사) → save(proposals type="rule_amendment").
군집 임계 미달이면 {proposals: [], reason: "반복 판례 없음"}으로 정상 종료 (에러 아님).
"""

import logging

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta
from app.schemas.proposals import RuleAmendmentRequest
from app.tools.detect_repeated_overrides import detect_repeated_overrides
from app.tools.proposal_store import save_proposal

logger = logging.getLogger(__name__)

NO_CLUSTER_REASON = "반복 판례 없음"


class AmendmentText(BaseModel):
    """LLM 산출은 문안만 — 근거 판례 id·횟수는 코드(군집)가 붙인다."""

    amendment: str  # 회칙에 바로 넣을 개정 조항 문안
    rationale: str  # 반복 개입 횟수·현행 조항과의 갭 설명


class AmendmentState(TypedDict, total=False):
    request: RuleAmendmentRequest
    clusters: list[dict]
    gap_summaries: list[str]
    drafts: list[AmendmentText]
    verified: bool
    verify_error: str | None
    proposal_ids: list[str]
    reason: str | None  # 임계 미달 시 NO_CLUSTER_REASON (정상 종료)
    llm_meta: dict[str, LLMCallMeta]  # 작성 노드가 하나뿐 — reducer 불요 (B-7 합산용)


async def detect(state: AmendmentState) -> dict:
    clusters = await detect_repeated_overrides(state["request"].team_id)
    if not clusters:
        return {"clusters": [], "reason": NO_CLUSTER_REASON}
    return {"clusters": clusters}


def _has_clusters(state: AmendmentState) -> str:
    return "summarize_gap" if state.get("clusters") else END


def summarize_gap_pure(cluster: dict) -> str:
    """군집 1건의 갭 설명 — 결정적 조립 (단위 테스트 대상)."""
    decisions = ", ".join(sorted(set(cluster["decisions"])))
    return (
        f"군집 요약: {cluster['cluster_summary']}\n"
        f"관리자 개입: {cluster['count']}회 (결정: {decisions})\n"
        f"갭: 현행 회칙 조항과 실제 관리자 결정이 반복적으로 어긋남"
    )


async def summarize_gap(state: AmendmentState) -> dict:
    return {"gap_summaries": [summarize_gap_pure(c) for c in state["clusters"]]}


def _mock_amendment(cluster: dict) -> AmendmentText:
    """목 모드 결정적 템플릿 — f-string 완결 문장 (placeholder 잔존 불가)."""
    return AmendmentText(
        amendment=(
            f"'{cluster['cluster_summary']}' 유형 지출은 관리자 반복 결정"
            f"({cluster['count']}회)을 반영해 처리 기준을 회칙에 명문화한다."
        ),
        rationale=(
            f"동일 패턴 지출에 대해 관리자가 {cluster['count']}회 반복 개입 — "
            f"현행 회칙에 명시 기준이 없어 개정을 제안합니다."
        ),
    )


async def draft_amendment(state: AmendmentState) -> dict:
    spec = load_prompt("rule_amendment")
    drafts: list[AmendmentText] = []
    meta_map: dict[str, LLMCallMeta] = {}
    for i, (cluster, gap) in enumerate(zip(state["clusters"], state["gap_summaries"], strict=True)):
        result, meta = await chat_structured(
            agent="rule_amendment",
            system=spec.system_with_few_shot(),
            user=gap,
            schema=AmendmentText,
            mock_response=_mock_amendment(cluster),
            prompt_version=spec.version,
        )
        drafts.append(result)
        meta_map[f"rule_amendment_{i}"] = meta
    return {"drafts": drafts, "llm_meta": meta_map}


def verify_amendment_pure(drafts: list[AmendmentText], clusters: list[dict]) -> str | None:
    """검증(Evaluator) — 위반 시 사유 반환, 통과 시 None (verify_draft_pure 패턴)."""
    if len(drafts) != len(clusters):
        return "초안 수가 군집 수와 다름"
    if any("{" in d.amendment + d.rationale for d in drafts):
        return "치환되지 않은 placeholder 존재"
    if any(not c.get("precedent_ids") for c in clusters):
        return "근거 판례 id 없는 군집 존재"
    return None


async def verify_amendment(state: AmendmentState) -> dict:
    error = verify_amendment_pure(state["drafts"], state["clusters"])
    if error:
        logger.error("rule amendment verification failed: %s", error)
    return {"verified": error is None, "verify_error": error}


async def save(state: AmendmentState) -> dict:
    if not state["verified"]:
        return {"proposal_ids": []}
    ids: list[str] = []
    for cluster, draft in zip(state["clusters"], state["drafts"], strict=True):
        payload = {
            "amendment": draft.amendment,
            "rationale": draft.rationale,
            "cluster_summary": cluster["cluster_summary"],
            "count": cluster["count"],
            "precedent_ids": cluster["precedent_ids"],  # 근거 판례 id 배열 (§4.4-e)
            "verified": True,
        }
        ids.append(await save_proposal(state["request"].team_id, "rule_amendment", payload))
    return {"proposal_ids": ids}


def build_rule_amendment_graph():
    g = StateGraph(AmendmentState)
    g.add_node("detect", detect)
    g.add_node("summarize_gap", summarize_gap)
    g.add_node("draft_amendment", draft_amendment)
    g.add_node("verify_amendment", verify_amendment)
    g.add_node("save", save)
    g.add_edge(START, "detect")
    g.add_conditional_edges("detect", _has_clusters, {"summarize_gap": "summarize_gap", END: END})
    g.add_edge("summarize_gap", "draft_amendment")
    g.add_edge("draft_amendment", "verify_amendment")
    g.add_edge("verify_amendment", "save")
    g.add_edge("save", END)
    return g.compile()


rule_amendment_graph = build_rule_amendment_graph()
