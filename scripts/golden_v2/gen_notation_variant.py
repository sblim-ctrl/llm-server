"""notation_variant 유형 — 같은 항목을 영문·외래어·오타·축약형으로 표기.

핵심은 판정(verdict)이 아니라 **분류(category) 축의 목/실 대조**다: app/tools/
category_catalog.py의 keyword_category_or_none()은 부분 문자열 매칭이라 카탈로그에
없는 표기(영문 브랜드명·외래어·오타)는 전부 놓치고 '기타'로 떨어진다. 반대로 실LLM
분류기는 문맥으로 의미를 읽어 맞힐 것으로 기대된다 — 그래서 이 유형은 목 모드
category_accuracy가 의도적으로 낮게 나와야 정상이고, 실모드에서 크게 올라가는 것이
성공 신호다. 사용자 원안 그대로 "분류 축은 목, 회칙 매칭 축은 실모드"라 mode_required는
mock으로 둔다 — 목 모드에서도 이 축의 결과(낮은 정확도)는 그 자체로 의미 있는 관측이다.
판정 자체는 금액·예산을 안전하게 잡아 항상 approve로 고정해 분류 축만 순수하게 관측한다.

20개 표기 변형 문구 × 5개 팀 유형 = 100건. 각 문구는 templates/category_catalog.yaml의
keywords 목록을 대조해 실제로 어떤 카테고리 키워드에도 걸리지 않음을 확인하고 골랐다
(기타 2건은 예외 — 이미 검증된 '카탈로그 밖' 기준 사례라 목/실 모두 기타로 일치해야 함).
"""

from scripts.golden_v2.case import build_case
from scripts.golden_v2.catalog import TEAM_TYPES
from scripts.golden_v2.engine import evaluate
from scripts.golden_v2.fixtures import FixtureRegistry

TYPE = "notation_variant"
DATE = "2026-07-15"
TOTAL, SPENT = 300_000, 118_000  # 잔액 182,000 — 항상 충분

# (실제 목표 카테고리, 표기 변형 제목, 왜 목 모드가 놓치는지)
VARIANTS = [
    ("식비", "Team Dinner", "영문 표기 — '회식/식사' 등 한글 키워드가 전혀 없음"),
    ("식비", "회싟비 정산", "오타 — '회식'이 '회싟'으로 깨져 키워드 미스매치"),
    ("식비", "다이닝 결제", "외래어 '다이닝' — 카탈로그 키워드는 '식사'만 인정"),
    ("교통", "우버 결제", "영문 브랜드명 — '택시' 키워드가 없음"),
    ("교통", "카풀 요금 정산", "'카풀' — 카탈로그 키워드 밖 교통수단 표현"),
    ("교통", "라이드 호출 요금", "외래어 '라이드·호출' — '택시/이동' 키워드와 겹치지 않음"),
    ("IT_인프라", "Notion 정기결제", "영문 브랜드명 — 카탈로그는 한글 '노션'만 인정"),
    ("IT_인프라", "슬렉 유료 플랜", "오타 — '슬랙'이 '슬렉'으로 깨짐"),
    ("교육", "MOOC 수료증 비용", "영문 축약형 — '강의/수강' 등 키워드 없음"),
    (
        "교육",
        "새미나 참여 비용",
        "오타 — '세미나'가 '새미나'로 깨짐(등록비 낱말은 행사_활동 키워드와 겹쳐 피함)",
    ),
    ("회의", "번개 회동", "구어체 '회동' — 카탈로그 키워드(회의실·정기모임 등) 밖"),
    ("회의", "모임 소집비", "'모임'만으로는 키워드 '정기모임'(4글자 전체) 미달"),
    (
        "장소_대관",
        "이벤트홀 대여",
        "'대여'는 2026-08-07 검증 후 의도적으로 제외된 낱말(카탈로그 주석). '행사장'을 쓰면"
        " '행사' 키워드가 행사_활동에 걸려 오분류가 나므로 '이벤트홀'로 회피",
    ),
    ("장소_대관", "베뉴 이용료", "외래어 '베뉴'(venue) — 한글 장소 키워드 없음"),
    ("행사_활동", "MT 참가", "로마자 표기 'MT' — 카탈로그는 한글 '엠티'만 인정"),
    ("행사_활동", "빙고게임 진행비", "'보드게임'과 다른 게임명이라 키워드 미스매치"),
    ("비품", "스테이셔너리 구매", "외래어 '스테이셔너리' + '구매'(카탈로그는 '구입'만 인정)"),
    ("비품", "웹캠 장만", "'장만'은 '장비'와 다른 낱말이라 미스매치"),
    (
        "기타",
        "동아리 회원 경조사 조화",
        "이미 검증된 카탈로그 밖 기준 사례 — 목/실 모두 기타로 일치해야 함",
    ),
    ("기타", "동호회 부의금", "선물/기념 계열 — legacy alias도 기타로 접는 항목, 목/실 모두 기타"),
]


def generate(reg: FixtureRegistry) -> list[dict]:
    cases: list[dict] = []
    org_by_type = {
        tt: reg.add_org(label=f"v2-notation-{i}", team_type=tt, total_budget=TOTAL, spent=SPENT)
        for i, tt in enumerate(TEAM_TYPES)
    }

    seq = 0
    for category, title, why in VARIANTS:
        for ti, team_type in enumerate(TEAM_TYPES):
            seq += 1
            case_id = f"v2-notation_variant-{seq:03d}"
            amount = 12_000 + ti * 1_500
            org_id = org_by_type[team_type]
            # description은 반드시 중립적이어야 한다 — classify_category가 title+description을
            # 함께 본다(user_text). "왜 목 모드가 놓치는지" 설명(why)에 정답 키워드가 섞여
            # 있으면(예: "'회식/식사' 등 한글 키워드가 없음") 그 설명 자체가 분류기 입력으로
            # 새어 들어가 이 유형의 취지(놓쳐야 할 표기가 실제로 놓치는지 관측)를 무너뜨린다
            # — why는 scenario(그래프에 전달되지 않는 골든셋 메타데이터)에만 남긴다.
            expense_id = reg.add_expense(
                title=title,
                amount=amount,
                date=DATE,
                description=f"{team_type} 지출 — {title}",
            )
            outcome = evaluate(
                amount=amount,
                auto_approve=True,
                auto_approve_limit=50_000,
                force_escalation_amount=200_000,
                budget_total=TOTAL,
                budget_spent=SPENT,
                receipt_state="match",
            )
            assert outcome.verdict == "approve", (case_id, outcome)
            cases.append(
                build_case(
                    case_id=case_id,
                    scenario=f"표기 변형 — '{title}'({why}) → 실제 정답 카테고리는 {category}",
                    team_type=team_type,
                    case_type=TYPE,
                    difficulty="medium",
                    mode_required="mock",
                    organization_id=org_id,
                    expense_id=expense_id,
                    receipt_path=f"mock://receipt?amount={amount}&date={DATE}",
                    expected_verdict=outcome.verdict,
                    expected_category=category,
                    expected_gate_includes=outcome.gate_includes,
                )
            )

    return cases


__all__ = ["generate", "TYPE"]
