"""rule_auditor — 회칙 심사관 (병렬). 회칙 RAG 검색 → 위반 여부·근거 조항 판정.

검색은 CRAG/Self-RAG 스타일 2단계 (강의 08-03 적용):
  ① 1차 검색(제목+설명) → 관련성 채점(distance 임계값)
  ② 불충분 → 쿼리 재작성 후 1회 재검색 — 실모드는 gpt-4o-mini가 규정 어휘로
     재작성(query_rewriter/v1, CRAG rewriter), 목 모드는 결정적 템플릿(골든셋 불변)
  ③ 그래도 근거 없음 → 추측 판정 금지, pass("관련 조항 없음") — 회칙이 금지하지 않는
     것은 회칙상 허용이다(2026-08-11 정책 확정, 아래 grade=="insufficient" 분기 참조)
근거 없이 조항을 지어내는(환각 인용) 경로를 구조적으로 차단한다 — 인용 정확도 지표(§9.1) 대응.

회칙이 아예 인덱싱되지 않은 팀(마법사 3단계 '건너뛰기')은 **기본 정책 모드**로 심사한다 —
유형별 기본 조항을 근거로 보되 반려는 하지 않는다(_audit_by_default_policy 참조).
전에는 무조건 pass여서 회칙 축이 통째로 비어 있었다.

목 모드에서도(회칙이 인덱싱된 팀이면) search_rules는 실제로 호출된다(검색
메커니즘 자체를 검증하기 위해) — 인덱싱 자체가 없는 팀은 활성 판번호가 없어
호출 없이 no_rules로 바로 빠진다. LLM 판정 자체는 mock_response 고정값. 실패
시에도 예외를 삼키고 error 소견을 남긴다 — 부분 실패 격리 (§3.2).
"""

import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import ExpenseClaim, LLMCallMeta, Opinion, ReceiptData
from app.tools.policy_defaults import FALLBACK_TEAM_TYPE, default_conduct_rules
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
    claim: ExpenseClaim,
    members: list[dict],
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
    team_id: int,
    claim: ExpenseClaim,
    version: int | None,
    members: list[dict],
) -> tuple[list[dict], str, LLMCallMeta | None]:
    """CRAG 스타일 검색: 채점 → 재작성 재검색. (chunks, grade, rewrite_meta) 반환.

    grade: "primary"(1차 적중) | "rewritten"(재작성 적중)
           | "no_rules"(인덱스 자체 없음) | "insufficient"(근거 못 찾음)
    rewrite_meta: 재작성 LLM 호출이 있었던 경우만 (비용·버전 계측용, 없으면 None)
    """
    if version is None:
        # 회칙이 인덱싱된 적 없는 팀 — search_rules를 부를 필요도 없이 확정.
        return [], "no_rules", None

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


def _receipt_status_line(receipt: ReceiptData | None) -> str:
    """기본 정책 user 메시지에 넣는 영수증 첨부·판독 상태 한 줄.

    2026-08-11 데모(팀2 expense 9) 재현 당시엔 기본 조항에 "모든 지출은 영수증을
    첨부해야 한다"가 있는데 첨부 여부를 안 줘서 모델이 "첨부 불명확"으로 헤지했다.
    근본 조치는 그 조항 자체를 근거에서 뺀 것(`default_conduct_rules` — 증빙 판단은
    evidence 심사관·가드레일 영역이라 rule 축이 중복 판단하지 않는다). 이 줄은 그
    뒤에도 남긴다 — default_policy/v2 시스템 프롬프트가 "증빙이 없는 지출"을 warn
    예시로 여전히 들고 있어(조항 무관 일반 지시), 판독 상태를 사실대로 알려주는 편이
    조항 없이 추측하게 두는 것보다 안전하다. intake가 심사관보다 먼저 돌므로 그래프
    경로에서는 receipt_data가 항상 있다(None은 그래프 밖 직접 호출뿐).
    """
    if receipt is None:
        return "영수증 상태: 정보 없음"
    if receipt.parse_ok:
        return "영수증 상태: 첨부됨, 정상 판독 (증빙 확인됨)"
    return f"영수증 상태: {receipt.parse_error or '판독 실패'}"


async def _audit_by_default_policy(
    state: ReviewState,
    claim: ExpenseClaim,
    members: list[dict],
) -> dict:
    """기본 정책 모드 — 회칙 미등록 팀을 유형별 기본 조항으로 본다 (마법사 3단계 건너뛰기).

    전에는 무조건 pass여서 회칙 축이 통째로 비어 있었다. 다만 근거가 '팀이 등록한 회칙'이
    아니라 '우리가 유형 보고 만든 기본값'이므로 반려는 하지 않는다 — fail이 와도 warn으로
    낮춘다(프롬프트에도 금지했지만 코드에서 한 번 더 막는다). warn은 가드레일이
    에스컬레이션으로 받아 관리자에게 넘긴다.

    근거 조항이 하나도 없는 유형이면(템플릿에 성격 조항이 없는 경우) 기존처럼 pass.
    """
    rules = default_conduct_rules(state.get("team_type") or FALLBACK_TEAM_TYPE)
    if not rules:
        return {
            "opinions": {
                "rule": Opinion(
                    auditor="rule",
                    verdict="pass",
                    summary="이 팀에 인덱싱된 회칙이 없고 적용할 기본 정책 조항도 없음 — 예산·판례 심사로 판정",
                )
            }
        }

    evidence_text = "\n".join(f"- {r}" for r in rules)
    spec = load_prompt("default_policy")
    opinion, meta = await chat_structured(
        agent="default_policy",
        system=spec.system_with_few_shot(),
        user=f"{claim.model_dump_json()}\n\n"
        f"기본 정책 조항 (등록된 회칙 아님 — 유형별 기본값):\n{evidence_text}\n\n"
        f"{_receipt_status_line(state.get('receipt_data'))}",
        schema=Opinion,
        mock_response=Opinion(
            auditor="rule",
            verdict="pass",
            summary=f"'{claim.category}' 지출 — 등록된 회칙이 없어 유형별 기본 정책 기준으로 봤고 "
            f"어긋나는 점 없음",
            evidence=list(rules),
        ),
        mask_with=members,
        prompt_version=spec.version,
    )
    opinion.auditor = "rule"
    if opinion.verdict == "fail":
        # 팀이 합의한 적 없는 기준으로 반려하지 않는다 — 관리자 확인으로 낮춘다
        opinion.verdict = "warn"
        opinion.summary = f"[기본 정책 기준 — 반려 아님] {opinion.summary}"
    return {"opinions": {"rule": opinion}, "llm_meta": {"default_policy": meta}}


async def rule_auditor(state: ReviewState) -> dict:
    claim = state["claim"]
    members = state.get("team_members") or []
    try:
        chunks, grade, rewrite_meta = await _retrieve_with_correction(
            state["team_id"], claim, state["rule_version"], members
        )
        rewrite_llm_meta = {"query_rewriter": rewrite_meta} if rewrite_meta else {}

        if grade == "no_rules":
            return await _audit_by_default_policy(state, claim, members)

        if grade == "insufficient":
            # **조항 부재는 위반이 아니다** (2026-08-11 정책 확정).
            #
            # 종전에는 warn을 냈고, 그것이 guardrail의 rule_ambiguous → 에스컬레이션이라
            # "회칙에 안 적힌 지출은 전부 관리자 확인"이 됐다. 회칙은 모든 지출 유형을
            # 열거하지 않으므로(장소 대관·택배·비품처럼 조항이 없는 게 정상인 항목이
            # 많다) 정상 지출 대부분이 대기열로 갔다 — 배포 데모에서 실제로 그랬다.
            #
            # Self-RAG 원칙("근거를 못 찾으면 지어내지 않는다")은 그대로다. 다만 그
            # 원칙의 결론은 "관리자를 부른다"가 아니라 **"회칙을 근거로는 막을 수 없다"**
            # 여야 한다 — 회칙이 금지하지 않는 것은 회칙상 허용이다(죄형법정주의와 같은
            # 구조). 실제 통제는 다른 축이 그대로 한다: 예산 부족은 budget 심사관이,
            # 중복·분할은 precedent 심사관이, 금액은 결정적 금액 게이트가, 영수증
            # 불일치는 evidence가 잡는다. 이 변경으로 느슨해지는 것은 **회칙 축 하나뿐**
            # 이고, 그 축은 애초에 근거가 없어 판단할 수 없던 상태였다.
            #
            # warn은 "조항이 있는데 해석이 갈리는 경우"로 좁힌다 — 그건 아래 LLM 경로가
            # 낸다. 여기(검색 결과 자체가 없음)는 pass다.
            return {
                "opinions": {
                    "rule": Opinion(
                        auditor="rule",
                        verdict="pass",
                        summary="청구와 관련된 회칙 조항이 없음 — 회칙상 금지에 해당하지 않음 "
                                "(예산·판례·금액 심사는 별도로 적용됨)",
                    )
                },
                "llm_meta": rewrite_llm_meta,
            }

        evidence_text = "\n".join(f"- {c['text']}" for c in chunks)
        spec = load_prompt("rule_auditor")
        opinion, meta = await chat_structured(
            agent="rule_auditor",
            system=spec.system_with_few_shot(),
            user=f"{claim.model_dump_json()}\n\n관련 회칙 조항 (검증된 근거만):\n{evidence_text}",
            schema=Opinion,
            mock_response=Opinion(
                auditor="rule",
                verdict="pass",
                summary=f"'{claim.category}' 카테고리 지출로 회칙상 금지 항목에 해당하지 않음",
                evidence=[c["text"] for c in chunks],
            ),
            mask_with=members,
            prompt_version=spec.version,
        )
        opinion.auditor = "rule"
        return {
            "opinions": {"rule": opinion},
            "llm_meta": {"rule_auditor": meta, **rewrite_llm_meta},
        }
    except Exception:
        logger.exception("rule_auditor failed")
        return {
            "opinions": {
                "rule": Opinion(
                    auditor="rule",
                    verdict="error",
                    summary="회칙 심사 실패",
                )
            }
        }
