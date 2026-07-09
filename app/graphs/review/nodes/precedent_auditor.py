"""precedent_auditor — 판례·이상탐지 심사관 (병렬).

search_precedents로 유사 판례를 실제 검색해 소견에 인용한다 (REQ-042 루프의 출구).
목 모드 판정 규칙(결정적): 매우 유사한(distance < 0.35) 반려/override 판례가
있으면 warn — guardrail_gate가 escalate로 수렴시킨다. 동일 사안 재청구 시
"판례 저장 전 approve → 저장 후 escalate" 변화를 데모로 보일 수 있다 (§9.2).

TODO(백엔드 연동 후): get_expense_history 기반 중복 청구·분할 청구 탐지 추가.
"""
import logging

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.schemas.common import Opinion
from app.tools.precedent_store import masked_claim_summary
from app.tools.search_precedents import search_precedents

logger = logging.getLogger(__name__)

PROMPT_VERSION = "precedent_auditor/v1"
SIMILARITY_WARN_DISTANCE = 0.35


def _mock_opinion(cases: list[dict]) -> Opinion:
    # 위험 신호는 '관리자(ADMIN)' 판례만 근거로 삼는다 (§4.4-b) — AGENT 자신의
    # 과거 반려까지 신호로 쓰면 유사 건을 영원히 에스컬레이션하는 자기 오염 루프가 생김
    risky = [c for c in cases
             if c["distance"] < SIMILARITY_WARN_DISTANCE
             and c["decided_by"] == "ADMIN"
             and (c["decision"] == "reject" or c["is_override"])]
    citations = [f"({c['decision']}/{c['decided_by']}) {c['expense_summary']}" for c in cases]

    if risky:
        return Opinion(
            auditor="precedent", verdict="warn",
            summary=f"유사 사안에 대한 반려/override 판례 {len(risky)}건 발견 — 관리자 확인 권고",
            similar_cases=citations,
        )

    # 판례 보완 신호 (§4.4-b의 승인 방향): 동일 사안을 관리자가 승인한 판례가 있으면
    # 회칙이 애매해도(rule warn) 가드레일이 자동 승인 경로를 유지할 수 있다
    support = [c for c in cases
               if c["distance"] < SIMILARITY_WARN_DISTANCE
               and c["decided_by"] == "ADMIN"
               and c["decision"] == "approve" and not c["is_override"]]
    return Opinion(
        auditor="precedent", verdict="pass",
        summary=((f"동일 사안 관리자 승인 판례 {len(support)}건 — 승인 근거로 인용" if support
                  else "유사 판례 있음, 위험 신호 없음" if cases else "유사 판례 없음") + " (mock)"),
        similar_cases=citations,
        figures={"admin_approve_support": len(support)},
    )


async def precedent_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        # 판례는 PIIMasker 처리된 텍스트로 저장돼 있으므로 쿼리도 동일 마스킹 적용
        cases = await search_precedents(state["team_id"],
                                        await masked_claim_summary(state["team_id"], claim))

        opinion = await chat_structured(
            agent="precedent_auditor",
            system="(prompts/precedent_auditor/v1.yaml에서 로드)",
            user=f"{claim.model_dump_json()}\n\n유사 판례:\n"
                 + "\n".join(f"- {c['expense_summary']} → {c['decision']}"
                             f" ({c['reason'] or '사유 없음'})" for c in cases),
            schema=Opinion,
            mock_response=_mock_opinion(cases),
        )
        opinion.auditor = "precedent"
        return {"opinions": {"precedent": opinion}}
    except Exception:
        logger.exception("precedent_auditor failed")
        return {"opinions": {"precedent": Opinion(
            auditor="precedent", verdict="error", summary="판례 심사 실패",
        )}}
