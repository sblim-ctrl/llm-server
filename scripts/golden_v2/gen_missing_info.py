"""missing_info 유형 — 정보/판정 권한 부족 → escalate.

Phase 0 조사에서 v1 97건 중 unclassified 20건의 절반(8건)이 "auto_approve_disabled
단독" 축이었다(영수증 문제도 아니고 정보 부족도 아니라 조직 정책 자체가 자동판정을
막는 경우). 사용자 원안 7유형에는 이 축을 위한 자리가 따로 없어, "정보/권한이 부족해
escalate로 수렴한다"는 공통점으로 missing_info에 접었다(2026-09-08 판단, 원인은 다르지만
결과 구조 — escalate로 수렴 — 가 같다).

그리드: (A) 영수증 미첨부 45건(5팀×9카테고리) + (B) auto_approve_disabled 45건 +
하드 케이스 9건 = 99건.

정직한 참고: "설명 없음"은 이 코드베이스에 게이트 트리거가 아니다 — description이
비어 있어도 guardrail_gate는 아무 반응이 없다(receipt_unreadable·auto_approve_disabled만
본다). 하드 케이스에서 description=""로 재현하되, escalate의 실제 근거는 항상 위 두 축
중 하나임을 시나리오 문구에 정직하게 남긴다.
"""

from scripts.golden_v2.case import build_case
from scripts.golden_v2.catalog import CATEGORY_TITLE_HINT, TEAM_TYPES
from scripts.golden_v2.engine import evaluate
from scripts.golden_v2.fixtures import FixtureRegistry

TYPE = "missing_info"
DATE = "2026-07-13"
AMOUNT = 10_000
TOTAL, SPENT = 300_000, 118_000  # 잔액 182,000 — 예산은 항상 충분, 순수하게 정보축만 본다


def generate(reg: FixtureRegistry) -> list[dict]:
    cases: list[dict] = []
    seq = 0

    noreceipt_org = {
        tt: reg.add_org(
            label=f"v2-missing-noreceipt-{i}", team_type=tt, total_budget=TOTAL, spent=SPENT
        )
        for i, tt in enumerate(TEAM_TYPES)
    }
    noauto_org = {
        tt: reg.add_org(
            label=f"v2-missing-noauto-{i}",
            team_type=tt,
            total_budget=TOTAL,
            spent=SPENT,
            auto_approve=False,
        )
        for i, tt in enumerate(TEAM_TYPES)
    }

    # Group A — 영수증 미첨부
    for team_type in TEAM_TYPES:
        org_id = noreceipt_org[team_type]
        for category, hint in CATEGORY_TITLE_HINT.items():
            seq += 1
            case_id = f"v2-missing_info-{seq:03d}"
            expense_id = reg.add_expense(
                title=hint,
                amount=AMOUNT,
                date=DATE,
                description=f"{team_type} — {hint}, 영수증 미첨부",
            )
            outcome = evaluate(
                amount=AMOUNT,
                auto_approve=True,
                auto_approve_limit=50_000,
                force_escalation_amount=200_000,
                budget_total=TOTAL,
                budget_spent=SPENT,
                receipt_state="missing",
            )
            assert outcome.verdict == "escalate", (case_id, outcome)
            cases.append(
                build_case(
                    case_id=case_id,
                    scenario=f"정보 부족 — 영수증 미첨부 ({hint})",
                    team_type=team_type,
                    case_type=TYPE,
                    difficulty="easy",
                    mode_required="mock",
                    organization_id=org_id,
                    expense_id=expense_id,
                    receipt_path=None,
                    expected_verdict=outcome.verdict,
                    expected_category=category,
                    expected_gate_includes=outcome.gate_includes,
                )
            )

    # Group B — 조직 정책상 자동판정 권한 없음(auto_approve=False)
    for team_type in TEAM_TYPES:
        org_id = noauto_org[team_type]
        for category, hint in CATEGORY_TITLE_HINT.items():
            seq += 1
            case_id = f"v2-missing_info-{seq:03d}"
            expense_id = reg.add_expense(
                title=hint,
                amount=AMOUNT,
                date=DATE,
                description=f"{team_type} — {hint}, 조직이 AI 자동판정을 꺼둠",
            )
            outcome = evaluate(
                amount=AMOUNT,
                auto_approve=False,
                auto_approve_limit=50_000,
                force_escalation_amount=200_000,
                budget_total=TOTAL,
                budget_spent=SPENT,
                receipt_state="match",
            )
            assert outcome.verdict == "escalate", (case_id, outcome)
            cases.append(
                build_case(
                    case_id=case_id,
                    scenario=(
                        f"정보 부족(판정 권한 없음) — 조직 auto_approve=False, 금액·예산·영수증"
                        f" 전부 정상({hint})"
                    ),
                    team_type=team_type,
                    case_type=TYPE,
                    difficulty="easy",
                    mode_required="mock",
                    organization_id=org_id,
                    expense_id=expense_id,
                    receipt_path=f"mock://receipt?amount={AMOUNT}&date={DATE}",
                    expected_verdict=outcome.verdict,
                    expected_category=category,
                    expected_gate_includes=outcome.gate_includes,
                )
            )

    # --- 하드 케이스 9건 ---
    hard_org_a = reg.add_org(
        label="v2-missing-hard-both",
        team_type="동아리/학생회",
        total_budget=TOTAL,
        spent=SPENT,
        auto_approve=False,
    )
    hard_org_b = reg.add_org(
        label="v2-missing-hard-budgetfail-noauto",
        team_type="스터디",
        total_budget=20_000,
        spent=19_000,
        auto_approve=False,
    )
    hard_org_c = reg.add_org(
        label="v2-missing-hard-nodesc", team_type="친목", total_budget=TOTAL, spent=SPENT
    )
    hard_org_d = reg.add_org(
        label="v2-missing-hard-boundary-noauto",
        team_type="동호회",
        total_budget=TOTAL,
        spent=SPENT,
        auto_approve=False,
    )

    seq += 1
    exp = reg.add_expense(
        title="동아리 엠티 참가비",
        amount=AMOUNT,
        date=DATE,
        description="영수증도 없고 조직도 auto_approve=False",
    )
    outcome = evaluate(
        amount=AMOUNT,
        auto_approve=False,
        auto_approve_limit=50_000,
        force_escalation_amount=200_000,
        budget_total=TOTAL,
        budget_spent=SPENT,
        receipt_state="missing",
    )
    assert outcome.gate_includes == ["auto_approve_disabled", "receipt_unreadable"], outcome
    cases.append(
        build_case(
            case_id=f"v2-missing_info-{seq:03d}",
            scenario="정보 부족(하드) — 영수증 미첨부 + 판정 권한 없음이 동시에 걸림(두 트리거 모두 관측)",
            team_type="동아리/학생회",
            case_type=TYPE,
            difficulty="hard",
            mode_required="mock",
            organization_id=hard_org_a,
            expense_id=exp,
            receipt_path=None,
            expected_verdict=outcome.verdict,
            expected_category="행사_활동",
            expected_gate_includes=outcome.gate_includes,
        )
    )

    seq += 1
    exp = reg.add_expense(
        title="정기 회식",
        amount=4_000,
        date=DATE,
        description="예산도 부족하고(잔액 1,000원) 조직도 auto_approve=False —"
        " 반려가 아니라 escalate가 이긴다(auto_approve_disabled는"
        " _BUDGET_OVERRIDES 밖이라 §4.5 반려 우선순위에 들지 못함)",
    )
    outcome = evaluate(
        amount=4_000,
        auto_approve=False,
        auto_approve_limit=50_000,
        force_escalation_amount=200_000,
        budget_total=20_000,
        budget_spent=19_000,
        receipt_state="match",
    )
    assert outcome.verdict == "escalate", outcome
    cases.append(
        build_case(
            case_id=f"v2-missing_info-{seq:03d}",
            scenario=(
                "정보 부족(하드) — 예산 부족(잔액 1,000원 < 청구 4,000원)과 auto_approve=False가"
                " 동시에 걸려도 reject가 아니라 escalate로 수렴(§4.5 우선순위의 화이트리스트 밖)"
            ),
            team_type="스터디",
            case_type=TYPE,
            difficulty="hard",
            mode_required="mock",
            organization_id=hard_org_b,
            expense_id=exp,
            receipt_path=f"mock://receipt?amount=4000&date={DATE}",
            expected_verdict=outcome.verdict,
            expected_category="식비",
            expected_gate_includes=outcome.gate_includes,
        )
    )

    for i, (category, hint) in enumerate(list(CATEGORY_TITLE_HINT.items())[:4]):
        seq += 1
        exp = reg.add_expense(
            title=hint,
            amount=AMOUNT,
            date=DATE,
            description="",  # 설명 없음 — 그러나 이 자체는 게이트를 건드리지 않는다(위 모듈독스트링)
        )
        outcome = evaluate(
            amount=AMOUNT,
            auto_approve=True,
            auto_approve_limit=50_000,
            force_escalation_amount=200_000,
            budget_total=TOTAL,
            budget_spent=SPENT,
            receipt_state="missing",
        )
        assert outcome.verdict == "escalate", outcome
        cases.append(
            build_case(
                case_id=f"v2-missing_info-{seq:03d}",
                scenario=(
                    f'정보 부족(하드) — {hint}, 설명란이 비어 있음(description=""). 다만 실제'
                    " escalate 근거는 설명 공란이 아니라 영수증 미첨부(receipt_unreadable)다 —"
                    " 이 코드베이스에서 '설명 없음' 자체는 게이트 트리거가 아니다"
                ),
                team_type="친목",
                case_type=TYPE,
                difficulty="hard",
                mode_required="mock",
                organization_id=hard_org_c,
                expense_id=exp,
                receipt_path=None,
                expected_verdict=outcome.verdict,
                expected_category=category,
                expected_gate_includes=outcome.gate_includes,
            )
        )

    for amount in (49_999, 50_000, 200_000):
        seq += 1
        exp = reg.add_expense(
            title="출장 기차표",
            amount=amount,
            date=DATE,
            description=f"auto_approve=False 조직에서 금액 경계({amount:,}원)를 함께 올려도"
            " 결과는 여전히 escalate 하나뿐 — 게이트 목록만 늘어난다",
        )
        outcome = evaluate(
            amount=amount,
            auto_approve=False,
            auto_approve_limit=50_000,
            force_escalation_amount=200_000,
            budget_total=TOTAL,
            budget_spent=SPENT,
            receipt_state="match",
        )
        assert outcome.verdict == "escalate", outcome
        cases.append(
            build_case(
                case_id=f"v2-missing_info-{seq:03d}",
                scenario=f"정보 부족(하드) — 판정 권한 없음 + 금액 {amount:,}원(경계 재확인)",
                team_type="동호회",
                case_type=TYPE,
                difficulty="hard",
                mode_required="mock",
                organization_id=hard_org_d,
                expense_id=exp,
                receipt_path=f"mock://receipt?amount={amount}&date={DATE}",
                expected_verdict=outcome.verdict,
                expected_category="교통",
                expected_gate_includes=outcome.gate_includes,
            )
        )

    return cases


__all__ = ["generate", "TYPE"]
