"""증빙 심사관 소견 (풀스택 협의 2026-08-04 — 지출 상세 'AI 심사결과' 네 번째 심사관).

`mismatch_gate`가 영수증-청구 대조 결과를 회칙·예산·판례와 같은 `Opinion` 형식으로도
내보낸다. 화면 표시용이고 **판정 권한은 없다** — 에스컬레이션은 가드레일이 기존대로
mismatch 리스트와 receipt_parse_ok로 결정한다. 그 경계가 지켜지는지까지 검증한다.
"""
from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails
from app.graphs.review.nodes.mismatch_gate import mismatch_gate, route_after_mismatch
from app.schemas.common import ExpenseClaim, Opinion, PolicyParams, ReceiptData

CLAIM = ExpenseClaim(title="스터디 교재", amount=32_000, category="교재/자료비",
                     date="2026-07-01", description="알고리즘 교재")
POLICY = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                      force_escalation_amount=200_000)
OTHERS = {k: Opinion(auditor=k, verdict="pass", summary="") for k in ("rule", "budget", "precedent")}


async def _run(receipt: ReceiptData | None) -> dict:
    return await mismatch_gate({"claim": CLAIM, "receipt_data": receipt})


async def test_matching_receipt_gives_pass_opinion():
    result = await _run(ReceiptData(amount=32_000, date="2026-07-01", parse_ok=True))
    op = result["opinions"]["receipt"]
    assert op.auditor == "receipt"
    assert op.verdict == "pass"
    assert "32,000원" in op.summary
    assert op.figures == {"claimed_amount": 32_000, "receipt_amount": 32_000}
    assert result["mismatch"] == []


# ── OCR 추출값 노출 (풀스택 협의 2026-08-04 8번) ──────────────────────────

async def test_merchant_appears_in_summary_and_evidence():
    """상호명을 읽었으면 소견에 드러난다 — 관리자가 무엇을 보고 판단했는지 알 수 있게."""
    result = await _run(ReceiptData(amount=32_000, date="2026-07-01", merchant="교보문고 광화문점",
                                    items=["알고리즘 교재"], parse_ok=True))
    op = result["opinions"]["receipt"]
    assert "교보문고 광화문점" in op.summary
    read = " ".join(op.evidence)
    assert "교보문고 광화문점" in read
    assert "32,000원" in read and "2026-07-01" in read
    assert "알고리즘 교재" in read


async def test_no_merchant_still_reads_cleanly():
    """상호명을 못 읽어도 문장이 어색해지지 않는다."""
    result = await _run(ReceiptData(amount=32_000, date="2026-07-01", parse_ok=True))
    op = result["opinions"]["receipt"]
    assert op.summary.endswith("일치합니다 (금액 32,000원).")
    assert "상호" not in " ".join(op.evidence)


async def test_mismatch_keeps_both_reason_and_read_values():
    """불일치일 때도 읽은 값이 함께 남아야 관리자가 대조할 수 있다."""
    result = await _run(ReceiptData(amount=25_000, date="2026-07-01",
                                    merchant="○○마트", parse_ok=True))
    op = result["opinions"]["receipt"]
    assert op.verdict == "fail"
    joined = " ".join(op.evidence)
    assert "청구 32000" in joined and "영수증 25000" in joined   # 불일치 사유
    assert "○○마트" in joined                                    # 읽은 값


async def test_amount_mismatch_gives_fail_opinion_with_both_numbers():
    """관리자가 화면에서 '무엇이 어긋났는지' 바로 읽을 수 있어야 한다."""
    result = await _run(ReceiptData(amount=25_000, date="2026-07-01", parse_ok=True))
    op = result["opinions"]["receipt"]
    assert op.verdict == "fail"
    assert "금액" in op.summary and "32000" in op.summary and "25000" in op.summary
    assert op.figures["claimed_amount"] == 32_000
    assert op.figures["receipt_amount"] == 25_000
    assert [m.field for m in result["mismatch"]] == ["amount"]


async def test_unreadable_receipt_gives_warn_not_fail():
    """판독 불능은 '불일치'가 아니다 — mismatch 리스트는 비어 있어야 한다 (§8 경로 유지)."""
    result = await _run(ReceiptData(amount=None, date=None, parse_ok=False))
    op = result["opinions"]["receipt"]
    assert op.verdict == "warn"
    assert "판독" in op.summary
    assert result["mismatch"] == []


async def test_missing_receipt_says_not_attached():
    result = await _run(None)
    op = result["opinions"]["receipt"]
    assert op.verdict == "warn"
    assert "첨부" in op.summary
    assert result["mismatch"] == []


async def test_date_mismatch_is_detected():
    result = await _run(ReceiptData(amount=32_000, date="2026-06-30", parse_ok=True))
    assert result["opinions"]["receipt"].verdict == "fail"
    assert [m.field for m in result["mismatch"]] == ["date"]


# ── 경계: 증빙 심사관은 판정을 바꾸지 않는다 ──────────────────────────────

async def test_receipt_opinion_does_not_change_routing():
    """라우팅은 mismatch 리스트만 본다 — 소견이 추가돼도 경로가 그대로다."""
    ok = await _run(ReceiptData(amount=32_000, date="2026-07-01", parse_ok=True))
    bad = await _run(ReceiptData(amount=25_000, date="2026-07-01", parse_ok=True))
    unreadable = await _run(ReceiptData(amount=None, date=None, parse_ok=False))

    assert route_after_mismatch(ok) != "escalate"          # 심사관 3종 fan-out
    assert route_after_mismatch(bad) == "escalate"
    # 판독 불능은 mismatch가 없으므로 여기서 막히지 않고 가드레일이 잡는다
    assert route_after_mismatch(unreadable) != "escalate"


def test_receipt_opinion_is_not_a_required_auditor():
    """증빙 소견이 fail이어도 그 자체로 가드레일을 발동시키지 않는다.

    누락 심사관 검사(REQUIRED_AUDITORS)에도 들어가지 않아야 한다 — 판정 권한 없음.
    """
    with_receipt = {**OTHERS,
                    "receipt": Opinion(auditor="receipt", verdict="fail", summary="불일치")}
    gate = evaluate_guardrails(opinions=with_receipt, mismatch=[], policy=POLICY, amount=32_000)
    assert gate.decision == "proceed"          # 소견만으로는 아무 일도 없다

    # 실제 보류는 mismatch 리스트가 만든다 (기존 계약)
    from app.schemas.common import Mismatch
    gate2 = evaluate_guardrails(opinions=with_receipt,
                                mismatch=[Mismatch(field="amount", claimed="32000",
                                                   receipt="25000")],
                                policy=POLICY, amount=32_000)
    assert gate2.decision == "escalate"
    assert "receipt_mismatch" in gate2.triggered_rules


def test_required_auditors_unchanged():
    """증빙 심사관이 없어도 심사는 성립한다 — 필수 3종 계약 불변."""
    from app.graphs.review.nodes.guardrail_gate import REQUIRED_AUDITORS
    assert REQUIRED_AUDITORS == ("rule", "budget", "precedent")
