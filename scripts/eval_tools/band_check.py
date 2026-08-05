"""마법사 2단계 구간표가 실제 가드레일과 맞는지 전수 확인.

화면 표: 소액(5만 미만) AI 자동 승인 / 중간(5~20만) 대기·자동 / 고액(20만 이상) 관리자 필수
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails
from app.schemas.common import Opinion, PolicyParams

ALL_PASS = {
    "rule": Opinion(auditor="rule", verdict="pass", summary=""),
    "budget": Opinion(auditor="budget", verdict="pass", summary=""),
    "precedent": Opinion(auditor="precedent", verdict="pass", summary=""),
}

AMOUNTS = [10_000, 30_000, 49_999, 50_000, 80_000, 150_000, 199_999, 200_000, 300_000]


def band(amount: int) -> str:
    if amount < 50_000:
        return "소액"
    if amount < 200_000:
        return "중간"
    return "고액"


for toggle_on in (False, True):
    # 화면 토글 '모든 지출 직접 확인' — 켜면 auto_approve=False
    policy = PolicyParams(auto_approve=not toggle_on,
                          auto_approve_limit=50_000,
                          force_escalation_amount=200_000)
    label = "켬 (모든 지출 직접 확인)" if toggle_on else "끔 (기본값)"
    print(f"\n{'='*74}\n토글 {label}\n{'='*74}")
    print(f"{'금액':>10} {'구간':<5} {'화면 표기':<14} {'실제 결과':<12} 발동 규칙")
    print("-" * 74)
    for amt in AMOUNTS:
        gate = evaluate_guardrails(ALL_PASS, [], policy, amt)
        b = band(amt)
        screen = {"소액": "AI 자동 승인", "중간": "대기/자동", "고액": "관리자 필수"}[b]
        actual = {"proceed": "AI 판정 진행", "escalate": "관리자 확인",
                  "reject_candidate": "반려 후보"}[gate.decision]
        mark = "" if (
            (b == "소액" and gate.decision == "proceed" and not toggle_on)
            or (b == "고액" and gate.decision == "escalate")
            or (toggle_on and gate.decision == "escalate")
        ) else "  <-- 화면과 다름"
        print(f"{amt:>10,} {b:<5} {screen:<14} {actual:<12} "
              f"{','.join(gate.triggered_rules) or '-'}{mark}")
