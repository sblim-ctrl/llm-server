"""rule_auditor — 회칙 심사관 (병렬). 회칙 RAG 검색 → 위반 여부·근거 조항 판정.

목 모드에서도 search_rules는 실제로 호출된다(검색 메커니즘 자체를 검증하기 위해) —
다만 LLM 판정 자체는 mock_response 고정값. 실패 시에도 예외를 삼키고 error 소견을
남긴다 — 부분 실패 격리 (§3.2).
"""
import logging

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.schemas.common import Opinion
from app.tools.search_rules import search_rules

logger = logging.getLogger(__name__)

PROMPT_VERSION = "rule_auditor/v1"


async def rule_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        chunks = await search_rules(state["team_id"], claim.description, state["rule_version"])
        evidence_text = "\n".join(f"- {c['text']}" for c in chunks) or "(인덱싱된 회칙 없음)"

        opinion = await chat_structured(
            agent="rule_auditor",
            system="(prompts/rule_auditor/v1.yaml에서 로드)",
            user=f"{claim.model_dump_json()}\n\n관련 회칙 조항:\n{evidence_text}",
            schema=Opinion,
            mock_response=Opinion(
                auditor="rule", verdict="pass",
                summary=f"'{claim.category}' 카테고리 지출로 회칙상 금지 항목에 해당하지 않음 (mock)",
                evidence=[c["text"] for c in chunks] or ["회칙 제4조 (mock)"],
            ),
        )
        opinion.auditor = "rule"
        return {"opinions": {"rule": opinion}}
    except Exception:
        logger.exception("rule_auditor failed")
        return {"opinions": {"rule": Opinion(
            auditor="rule", verdict="error", summary="회칙 심사 실패",
        )}}
