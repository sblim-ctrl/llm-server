"""마법사 2단계 설정값이 심사 판정을 어떻게 가르는지 실측표로 출력한다.

풀스택 협의용 — 2단계 화면의 금액 1종('관리자 승인 필수 금액')·토글 1종이 실제로 어떤
판정을 만드는지 `evaluate_guardrails`(순수 함수)를 그대로 호출해 보여준다. 백엔드
응답에서 `PolicyParams`를 만드는 해석도 심사 경로와 같은 `map_team_settings`를 쓴다.
DB·LLM·백엔드 없이 돈다.

    uv run python scripts/wizard_step2_matrix.py

2026-08-05 화면 개편(금액 칸 2개 → 1개, 경계 '이상', 최소 5만원)이 심사에 그대로
반영됐는지 눈으로 확인하는 것이 목적이다. 소견 3종은 전부 pass(이상 없음)로 고정한다
— 금액 규칙만 분리해 보기 위해서다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.graphs.review.nodes.guardrail_gate import evaluate_guardrails  # noqa: E402
from app.schemas.common import Opinion, PolicyParams  # noqa: E402
from app.tools.policy_params import (  # noqa: E402
    effective_auto_approve_limit,
    map_team_settings,
)

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
        gate = evaluate_guardrails(opinions=CLEAN_OPINIONS, mismatch=[], policy=policy, amount=amt)
        rows.append((amt, gate.decision, gate.triggered_rules))
    return rows


def show(title: str, policy: PolicyParams) -> None:
    print(f"\n### {title}")
    print(
        f"    auto_approve={policy.auto_approve} · "
        f"auto_approve_limit={policy.auto_approve_limit:,} · "
        f"force_escalation_amount={policy.force_escalation_amount:,}"
    )
    print(f"    {'청구액':>10} | {'판정':<16} | 발동 규칙")
    print(f"    {'-' * 10}-+-{'-' * 16}-+-{'-' * 40}")
    for amt, decision, rules in run(policy):
        print(f"    {amt:>10,} | {DECISION_LABEL[decision]:<16} | {', '.join(rules) or '—'}")


print("마법사 2단계 설정값 → 심사 판정 실측표")
print("(소견 3종 전부 pass 고정 — 금액 규칙만 분리)")

show(
    "A. 화면 최소값 — 관리자 승인 필수 금액 5만 (자동 심사 켬)",
    map_team_settings({"auto_approve": True, "auto_approve_limit": 50_000}),
)

show(
    "B. 토글 켬 — '모든 지출을 직접 확인할래요' (auto_approve=false)",
    map_team_settings({"auto_approve": False, "auto_approve_limit": 50_000}),
)

show(
    "C. 관리자가 50만으로 올림",
    map_team_settings({"auto_approve": True, "auto_approve_limit": 500_000}),
)

show(
    "D. 컬럼 삭제 전 잔존 데이터 — 두 값이 따로 저장된 팀 (한도 15만 / 고액 20만)",
    map_team_settings(
        {"auto_approve": True, "auto_approve_limit": 150_000, "escalation_threshold": 200_000}
    ),
)

# ── 경계가 '이상'인지 확인 ───────────────────────────────────────────────
print("\n\n### 확인: 경계는 '이상'이다 (2026-08-05 화면 개편으로 확정)")
policy = map_team_settings({"auto_approve": True, "auto_approve_limit": 50_000})
for amt in (49_999, 50_000):
    gate = evaluate_guardrails(opinions=CLEAN_OPINIONS, mismatch=[], policy=policy, amount=amt)
    print(f"    {amt:>10,}원 → {DECISION_LABEL[gate.decision]}")
print("\n    → 화면 표의 '5만원 미만 = 자동 승인/검토 요청', '5만원 이상 = 관리자 승인 항상'과")
print("      같은 기준이다. 한도와 같은 금액은 관리자 확인이다.")

# ── escalation_threshold 컬럼 삭제가 한도를 축소하지 않는지 ──────────────
print("\n\n### 확인: escalation_threshold 컬럼이 없어도 관리자 설정값이 유지되는가")
deleted = map_team_settings({"auto_approve": True, "auto_approve_limit": 500_000})
print(
    f"    응답에 auto_approve_limit=500,000만 있을 때 → "
    f"실효 한도 {effective_auto_approve_limit(deleted):,}원"
)
print("    → 모델 기본값 200,000으로 축소되지 않는다. 축소되면 화면에는 50만인데")
print("      심사는 20만부터 관리자 확인이 되어 조용히 어긋난다(2026-07-31 사고 유형).")
