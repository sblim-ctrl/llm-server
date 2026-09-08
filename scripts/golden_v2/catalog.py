"""골든 v2 생성기 공용 상수 — 카테고리 힌트·팀 유형·정책 기본값.

templates/category_catalog.yaml(9종 키워드)과 app/tools/policy_params.py(PolicyParams
기본값)를 손으로 옮긴 것이 아니라 그대로 참조해야 하지만, 이 파일은 순수 문자열
상수만 다루므로 import 없이 값만 재현한다 — 값이 실제 카탈로그와 어긋나면
tests/test_mock_fixture.py의 카테고리 canonical 검사가 즉시 잡는다(§4.2 계약).
"""

TEAM_TYPES = ["동아리/학생회", "스터디", "친목", "동호회", "회사"]

# 카테고리별 "키워드가 확실히 그 카테고리 하나에만 걸리는" 제목 문구.
# templates/category_catalog.yaml의 순서(식비→교통→IT_인프라→교육→회의→장소_대관→
# 행사_활동→비품→기타)와 각 카테고리의 keywords 목록을 대조해 다른 카테고리 키워드와
# 겹치지 않는 문구만 골랐다 — classify_by_keywords()가 결정적으로 이 카테고리를
# 반환함을 보장한다(목 모드 분류 채점의 전제).
CATEGORY_TITLE_HINT: dict[str, str] = {
    "식비": "정기 회식",
    "교통": "출장 기차표",
    "IT_인프라": "노션 팀 구독료",
    "교육": "온라인 강의 수강료",
    "회의": "동아리 정기모임 회의비",
    "장소_대관": "스터디룸 대관료",
    "행사_활동": "동아리 엠티 참가비",
    "비품": "학회 단체 티셔츠 제작",
    "기타": "동아리 회원 경조사 조화",
}

# 목 모드 rule_auditor는 항상 no_rules(기본 정책) 경로를 타 verdict="pass"·평문 근거만
# 남기므로(scripts/golden_v2/engine.py 모듈독스트링 참조) expected_rule_clauses는
# run_eval 채점에 쓰이지 않는 문서용 필드다. 그래도 실모드(회칙 실인덱싱 후)에서
# app/tools/backend_client.py의 11개조 본문과 대조할 수 있도록, 카테고리별로 가장
# 가까운 조항 번호만 참고용으로 남긴다.
CATEGORY_RULE_CLAUSE_HINT: dict[str, str] = {
    "식비": "제2조",
    "교통": "제9조",
    "IT_인프라": "제5조",
    "교육": "제4조",
    "회의": "제6조",
    "장소_대관": "제6조",
    "행사_활동": "제7조",
    "비품": "제5조",
    "기타": "제3조",
}

# app/schemas/common.py PolicyParams 기본값과 eval/fixtures/mock_backend.json 기존
# 조직들이 실제로 쓰는 값 — v2도 동일 상수를 재사용해 v1과 조건을 맞춘다.
AUTO_APPROVE_LIMIT = 50_000
FORCE_ESCALATION_AMOUNT = 200_000

# 리뷰 목표 문구 — golden_v1.json 전 케이스가 공유하는 고정값 그대로.
REVIEW_GOAL = "회칙·예산·판례에 근거해 이 지출의 승인 여부를 심사하라"
