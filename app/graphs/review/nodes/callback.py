"""callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)."""

import time
from typing import Any

from app.graphs.review.state import ReviewState
from app.schemas.callback import CallbackPayload
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


# 콜백 opinions 배열의 고정 순서. 화면 카드 순서(회칙·예산·이상탐지·증빙)와 같다.
#
# **왜 필요한가.** 심사관 3종은 병렬 노드고 opinions는 리듀서(merge_opinions)가 fan-in
# 시점에 병합하는 dict다 — dict 삽입 순서가 **매 실행마다 완료 순서에 따라 달라진다**.
# 게다가 evidence는 fan-out 이전(mismatch_gate)에 들어가 항상 맨 앞이라, 순서가
# [evidence, ?, ?, ?]로 나가고 뒤 3개는 실행마다 뒤바뀐다.
# 각 소견에 auditor 필드가 있으니 수신 측이 그 필드로 매핑하면 문제가 없지만, 배열
# 순서로 카드를 그리면 "회칙 심사관 자리에 영수증 내용"처럼 라벨이 어긋난다
# (2026-08-11 배포 데모에서 실제로 발생 — 같은 지출을 새로고침할 때마다 내용이 바뀜).
# 순서를 계약으로 고정하면 수신 측 구현과 무관하게 안정된다.
_OPINION_ORDER = ("rule", "budget", "precedent", "evidence")


def ordered_opinions(opinions: dict[str, Any]) -> list:
    """소견을 고정 순서로 정렬. 목록에 없는 키(향후 신설 심사관)는 뒤에 이름순으로."""
    known = [opinions[k] for k in _OPINION_ORDER if k in opinions]
    extra = [opinions[k] for k in sorted(opinions) if k not in _OPINION_ORDER]
    return known + extra


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
        opinions=ordered_opinions(state.get("opinions", {})),
        mismatch=state.get("mismatch", []),
        reasons=state.get("reasons"),
    )


async def callback(state: ReviewState) -> dict:
    payload = build_callback_payload(state)
    # by_alias=True 필수 — 백엔드 API는 전부 camelCase (§ bravo_API명세서.xlsx)
    ok = await send_callback(payload.model_dump(mode="json", by_alias=True))
    return {"callback_status": "sent" if ok else "failed"}
