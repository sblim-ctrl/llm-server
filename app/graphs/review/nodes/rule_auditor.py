"""rule_auditor — 회칙 심사관 (병렬). 회칙 RAG 검색 → 위반 여부·근거 조항 판정.

검색은 CRAG/Self-RAG 스타일 2단계 (강의 08-03 적용):
  ① 1차 검색(제목+설명) → 관련성 채점(distance 임계값)
  ② 불충분 → 쿼리 재작성(카테고리·규정 어휘) 후 1회 재검색
  ③ 그래도 근거 없음 → 추측 판정 금지, warn("해석 애매") → 가드레일이 에스컬레이션
근거 없이 조항을 지어내는(환각 인용) 경로를 구조적으로 차단한다 — 인용 정확도 지표(§9.1) 대응.

회칙이 아예 인덱싱되지 않은 팀(온보딩 직후)은 '적용 회칙 없음'으로 pass —
회칙 없는 팀도 예산·판례 심사만으로 파이프라인이 동작해야 한다.

목 모드에서도 search_rules는 실제로 호출된다(검색 메커니즘 자체를 검증하기 위해) —
다만 LLM 판정 자체는 mock_response 고정값. 실패 시에도 예외를 삼키고 error 소견을
남긴다 — 부분 실패 격리 (§3.2).
"""
import logging

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import ExpenseClaim, Opinion
from app.tools.search_rules import search_rules

logger = logging.getLogger(__name__)

# 이 거리보다 멀면 근거로 사용하지 않음 (실제 임베딩 연결 후 골든셋으로 보정 필요)
RELEVANCE_MAX_DISTANCE = 0.5


async def _retrieve_with_correction(
    team_id: str, claim: ExpenseClaim, version: int,
) -> tuple[list[dict], str]:
    """CRAG 스타일 검색: 채점 → 재작성 재검색. (chunks, grade) 반환.

    grade: "primary"(1차 적중) | "rewritten"(재작성 적중)
           | "no_rules"(인덱스 자체 없음) | "insufficient"(근거 못 찾음)
    """
    primary_query = f"{claim.title} {claim.description}".strip()
    chunks = await search_rules(team_id, primary_query, version)
    if not chunks:
        return [], "no_rules"

    relevant = [c for c in chunks if c["distance"] <= RELEVANCE_MAX_DISTANCE]
    if relevant:
        return relevant, "primary"

    # TODO(실키 연결 후): gpt-4o-mini로 질의 재작성 — 지금은 규정 어휘 기반 결정적 재작성
    rewritten_query = f"{claim.category} 지출 한도 금지 규정"
    chunks = await search_rules(team_id, rewritten_query, version)
    relevant = [c for c in chunks if c["distance"] <= RELEVANCE_MAX_DISTANCE]
    if relevant:
        return relevant, "rewritten"
    return [], "insufficient"


async def rule_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    try:
        chunks, grade = await _retrieve_with_correction(
            state["team_id"], claim, state["rule_version"])

        if grade == "no_rules":
            return {"opinions": {"rule": Opinion(
                auditor="rule", verdict="pass",
                summary="이 팀에 인덱싱된 회칙이 없음 — 회칙 기준 판단 대상 아님 (예산·판례 심사로 판정)",
            )}}

        if grade == "insufficient":
            # Self-RAG 원칙: 근거를 못 찾으면 지어내지 않는다 → 해석 애매로 관리자 확인
            return {"opinions": {"rule": Opinion(
                auditor="rule", verdict="warn",
                summary="청구와 관련된 회칙 조항을 찾지 못함 — 해석 애매, 관리자 확인 권고",
            )}}

        evidence_text = "\n".join(f"- {c['text']}" for c in chunks)
        spec = load_prompt("rule_auditor")
        opinion, meta = await chat_structured(
            agent="rule_auditor",
            system=spec.system_with_few_shot(),
            user=f"{claim.model_dump_json()}\n\n관련 회칙 조항 (검증된 근거만):\n{evidence_text}",
            schema=Opinion,
            mock_response=Opinion(
                auditor="rule", verdict="pass",
                summary=f"'{claim.category}' 카테고리 지출로 회칙상 금지 항목에 해당하지 않음 (mock)",
                evidence=[c["text"] for c in chunks],
            ),
            mask_with=state.get("team_members") or [],
            prompt_version=spec.version,
        )
        opinion.auditor = "rule"
        return {"opinions": {"rule": opinion}, "llm_meta": {"rule_auditor": meta}}
    except Exception:
        logger.exception("rule_auditor failed")
        return {"opinions": {"rule": Opinion(
            auditor="rule", verdict="error", summary="회칙 심사 실패",
        )}}
