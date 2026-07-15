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
    # 입력
    job_id: str
    expense_id: str
    team_id: str
    claim: ExpenseClaim
    receipt_url: str | None
    receipt_text: str | None    # 백엔드가 미리 추출한 영수증 텍스트 (있으면 Vision 생략)
    # 컨텍스트 (load_context가 씀)
    policy_params: PolicyParams
    rule_version: int
    team_type: str              # 모임 유형 — 유형별 카테고리 카탈로그 선택에 사용
    team_members: list[dict]    # PII 마스킹용 멤버 명단 — 조회 실패 시에도 [] 보장 (B2)
    # 분류 (classify_category가 씀) — "user"(직접 입력) | "ai"(자동 분류)
    category_source: str
    # 진행 산출물
    receipt_data: ReceiptData | None
    mismatch: list[Mismatch]
    opinions: Annotated[dict[str, Opinion], merge_opinions]
    # LLM 호출 계측 — 병렬 노드가 자기 agent 키로만 쓰고 reducer가 병합 (B2)
    llm_meta: Annotated[dict[str, LLMCallMeta], merge_llm_meta]
    gate_result: GateResult | None
    # 최종
    verdict: Verdict | None
    confidence: float | None
    reasons: Reasons | None
    execution_result: dict | None
    callback_status: str | None
