"""circumvention 유형 — 한도 회피용 분할 결제·동일 건 재청구. 실모드 전용(판례 유사검색 축).

이 코드베이스를 직접 정독해 확인한 사실: 분할 결제와 동일 건 재청구는 서로 다른 별도
탐지 로직이 있는 게 아니라, **둘 다 precedent_auditor의 판례 유사도 검색 하나로
뭉뚱그려 처리된다**(app/graphs/review/nodes/precedent_auditor.py _mock_opinion). 관리자가
과거에 "분할 결제 의심" 또는 "중복 청구 의심"으로 반려한 판례가 있고, 이번 청구가
그 판례와 충분히 유사(실모드 임베딩 distance<0.35)하며 결정주체가 ADMIN이고 decision이
reject/override일 때만 precedent_suspicion이 발동한다. 목 모드는 해시 임베딩이라 의미
유사도가 없고, 이 유형의 판례는 실모드 러너가 case["seed_precedents"]를 통해 실행 직전에
_seed_briefing_precedents 패턴으로 DB에 심어야 의미가 생긴다(§4.5와 무관한 축).

expected_verdict는 "판례 유사도가 실제로 감지된다면" 나와야 할 정답(escalate)을 사람이
판단해 적었다 — 목 모드는 판례를 심지 않으므로 이 정답에 못 미치는 것이 예상된 결과다.

10개 재청구 시나리오 + 10개 분할 결제 시나리오 × 5개 팀 유형 = 100건.
"""

from scripts.golden_v2.case import build_case
from scripts.golden_v2.engine import evaluate
from scripts.golden_v2.fixtures import FixtureRegistry

TYPE = "circumvention"
DATE = "2026-07-17"
TOTAL, SPENT = 300_000, 118_000  # 잔액 182,000 — 예산은 항상 충분, 순수하게 판례 축만 본다
TEAM_TYPES_5 = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]

# (category, title, amount, seed_reason) — 재청구(동일 건을 다시 냄)
RESUBMIT_SPECS = [
    ("식비", "정기 회식", 28_000, "이미 승인된 동일 지출을 다시 청구 — 중복 청구 의심으로 반려"),
    (
        "비품",
        "학회 단체 티셔츠 제작",
        45_000,
        "지난달과 동일한 티셔츠 제작 건 재청구 — 중복 의심 반려",
    ),
    ("교통", "출장 기차표", 32_000, "동일 출장 기차표를 두 번째로 청구 — 중복 청구 반려"),
    ("IT_인프라", "노션 팀 구독료", 33_000, "이미 정산된 구독료를 다시 청구 — 중복 청구 반려"),
    ("교육", "온라인 강의 수강료", 40_000, "환불받은 강의를 재청구 — 이중 수령 의심 반려"),
    ("장소_대관", "스터디룸 대관료", 25_000, "동일 대관 건을 날짜만 바꿔 재청구 — 중복 의심 반려"),
    ("행사_활동", "동아리 엠티 참가비", 48_000, "이미 정산된 엠티 참가비를 다시 청구 — 중복 반려"),
    ("회의", "동아리 정기모임 회의비", 20_000, "동일 회의비를 두 번째로 청구 — 중복 청구 반려"),
    ("기타", "동아리 회원 경조사 조화", 30_000, "이미 지급된 경조사비를 재청구 — 중복 반려"),
    ("식비", "정기 회식", 15_000, "영수증 사본으로 같은 건을 재청구 — 중복 청구 반려"),
]

# (category, title, amount, seed_reason) — 분할 결제(한도 회피 목적으로 쪼갬)
SPLIT_SPECS = [
    (
        "비품",
        "학회 단체 티셔츠 제작(2차분)",
        22_000,
        "70,000원 단일 구매를 한도 회피 목적으로 3건으로 쪼갠 것으로 의심되어 반려",
    ),
    (
        "행사_활동",
        "동아리 엠티 참가비(추가분)",
        24_000,
        "대형 엠티 비용을 여러 건으로 분할 청구한 것으로 의심되어 반려",
    ),
    (
        "장소_대관",
        "스터디룸 대관료(2회차)",
        21_000,
        "장기 대관을 회차별로 쪼개 한도를 피한 것으로 의심되어 반려",
    ),
    ("식비", "정기 회식(2차)", 18_000, "동일 회식을 1차·2차로 나눠 청구한 것으로 의심되어 반려"),
    (
        "IT_인프라",
        "노션 팀 구독료(분기 추가분)",
        15_000,
        "연간 구독료를 분기별로 쪼개 한도 아래로 맞춘 것으로 의심되어 반려",
    ),
    (
        "비품",
        "웹캠 장비 구매(추가)",
        19_000,
        "한 번에 살 장비를 여러 건으로 나눈 것으로 의심되어 반려",
    ),
    (
        "교육",
        "온라인 강의 수강료(2강)",
        23_000,
        "패키지 강의를 강별로 쪼개 청구한 것으로 의심되어 반려",
    ),
    (
        "교통",
        "출장 기차표(왕복 2건)",
        17_000,
        "왕복 교통비를 편도씩 나눠 청구한 것으로 의심되어 반려",
    ),
    (
        "회의",
        "동아리 정기모임 회의비(추가)",
        12_000,
        "한 회의 비용을 두 건으로 나눠 한도를 피한 것으로 의심되어 반려",
    ),
    (
        "기타",
        "동아리 회원 경조사 조화(추가)",
        14_000,
        "한 건의 경조사비를 나눠 청구한 것으로 의심되어 반려",
    ),
]


def _seed_for(category: str, title: str, amount: int, reason: str) -> list[dict]:
    return [
        {
            "category": category,
            "title": title,
            "amount": amount,
            "decision": "reject",
            "decided_by": "ADMIN",
            "reason": reason,
            "is_override": False,
            "date": "2026-06-20",
        }
    ]


def _build_group(
    reg: FixtureRegistry,
    specs: list[tuple],
    label_prefix: str,
    scenario_prefix: str,
    seq_start: int,
) -> list[dict]:
    cases: list[dict] = []
    seq = seq_start
    for category, title, amount, reason in specs:
        for team_type in TEAM_TYPES_5:
            seq += 1
            case_id = f"v2-circumvention-{seq:03d}"
            org_id = reg.add_org(
                label=f"v2-{label_prefix}-{seq:03d}",
                team_type=team_type,
                total_budget=TOTAL,
                spent=SPENT,
            )
            expense_id = reg.add_expense(
                title=title,
                amount=amount,
                date=DATE,
                description=f"{team_type} — {title}, {amount:,}원. {reason}",
            )
            mock_outcome = evaluate(
                amount=amount,
                auto_approve=True,
                auto_approve_limit=50_000,
                force_escalation_amount=200_000,
                budget_total=TOTAL,
                budget_spent=SPENT,
                receipt_state="match",
            )
            case = build_case(
                case_id=case_id,
                scenario=f"{scenario_prefix} — {title} {amount:,}원. {reason}",
                team_type=team_type,
                case_type=TYPE,
                difficulty="hard",
                mode_required="real",
                organization_id=org_id,
                expense_id=expense_id,
                receipt_path=f"mock://receipt?amount={amount}&date={DATE}",
                expected_verdict="escalate",
                expected_category=category,
                expected_gate_includes=["precedent_suspicion"],
            )
            # seed_precedents는 run_eval_v2_real.py 전용 필드 — mock 러너는 읽지 않는다.
            # 목 모드는 이 판례를 심지 않으므로 실제로는 mock_outcome(대개 approve)이 나온다 —
            # 그 괴리 자체가 이 유형의 목/실 대조 핵심이다(모듈독스트링 참고).
            case["seed_precedents"] = _seed_for(category, title, amount, reason)
            case["mock_mode_note"] = (
                f"목 모드는 판례를 심지 않아 실제로는 approve(가드레일 없음)가 나올 것으로 예상됨 —"
                f" 참고용 기계적 결과: {mock_outcome.verdict}"
            )
            cases.append(case)
    return cases


def generate(reg: FixtureRegistry) -> list[dict]:
    cases = _build_group(reg, RESUBMIT_SPECS, "circumvent-resubmit", "동일 건 재청구", 0)
    cases += _build_group(reg, SPLIT_SPECS, "circumvent-split", "분할 결제 의심", len(cases))
    return cases


__all__ = ["generate", "TYPE"]
