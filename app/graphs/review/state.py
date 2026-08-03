"""심사 그래프 상태 스키마 (§4.2).

병렬 심사관은 opinions에 자기 키로만 쓰고 reducer(merge_opinions)가 fan-in 시 병합한다
— 쓰기 충돌이 구조적으로 불가능.
"""
from typing import Annotated, TypedDict

from app.schemas.common import (
    ExpenseClaim, GateResult, LLMCallMeta, Mismatch, Opinion, PolicyParams, Reasons,
    ReceiptData, Verdict,
)


def merge_opinions(left: dict[str, Opinion] | None,
                   right: dict[str, Opinion] | None) -> dict[str, Opinion]:
    return {**(left or {}), **(right or {})}


def merge_llm_meta(left: dict[str, LLMCallMeta] | None,
                   right: dict[str, LLMCallMeta] | None) -> dict[str, LLMCallMeta]:
    return {**(left or {}), **(right or {})}


class ReviewState(TypedDict, total=False):
    # 입력 (pull 모델 — bravo 설계서 TABLE 18: 백엔드는 5필드만 보낸다)
    job_id: str                 # 내부 jobs.id — thread_id·체크포인트 키
    external_job_id: str        # 백엔드 발급 jobId — 콜백에서 그대로 echo (ai_job_id 대조)
    expense_id: str
    team_id: str                # 백엔드 organizationId — 내부 키 이름은 team_id 유지
    review_goal: str            # 심사 목표 지시문 — 보관만, 판정 미반영 (schemas/analyze.py 참조)
    receipt_path: str | None    # 영수증 조회 경로 — intake가 Agent 토큰으로 되물어 조회
    claim: ExpenseClaim         # load_context가 pull로 채움 (직접 호출 시엔 초기 상태로 주입 가능)
    receipt_url: str | None     # 구 계약 잔재 — 직접 그래프 호출·mock:// 오버라이드용
    receipt_text: str | None    # 백엔드가 미리 추출한 영수증 텍스트 (있으면 Vision 생략)
    # 컨텍스트 (load_context가 씀)
    started_at: float           # 심사 시작 시각(time.time()) — 콜백 latency_ms 계산용 (B4)
    policy_params: PolicyParams
    rule_version: int
    team_type: str              # 모임 유형 — 유형별 카테고리 카탈로그 선택에 사용
    team_members: list[dict]    # PII 마스킹용 멤버 명단 — 조회 실패 시에도 [] 보장 (B2)
    # 분류 (classify_category가 씀) — "user"(직접 입력) | "ai"(자동 분류)
    category_source: str
    # 사용자 지정 카테고리 vs AI 분류의 '확신 있는 불일치' (2026-07-28 결정) —
    # 라벨은 사용자 것 유지, 가드레일이 category_mismatch로 보류시키고
    # AI 의견은 콜백 suggestedCategory로 관리자에게 전달
    category_mismatch: bool
    ai_suggested_category: str | None
    # 진행 산출물
    receipt_data: ReceiptData | None
    mismatch: list[Mismatch]
    opinions: Annotated[dict[str, Opinion], merge_opinions]
    # LLM 호출 계측 — 병렬 노드가 자기 agent 키로만 쓰고 reducer가 병합 (B2)
    llm_meta: Annotated[dict[str, LLMCallMeta], merge_llm_meta]
    gate_result: GateResult | None
    # HITL(사람 개입, 강의 06-02 — 데모·관측 경로 전용): hitl_enabled면 escalate
    # 노드가 interrupt()로 멈추고, 관리자 결정이 admin_decision으로 기록된다.
    # 워커 경로는 이 키가 없어 기존 동작 불변.
    hitl_enabled: bool
    admin_decision: dict | None
    # 최종
    verdict: Verdict | None
    confidence: float | None
    reasons: Reasons | None
    execution_result: dict | None
    callback_status: str | None
