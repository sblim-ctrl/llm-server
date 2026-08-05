"""마법사 2단계 설정값이 심사 판정을 어떻게 가르는지 실측표로 출력한다.

풀스택 협의용 — 2단계 화면의 금액 2종·토글 1종이 실제로 어떤 판정을 만드는지
`evaluate_guardrails`(순수 함수)를 그대로 호출해 보여준다. DB·LLM·백엔드 없이 돈다.

    uv run python scripts/wizard_step2_matrix.py

화면 대조 §2-4("중간 구간 5만~20만의 '대기/자동'이 무슨 뜻인가")에 코드로 답하는 것이
목적이다. 소견 3종은 전부 pass(이상 없음)로 고정한다 — 금액 규칙만 분리해 보기 위해서다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails  # noqa: E402
from app.schemas.common import Opinion, PolicyParams  # noqa: E402

CLEAN_OPINIONS = {
    "rule": Opinion(auditor="rule", verdict="pass", summary="회칙 위반 없음"),
    "budget": Opinion(auditor="budget", verdict="pass", summary="잔액 충분"),
    "precedent": Opinion(auditor="precedent", verdict="pass", summary="유사 판례 없음"),
}

DECISION_LABEL = {
    "proceed": "자동 판정 진행",
    "escalate": "관리자 확인(대기)",
    "reject_candidate": "반려 후보",
}

AMOUNTS = [10_000, 49_999, 50_000, 50_001, 120_000, 199_999, 200_000, 200_001, 500_000]


def run(policy: PolicyParams, amounts=AMOUNTS) -> list[tuple]:
    rows = []
    for amt in amounts:
        gate = evaluate_guardrails(
            opinions=CLEAN_OPINIONS, mismatch=[], policy=policy, amount=amt
        )
        rows.append((amt, gate.decision, gate.triggered_rules))
    return rows


def show(title: str, policy: PolicyParams) -> None:
    print(f"\n### {title}")
    print(f"    auto_approve={policy.auto_approve} · "
          f"auto_approve_limit={policy.auto_approve_limit:,} · "
          f"force_escalation_amount={policy.force_escalation_amount:,}")
    print(f"    {'청구액':>10} | {'판정':<16} | 발동 규칙")
    print(f"    {'-' * 10}-+-{'-' * 16}-+-{'-' * 40}")
    for amt, decision, rules in run(policy):
        print(f"    {amt:>10,} | {DECISION_LABEL[decision]:<16} | {', '.join(rules) or '—'}")


print("마법사 2단계 설정값 → 심사 판정 실측표")
print("(소견 3종 전부 pass 고정 — 금액 규칙만 분리)")

show("A. 화면 기본값 (소액 5만 / 고액 20만, 자동 심사 켬)",
     PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                  force_escalation_amount=200_000))

show("B. 토글 켬 — '모든 지출을 직접 확인할래요' (auto_approve=false)",
     PolicyParams(auto_approve=False, auto_approve_limit=50_000,
                  force_escalation_amount=200_000))

show("C. 관리자가 고액 기준만 30만으로 올림",
     PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                  force_escalation_amount=300_000))

show("D. 관리자가 소액 한도를 15만으로 올림 (고액 20만 유지)",
     PolicyParams(auto_approve=True, auto_approve_limit=150_000,
                  force_escalation_amount=200_000))

# ── 두 금액 칸이 서로 어떤 관계인지 ──────────────────────────────────────
print("\n\n### 확인: 두 금액 칸이 독립적으로 작동하는가")
base = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                    force_escalation_amount=200_000)
raised = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                      force_escalation_amount=300_000)
diff = [(a, d1, d2) for (a, d1, _), (_, d2, _) in zip(run(base), run(raised)) if d1 != d2]
print(f"    고액 기준을 20만 → 30만으로 바꿨을 때 판정이 달라지는 금액: "
      f"{[f'{a:,}' for a, _, _ in diff] or '없음'}")

lowered = PolicyParams(auto_approve=True, auto_approve_limit=50_000,
                       force_escalation_amount=30_000)
diff2 = [(a, d1, d2) for (a, d1, _), (_, d2, _) in zip(run(base), run(lowered)) if d1 != d2]
print(f"    고액 기준을 20만 → 3만으로 내렸을 때 판정이 달라지는 금액: "
      f"{[f'{a:,}' for a, _, _ in diff2] or '없음'}")
print("\n    → 두 칸 중 실제로 자동/대기를 가르는 것은 항상 작은 쪽이다.")
print("      min(소액 한도, 고액 기준) 초과 = 관리자 확인.")
