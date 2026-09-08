"""boundary 유형 — 금액·예산 임계값이 '이상(>=)' 경계에 정확히 걸리는 케이스.

3개 축을 나눠서 본다:
  1. auto_approve_limit(50,000) 경계 — 49,999(approve) vs 50,000(escalate)
  2. force_escalation_amount(200,000) 경계 — 199,999 vs 200,000 (둘 다 escalate이지만
     발동 게이트 목록이 다르다 — over_force_escalation_amount 유무)
  3. 예산 사용률 90% 경계 — budget_auditor의 verdict만 pass↔warn으로 바뀔 뿐,
     guardrail_gate는 verdict=="fail"만 보므로(app/graphs/review/nodes/guardrail_gate.py:95)
     **게이트·최종 판정에는 아무 영향이 없다**. "경계선이니 판정이 갈릴 것"이라는 직관과
     달리 실제로는 무영향이라는 사실 자체가 이 유형의 핵심 발견이다 — 시나리오 문구에 남긴다.

그리드 30×3=90건 + 하드 케이스 10건 = 100건.
"""

from scripts.golden_v2.case import build_case
from scripts.golden_v2.catalog import CATEGORY_TITLE_HINT, TEAM_TYPES
from scripts.golden_v2.engine import evaluate
from scripts.golden_v2.fixtures import FixtureRegistry

TYPE = "boundary"
DATE = "2026-07-12"

CATS = list(CATEGORY_TITLE_HINT.items())
AXIS1_CATS = CATS[0:3]  # 식비·교통·IT_인프라
AXIS2_CATS = CATS[3:6]  # 교육·회의·장소_대관
AXIS3_CATS = CATS[6:9]  # 행사_활동·비품·기타

DEFAULT_TOTAL, DEFAULT_SPENT = 300_000, 118_000  # 잔액 182,000 — 축1에 충분
BIG_TOTAL, BIG_SPENT = 1_000_000, 100_000  # 잔액 900,000 — 축2(20만원대)에 충분
USAGE_TOTAL = 100_000  # 축3 전용 — 사용률 90% 계산이 딱 떨어지게


def _emit(
    cases,
    reg,
    seq_holder,
    *,
    team_type,
    org_id,
    category,
    hint,
    amount,
    total,
    spent,
    note,
    difficulty="easy",
    auto_approve=True,
):
    seq_holder[0] += 1
    case_id = f"v2-boundary-{seq_holder[0]:03d}"
    expense_id = reg.add_expense(title=hint, amount=amount, date=DATE, description=note)
    outcome = evaluate(
        amount=amount,
        auto_approve=auto_approve,
        auto_approve_limit=50_000,
        force_escalation_amount=200_000,
        budget_total=total,
        budget_spent=spent,
        receipt_state="match",
    )
    cases.append(
        build_case(
            case_id=case_id,
            scenario=f"경계 — {note}",
            team_type=team_type,
            case_type=TYPE,
            difficulty=difficulty,
            mode_required="mock",
            organization_id=org_id,
            expense_id=expense_id,
            receipt_path=f"mock://receipt?amount={amount}&date={DATE}",
            expected_verdict=outcome.verdict,
            expected_category=category,
            expected_gate_includes=outcome.gate_includes,
        )
    )


def generate(reg: FixtureRegistry) -> list[dict]:
    cases: list[dict] = []
    seq = [0]

    default_org = {
        tt: reg.add_org(
            label=f"v2-boundary-default-{i}",
            team_type=tt,
            total_budget=DEFAULT_TOTAL,
            spent=DEFAULT_SPENT,
        )
        for i, tt in enumerate(TEAM_TYPES)
    }
    big_org = {
        tt: reg.add_org(
            label=f"v2-boundary-big-{i}", team_type=tt, total_budget=BIG_TOTAL, spent=BIG_SPENT
        )
        for i, tt in enumerate(TEAM_TYPES)
    }

    # 축 1 — auto_approve_limit 경계 (5팀 × 3카테고리 × 2사이드 = 30)
    for team_type in TEAM_TYPES:
        org_id = default_org[team_type]
        for category, hint in AXIS1_CATS:
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id,
                category=category,
                hint=hint,
                amount=49_999,
                total=DEFAULT_TOTAL,
                spent=DEFAULT_SPENT,
                note=f"{hint} — auto_approve_limit(50,000원)보다 정확히 1원 낮음 → approve",
            )
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id,
                category=category,
                hint=hint,
                amount=50_000,
                total=DEFAULT_TOTAL,
                spent=DEFAULT_SPENT,
                note=f"{hint} — auto_approve_limit(50,000원)과 정확히 같음(이상 규칙) → escalate",
            )

    # 축 2 — force_escalation_amount 경계 (5팀 × 3카테고리 × 2사이드 = 30)
    for team_type in TEAM_TYPES:
        org_id = big_org[team_type]
        for category, hint in AXIS2_CATS:
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id,
                category=category,
                hint=hint,
                amount=199_999,
                total=BIG_TOTAL,
                spent=BIG_SPENT,
                note=(
                    f"{hint} — force_escalation_amount(200,000원)보다 1원 낮음. "
                    "auto_approve_limit은 이미 넘어 escalate지만 over_force_escalation_amount"
                    "는 아직 발동하지 않음"
                ),
            )
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id,
                category=category,
                hint=hint,
                amount=200_000,
                total=BIG_TOTAL,
                spent=BIG_SPENT,
                note=(
                    f"{hint} — force_escalation_amount(200,000원)과 정확히 같음. 판정은 위와"
                    " 동일하게 escalate지만 over_force_escalation_amount가 추가로 발동"
                ),
            )

    # 축 3 — 예산 사용률 90% 경계 (5팀 × 3카테고리 × 2사이드 = 30). amount는 auto_approve_
    # limit 미만으로 고정해 금액 축과 완전히 분리한다.
    for team_type in TEAM_TYPES:
        org_id = reg.add_org(
            label=f"v2-boundary-usage-{team_type}",
            team_type=team_type,
            total_budget=USAGE_TOTAL,
            spent=44_900,
        )
        org_id_over = reg.add_org(
            label=f"v2-boundary-usage-over-{team_type}",
            team_type=team_type,
            total_budget=USAGE_TOTAL,
            spent=45_000,
        )
        for category, hint in AXIS3_CATS:
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id,
                category=category,
                hint=hint,
                amount=45_000,
                total=USAGE_TOTAL,
                spent=44_900,
                note=(
                    f"{hint} — 승인 시 예산 사용률 89.9%(90% 미만). budget_auditor 의견은"
                    " pass지만 verdict=='fail'만 게이트에 영향을 주므로 결과는 아래 90.0%"
                    " 케이스와 동일하게 approve — 사용률 경계는 게이트에 관측되지 않는다"
                ),
            )
            _emit(
                cases,
                reg,
                seq,
                team_type=team_type,
                org_id=org_id_over,
                category=category,
                hint=hint,
                amount=45_000,
                total=USAGE_TOTAL,
                spent=45_000,
                note=(
                    f"{hint} — 승인 시 예산 사용률 정확히 90.0%. budget_auditor 의견은 warn으로"
                    " 바뀌지만 guardrail_gate는 verdict=='fail'만 보므로(§4.5 밖) 최종 판정은"
                    " 위 89.9% 케이스와 동일하게 approve — '경계선이니 갈릴 것'이라는 직관과"
                    " 달리 게이트·최종 판정에는 무영향(이 유형의 핵심 발견)"
                ),
            )

    # --- 하드 케이스 10건 ---
    hard = reg.add_org(
        label="v2-boundary-hard-default",
        team_type="동아리/학생회",
        total_budget=DEFAULT_TOTAL,
        spent=DEFAULT_SPENT,
    )
    hard_noauto = reg.add_org(
        label="v2-boundary-hard-noauto",
        team_type="스터디",
        total_budget=DEFAULT_TOTAL,
        spent=DEFAULT_SPENT,
        auto_approve=False,
    )
    hard_tight_at_limit = reg.add_org(
        label="v2-boundary-hard-tight", team_type="친목", total_budget=50_000, spent=0
    )
    hard_zero_after = reg.add_org(
        label="v2-boundary-hard-zeroafter", team_type="동호회", total_budget=100_000, spent=0
    )
    hard_force_and_budget = reg.add_org(
        label="v2-boundary-hard-force-budget", team_type="회사", total_budget=100_000, spent=0
    )

    _emit(
        cases,
        reg,
        seq,
        team_type="동아리/학생회",
        org_id=hard,
        category="식비",
        hint="정기 회식",
        amount=50_001,
        total=DEFAULT_TOTAL,
        spent=DEFAULT_SPENT,
        note="한도보다 1원 더 많음 — escalate 쪽에서도 여유 있게 안쪽인지 확인",
        difficulty="hard",
    )
    _emit(
        cases,
        reg,
        seq,
        team_type="스터디",
        org_id=hard_noauto,
        category="교육",
        hint="온라인 강의 수강료",
        amount=10_000,
        total=DEFAULT_TOTAL,
        spent=DEFAULT_SPENT,
        note=(
            "auto_approve=False인 조직 — 금액은 한도 훨씬 아래(10,000원)라도 판정 권한 자체가"
            " 없어 escalate. 이 유형의 '금액 경계'와는 다른 축(auto_approve_disabled)이 함께"
            " 있음을 보여주는 하드 케이스"
        ),
        difficulty="hard",
        auto_approve=False,
    )
    _emit(
        cases,
        reg,
        seq,
        team_type="친목",
        org_id=hard_tight_at_limit,
        category="장소_대관",
        hint="스터디룸 대관료",
        amount=50_000,
        total=50_000,
        spent=0,
        note=(
            "청구액이 한도(50,000원)와 정확히 같고 잔액도 정확히 50,000원 — 예산은 충분하지만"
            " 금액 경계가 이겨 escalate(§4.5 우선순위표 밖: 예산이 '부족'하지 않으면 반려"
            " 우선순위 자체가 발동하지 않는다)"
        ),
        difficulty="hard",
    )
    _emit(
        cases,
        reg,
        seq,
        team_type="동호회",
        org_id=hard_zero_after,
        category="행사_활동",
        hint="동아리 엠티 참가비",
        amount=49_999,
        total=100_000,
        spent=50_001,
        note="승인 시 잔액이 정확히 0원(사용률 100%)이지만 금액이 한도 미만이라 approve",
        difficulty="hard",
    )
    _emit(
        cases,
        reg,
        seq,
        team_type="회사",
        org_id=hard_force_and_budget,
        category="IT_인프라",
        hint="노션 팀 구독료",
        amount=200_000,
        total=100_000,
        spent=0,
        note=(
            "force_escalation_amount 경계(200,000원)와 예산 부족(잔액 100,000원)이 동시에"
            " 걸리는 조합 — §4.5 우선순위상 반려가 이겨 이 boundary 케이스의 결과는 escalate가"
            " 아니라 reject가 된다(경계 유형 안에 우선순위 유형의 로직이 스며드는 예)"
        ),
        difficulty="hard",
    )

    # 나머지 5건 — 두 금액 경계를 한 조직에서 다시 확인(다른 카테고리 조합)
    for i, (category, hint) in enumerate(CATS[:5]):
        amount = 50_000 if i % 2 == 0 else 49_999
        _emit(
            cases,
            reg,
            seq,
            team_type="동아리/학생회",
            org_id=hard,
            category=category,
            hint=hint,
            amount=amount,
            total=DEFAULT_TOTAL,
            spent=DEFAULT_SPENT,
            note=f"{hint} — auto_approve_limit 경계 재확인({amount:,}원)",
            difficulty="medium",
        )

    return cases


__all__ = ["generate", "TYPE"]
