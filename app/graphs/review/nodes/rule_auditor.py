"""rule_auditor — 회칙 심사관 (병렬). 회칙 RAG 검색 → 위반 여부·근거 조항 판정.

검색은 CRAG/Self-RAG 스타일 2단계 (강의 08-03 적용):
  ① 1차 검색(제목+설명) → 관련성 채점(distance 임계값)
  ② 불충분 → 쿼리 재작성 후 1회 재검색 — 실모드는 gpt-4o-mini가 규정 어휘로
     재작성(query_rewriter/v1, CRAG rewriter), 목 모드는 결정적 템플릿(골든셋 불변)
  ③ 그래도 근거 없음 → 추측 판정 금지, warn("해석 애매") → 가드레일이 에스컬레이션
근거 없이 조항을 지어내는(환각 인용) 경로를 구조적으로 차단한다 — 인용 정확도 지표(§9.1) 대응.

회칙이 아예 인덱싱되지 않은 팀(온보딩 직후)은 '적용 회칙 없음'으로 pass —
회칙 없는 팀도 예산·판례 심사만으로 파이프라인이 동작해야 한다.

목 모드에서도 search_rules는 실제로 호출된다(검색 메커니즘 자체를 검증하기 위해) —
다만 LLM 판정 자체는 mock_response 고정값. 실패 시에도 예외를 삼키고 error 소견을
남긴다 — 부분 실패 격리 (§3.2).
"""
import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import ExpenseClaim, LLMCallMeta, Opinion
from app.tools.search_rules import search_rules

logger = logging.getLogger(__name__)

# 이 거리보다 멀면 근거로 사용하지 않음.
# A-9 실키 실측(2026-07-20, text-embedding-3-small 코사인 거리)으로 보정:
# 관련 조항 0.42-0.51 / 무관 조항 0.71+ / 완전 무관 0.81+ — 구값 0.5는 관련 조항
# (교재→도서 조항 0.509)을 경계에서 놓쳤다. 0.65 = 관련은 여유 있게 수용,
# 최근접 오답(0.713)은 차단. 임베딩 모델 교체 시 재실측 필수.
RELEVANCE_MAX_DISTANCE = 0.65


class RewrittenQuery(BaseModel):
    """query_rewriter 출력 — 회칙 검색용으로 재작성된 질의 한 줄."""
    query: str


def _fallback_query(claim: ExpenseClaim) -> str:
    """결정적 재작성 템플릿 — 목 모드 응답이자 실모드 빈 출력 방어값."""
    return f"{claim.category} 지출 한도 금지 규정"


async def _rewrite_query(
    claim: ExpenseClaim, members: list[dict],
) -> tuple[str, LLMCallMeta]:
    """CRAG 재작성기 (강의 08-03) — 1차 검색이 빗나간 청구를 규정 어휘 질의로 재작성.

    실모드: gpt-4o-mini (드문 경로라 비용 미미). 목 모드: mock_response로 기존
    결정적 템플릿을 그대로 반환 — 골든셋 결정성·기존 재검색 동작 불변.
    """
    spec = load_prompt("query_rewriter")
    result, meta = await chat_structured(
        agent="query_rewriter",
        system=spec.system_with_few_shot(),
        user=claim.model_dump_json(),
        schema=RewrittenQuery,
        mock_response=RewrittenQuery(query=_fallback_query(claim)),
        mask_with=members,
        prompt_version=spec.version,
    )
    return (result.query.strip() or _fallback_query(claim)), meta


async def _retrieve_with_correction(
    team_id: str, claim: ExpenseClaim, version: int, members: list[dict],
) -> tuple[list[dict], str, LLMCallMeta | None]:
    """CRAG 스타일 검색: 채점 → 재작성 재검색. (chunks, grade, rewrite_meta) 반환.

    grade: "primary"(1차 적중) | "rewritten"(재작성 적중)
           | "no_rules"(인덱스 자체 없음) | "insufficient"(근거 못 찾음)
    rewrite_meta: 재작성 LLM 호출이 있었던 경우만 (비용·버전 계측용, 없으면 None)
    """
    primary_query = f"{claim.title} {claim.description}".strip()
    chunks = await search_rules(team_id, primary_query, version)
    if not chunks:
        return [], "no_rules", None

    relevant = [c for c in chunks if c["distance"] <= RELEVANCE_MAX_DISTANCE]
    if relevant:
        return relevant, "primary", None

    rewritten_query, rewrite_meta = await _rewrite_query(claim, members)
    chunks = await search_rules(team_id, rewritten_query, version)
    relevant = [c for c in chunks if c["distance"] <= RELEVANCE_MAX_DISTANCE]
    if relevant:
        return relevant, "rewritten", rewrite_meta
    return [], "insufficient", rewrite_meta


async def rule_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    members = state.get("team_members") or []
    try:
        chunks, grade, rewrite_meta = await _retrieve_with_correction(
            state["team_id"], claim, state["rule_version"], members)
        rewrite_llm_meta = {"query_rewriter": rewrite_meta} if rewrite_meta else {}

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
            )}, "llm_meta": rewrite_llm_meta}

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
            mask_with=members,
            prompt_version=spec.version,
        )
        opinion.auditor = "rule"
        return {"opinions": {"rule": opinion},
                "llm_meta": {"rule_auditor": meta, **rewrite_llm_meta}}
    except Exception:
        logger.exception("rule_auditor failed")
        return {"opinions": {"rule": Opinion(
            auditor="rule", verdict="error", summary="회칙 심사 실패",
        )}}
