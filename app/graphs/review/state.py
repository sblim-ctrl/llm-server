"""심사 그래프 상태 스키마 (§4.2).

병렬 심사관은 opinions에 자기 키로만 쓰고 reducer(merge_opinions)가 fan-in 시 병합한다
— 쓰기 충돌이 구조적으로 불가능.
"""
from typing import Annotated, TypedDict

from app.schemas.common import (
    ExpenseClaim, GateResult, Mismatch, Opinion, PolicyParams, Reasons, ReceiptData, Verdict,
)


def merge_opinions(left: dict[str, Opinion] | None,
                   right: dict[str, Opinion] | None) -> dict[str, Opinion]:
    return {**(left or {}), **(right or {})}


class ReviewState(TypedDict, total=False):
    # 입력
    job_id: str
    expense_id: str
    team_id: str
    claim: ExpenseClaim
    receipt_url: str | None
    # 컨텍스트 (load_context가 씀)
    policy_params: PolicyParams
    rule_version: int
    # 진행 산출물
    receipt_data: ReceiptData | None
    mismatch: list[Mismatch]
    opinions: Annotated[dict[str, Opinion], merge_opinions]
    gate_result: GateResult | None
    # 최종
    verdict: Verdict | None
    confidence: float | None
    reasons: Reasons | None
    execution_result: dict | None
    callback_status: str | None
