"""mismatch_gate — 영수증-청구 대조 (REQ-028). 순수 비교, 부수효과 없음.

대조 결과를 **증빙 심사관 소견**으로도 내보낸다 (풀스택 협의 2026-08-04 — 지출 상세
'AI 심사결과'에 증빙 심사관 추가). 회칙·예산·판례와 같은 `Opinion` 형식이라 화면이
네 번째 심사관으로 그대로 그릴 수 있다.

**판정 권한은 없다.** 에스컬레이션 여부는 가드레일이 기존대로 `mismatch` 리스트와
`receipt_parse_ok`로 결정하고, 이 소견은 근거를 화면에 남기기 위한 표현이다. 불일치
건은 심사관 3종을 거치지 않고 바로 보류되므로(`route_after_mismatch`), 이 소견이
없으면 화면에 "왜 보류됐는지"가 소견 형태로 남지 않는다.
"""
from app.graphs.review.state import ReviewState
from app.schemas.common import ExpenseClaim, Mismatch, Opinion, ReceiptData

FIELD_LABELS = {"amount": "금액", "date": "날짜"}


def _receipt_opinion(receipt: ReceiptData | None, claim: ExpenseClaim,
                     mismatches: list[Mismatch]) -> Opinion:
    """증빙 심사관 소견 (순수 함수) — 표시 전용. 가드레일 판단과 의미를 맞춘다."""
    if receipt is None or not receipt.parse_ok:
        return Opinion(
            auditor="evidence", verdict="warn",
            summary=("영수증을 판독하지 못했습니다 — 관리자 확인이 필요합니다."
                     if receipt is not None
                     else "영수증이 첨부되지 않았습니다 — 관리자 확인이 필요합니다."),
        )

    figures: dict[str, int | float] = {"claimed_amount": claim.amount}
    if receipt.amount is not None:
        figures["receipt_amount"] = receipt.amount

    # 읽어낸 값을 근거로 남긴다 — 관리자가 화면에서 "무엇을 보고 판단했는지" 알 수 있게
    # (풀스택 협의 2026-08-04 8번: OCR 추출값 상호명·날짜·금액).
    read = [f"상호 {receipt.merchant}"] if receipt.merchant else []
    if receipt.amount is not None:
        read.append(f"금액 {receipt.amount:,}원")
    if receipt.date:
        read.append(f"날짜 {receipt.date}")
    if receipt.items:
        read.append(f"품목 {', '.join(receipt.items[:3])}")
    evidence = [f"영수증에서 읽은 값: {' · '.join(read)}"] if read else []

    if mismatches:
        detail = ", ".join(
            f"{FIELD_LABELS.get(m.field, m.field)} 청구 {m.claimed} / 영수증 {m.receipt}"
            for m in mismatches
        )
        return Opinion(
            auditor="evidence", verdict="fail",
            summary=f"영수증과 청구 내용이 일치하지 않습니다 — {detail}",
            evidence=[detail, *evidence], figures=figures,
        )
    where = f" — {receipt.merchant}" if receipt.merchant else ""
    return Opinion(
        auditor="evidence", verdict="pass",
        summary=f"영수증이 청구 내용과 일치합니다 (금액 {claim.amount:,}원){where}.",
        evidence=evidence, figures=figures,
    )


async def mismatch_gate(state: ReviewState) -> dict:
    receipt = state.get("receipt_data")
    claim = state["claim"]
    mismatches: list[Mismatch] = []

    # 판독 불능은 mismatch가 아니라 가드레일의 receipt_unreadable로 처리된다 (§8) —
    # 그래서 대조는 판독에 성공했을 때만 수행하고, mismatch 리스트의 의미는 그대로다.
    if receipt is not None and receipt.parse_ok:
        if receipt.amount is not None and receipt.amount != claim.amount:
            mismatches.append(Mismatch(field="amount",
                                       claimed=str(claim.amount), receipt=str(receipt.amount)))
        if receipt.date is not None and receipt.date != claim.date:
            mismatches.append(Mismatch(field="date", claimed=claim.date, receipt=receipt.date))

    return {"mismatch": mismatches,
            "opinions": {"evidence": _receipt_opinion(receipt, claim, mismatches)}}


AUDITORS = ["rule_auditor", "budget_auditor", "precedent_auditor"]


def route_after_mismatch(state: ReviewState) -> str | list[str]:
    """조건부 엣지: 불일치 → escalate로 직행, 일치 → 3-심사관 병렬 fan-out (§3.2)."""
    return "escalate" if state.get("mismatch") else AUDITORS
