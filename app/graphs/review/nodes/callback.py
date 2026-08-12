"""callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)."""

import re
import time
from typing import Any

from app.graphs.review.state import ReviewState
from app.schemas.callback import CallbackPayload
from app.schemas.common import Opinion
from app.tools.backend_client import send_callback


def resolve_processed_by(verdict: str, admin_decision: dict | None) -> str | None:
    """최종 처리 주체. 아직 처리자가 없으면 None.

    - 관리자가 직접 결정한 건(HITL 재개)은 ADMIN
    - AI가 승인·반려까지 끝낸 건은 AI
    - escalate는 관리자 확인 대기라 최종 처리자가 없다 → None. 여기서 "AI"를 보내면
      대기 건이 프론트에 'AI가 처리함'으로 표시된다. 관리자가 승인·반려하면 백엔드가
      그 시점에 ADMIN을 기입한다(우리는 그 시점을 알 수 없다).

    이 규칙 덕에 프론트의 'AI 자동처리' 배지 조건이 processedBy == "AI" 하나로 끝난다.
    """
    if admin_decision:
        return "ADMIN"
    return None if verdict == "escalate" else "AI"


def trace_meta(state: ReviewState) -> dict[str, Any]:
    """LLM 호출 계측 4종 — worker가 jobs.result에 남기는 관측값.

    2026-08-03까지는 콜백 페이로드의 일부였다. 지출 상세 화면 4종 어디에도 표시되지
    않아 콜백에서 덜어냈고(`docs/internal/화면_대조_2026-08-03.md` §4), 계산 로직만
    여기 남겨 worker가 쓴다 — 원래 이 값들을 만들던 자리가 여기이기 때문이다.
    """
    # llm_meta 실측치 (B2→B4): adjudicator는 escalate 경로(영수증 불일치·가드레일
    # 차단)에선 실행되지 않으므로 반드시 .get() — 대괄호 접근이면 콜백이 크래시한다
    llm_meta = state.get("llm_meta") or {}
    adj = llm_meta.get("adjudicator")
    started_at = state.get("started_at")
    return {
        "model_version": adj.model if adj else "mock",
        "prompt_version": adj.prompt_version if adj and adj.prompt_version else "review/v1",
        "cost_usd": round(sum(m.cost_usd for m in llm_meta.values()), 6),
        "latency_ms": int((time.time() - started_at) * 1000) if started_at else 0,
    }


# 콜백 opinions 배열의 고정 순서 — **[증빙, 예산, 판례, 회칙]** (계약 문서
# docs/풀스택_연동_계약.md의 2026-08-11 갱신 블록이 제안한 순서이자 실화면 순서).
#
# **왜 필요한가.** 심사관 3종은 병렬 노드고 opinions는 리듀서(merge_opinions)가 fan-in
# 시점에 병합하는 dict다 — dict 삽입 순서가 **매 실행마다 완료 순서에 따라 달라진다**.
# 각 소견에 auditor 필드가 있으니 수신 측이 그 필드로 매핑하면 문제가 없지만, 배열
# 순서로 카드를 그리면 "회칙 심사관 자리에 영수증 내용"처럼 라벨이 어긋난다
# (2026-08-11 배포 데모에서 실제로 발생 — 같은 지출을 새로고침할 때마다 내용이 바뀜).
# 순서를 고정하면 수신 측 구현과 무관하게 안정된다.
#
# **값의 근거 (2026-08-12 정정, #86).** 처음 고정할 때(PR #62, 리뷰 없이 머지)
# [회칙, 예산, 판례, 증빙]을 "화면 카드 순서"라 주장했으나, 그 29분 전에 계약 문서가
# 제안한 순서·실화면 확인과 정반대였다. 증빙(영수증 대조)이 처리상 가장 먼저 나오는
# 값이라 화면·코드 양쪽에서 순서의 이유를 설명하기 쉽다는 문서의 논거를 따른다.
# 수신 측 매핑 계약은 여전히 배열 위치가 아니라 auditor 값이다(문서 같은 블록).
_OPINION_ORDER = ("evidence", "budget", "precedent", "rule")


def opinion_sort_key(auditor: str) -> tuple:
    """소견 순서 계약의 정렬 키 — 알려진 심사관은 고정 순서, 신설은 뒤에 이름순.

    **출구가 콜백 하나가 아니라서 공개 함수다** (#86, 용어 치환 #71→#73과 같은 구조):
    worker가 `jobs.result`에 저장하는 opinions는 삽입 순서 그대로라, 폴링 안전망
    (`GET /v1/jobs/{job_id}`)이 콜백과 다른 순서로 내보냈다. `app/api/jobs.py`가
    조회 시점에 이 키로 같은 정렬을 적용한다 — 순서 규칙을 두 벌로 만들지 않는다.
    """
    if auditor in _OPINION_ORDER:
        return (0, _OPINION_ORDER.index(auditor))
    return (1, auditor)


def ordered_opinions(opinions: dict[str, Any]) -> list:
    """소견을 고정 순서로 정렬. 목록에 없는 키(향후 신설 심사관)는 뒤에 이름순으로."""
    return [opinions[k] for k in sorted(opinions, key=opinion_sort_key)]


# 판례 인용 접두 "(결정/결정주체[, override])" → 한국어 (2026-08-11).
#
# **왜 여기서 치환하는가.** precedent_auditor._precedent_lines가 LLM 입력에 이
# 표기를 쓰는 것과 precedent_auditor/v5.yaml이 similar_cases에 "입력 표기 그대로"
# 인용하도록 강제하는 것은 그대로 둔다 — "ADMIN 판례만 근거" 규칙이 이 표기에
# 의존하고(precedent_auditor.py _precedent_lines 참조), 입력 표기 그대로 인용해야
# 충실성(환각 여부)을 원문 대조로 검증할 수 있다. 대신 사용자에게 나가는 마지막
# 지점에서만 코드가 결정적으로 옮긴다 — LLM에게 번역을 시키면 의역 드리프트·환각
# 표면이 새로 생긴다.
#
# **출구는 콜백 하나가 아니다** (#71): 콜백이 유실되면 백엔드가
# `GET /v1/jobs/{job_id}`로 폴링하고(§7.1 안전망), 그 응답은 worker가 저장한
# 원본 opinions를 그대로 싣는다. 그래서 `translate_precedent_citation`은 공개
# 함수로 두고 `app/api/jobs.py`가 조회 시점에 같은 치환을 적용한다 — 저장 시점이
# 아니라 조회 시점에 거는 이유는 이미 저장된 잡 결과까지 함께 덮기 위해서다.
_CITATION_PREFIX_RE = re.compile(r"^\((approve|reject|escalate)/(ADMIN|AGENT)(, override)?\)\s*")
_CITATION_DECISION_LABELS = {"approve": "승인", "reject": "반려", "escalate": "보류"}
_CITATION_ACTOR_LABELS = {"ADMIN": "관리자", "AGENT": "AI 자동"}


def translate_precedent_citation(citation: str) -> str:
    """판례 인용 문자열의 시스템 표기 접두만 한국어로 옮긴다 (순수 함수).

    접두 뒤 본문("사유: ..." 포함)은 관리자가 원래 남긴 자유 텍스트이므로 그대로
    둔다. 접두가 이 형식이 아니면(향후 표기 변경 등) 원문을 그대로 반환한다 —
    숨기면 새 표기가 조용히 새어 나간다(escalate.describe_rules의 미등록 규칙
    폴백과 같은 원칙).
    """
    match = _CITATION_PREFIX_RE.match(citation)
    if not match:
        return citation
    decision, actor, override = match.groups()
    label = f"({_CITATION_ACTOR_LABELS[actor]} {_CITATION_DECISION_LABELS[decision]}"
    if override:
        label += "·AI 추천 번복"
    return label + ") " + citation[match.end() :]


def _translate_opinion_citations(opinion: Opinion) -> Opinion:
    if not opinion.similar_cases:
        return opinion
    return opinion.model_copy(
        update={"similar_cases": [translate_precedent_citation(c) for c in opinion.similar_cases]}
    )


def build_callback_payload(state: ReviewState) -> CallbackPayload:
    verdict = state.get("verdict") or "escalate"
    return CallbackPayload(
        # 백엔드 발급 jobId를 echo (pull 모델) — 없으면(직접 그래프 호출) 내부 id
        job_id=state.get("external_job_id") or state["job_id"],
        expense_id=state["expense_id"],
        team_id=state["team_id"],
        verdict=verdict,
        # AI가 확정한 카테고리 (T7 — AI 분류가 유일한 출처). 백엔드는 첫 심사 콜백의
        # 이 값으로 expenses.category를 채운다(8/6 회신) — API-045/046 suggestedCategory.
        # (구 ai_suggested_category 우선 참조는 필드 제거와 함께 정리 — 2026-08-06)
        suggested_category=state["claim"].category or None,
        processed_by=resolve_processed_by(verdict, state.get("admin_decision")),
        confidence=state.get("confidence"),
        opinions=[
            _translate_opinion_citations(o) for o in ordered_opinions(state.get("opinions", {}))
        ],
        mismatch=state.get("mismatch", []),
        reasons=state.get("reasons"),
    )


async def callback(state: ReviewState) -> dict:
    payload = build_callback_payload(state)
    # by_alias=True 필수 — 백엔드 API는 전부 camelCase (§ bravo_API명세서.xlsx)
    ok = await send_callback(payload.model_dump(mode="json", by_alias=True))
    return {"callback_status": "sent" if ok else "failed"}
