"""프롬프트 YAML 로더 (스프린트1 C3 계약) — `prompts/{agent}/{version}.yaml`.

버전의 진실 원천은 YAML 내부 `version:` 필드다 (파일명 아님) — 판정 기록·판례에
남는 prompt_version은 항상 `load_prompt(...).version`을 쓴다. YAML 형식은
version / system / output_schema(문서용 주석) / few_shot 4키로 고정
(기존 prompts/rule_auditor/v1.yaml 기준). 신규 에이전트 프롬프트도 동일 형식.
"""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_ENV_PREFIX = "PROMPT_VERSION_"  # A/B 실험용 오버라이드: PROMPT_VERSION_ADJUDICATOR=v2

# 에이전트별 기본 버전 — 실측 A/B로 우세가 재현된 버전만 승격한다 (미등재=v1).
# 승격 근거(2026-07-20 실모드 골든셋 6회전, 오승인 전 회차 0 — 상세 PROGRESS §6-1):
# rule_auditor v1 80.0% → v2 93.3%·90.0%(재현) → v3+temp0 100.0% (연 한도 편차 해소)
# adjudicator v1 80.0% → v2 93.3%~ (잔액 부족 확신 반려)
# briefing_writer v1 3/5(bf-override·bf-gap 실패) → v2 5/5, verified 불통과 0건
#   (실키 writers golden, gap_categories 처리·0건 생략 금지 few_shot 보강 효과)
# report_writer v1 4/4 → v2 4/4 유지(실키 writers golden, 회귀 없음 확인 후 승격)
#
# 2026-07-24 골든셋 receiptPath를 실제 로컬 이미지(file://)로 교체 후 재측정.
# 주의: compare_prompts.py는 A(베이스라인)를 먼저 실행해 판례를 쌓고 그 위에서
# B(오버라이드)를 평가하는 구조라, 초기 측정에서 adjudicator/rule_auditor/
# classifier 전부 동일한 3개 adversarial 케이스(hobby-adversarial-001·
# social-adversarial-001·study-adversarial-002)가 "회귀"로 보였다 — 오버라이드
# 없이 판례만 안 지우고 재실행해도 동일하게 재현되어(57/60·95.0%), 프롬프트
# 문제가 아니라 A→B 판례 오염 아티팩트임을 확정했다. 이후 전부 골든-* 팀 판례
# 리셋 + 단독 실행(compare 없이 PROMPT_VERSION_*만 지정)으로 재검증:
# adjudicator v2 100.0%(2회) vs v3 100.0%(2회) — 동률이나 v3는
#   build_adjudication_user(근거 조항·수치·판례 확장 입력)와 few_shot 형식이
#   정합하는 필수 수정이라 승격.
# intake v1 100.0%(수 회) vs v2 100.0%(2회) — 동률, items 포맷 고정 등 부가
#   개선이라 회귀 없음 확인 후 승격.
# classifier: 골든셋 60건 전부 category가 이미 지정돼 있어 classify_category가
#   즉시 반환 — LLM classifier 자체가 호출되지 않음(A/B 무효). category 없는
#   대표 케이스 직접 호출 스모크(5유형+fallback 1건)로 재검증: v1 6/6 = v2 6/6
#   동률이나, v1 few_shot이 실제 카탈로그와 다른 가짜 후보 라벨을 쓰던 결함을
#   v2가 수정했으므로 승격.
# rule_auditor v3 100.0%(2회) vs v4 100.0%(2회) — 완전 동률, v4는 조항 번호
#   인용이라는 순수 부가 개선이라 기존 방침("동률이면 v3 유지") 그대로 미승격.
# precedent_auditor v2: 판례 리셋한 클린 상태에서도 100.0%→61.7% 붕괴(23건,
#   대부분 승인 기대 건이 보류로) — 판례 오염과 무관한 진짜 결함. "중복·분할
#   청구 검사는 결정주체 무관"이라는 v2 규칙이 AGENT의 정상 반복 승인(매달
#   반복되는 도서 구입 등)을 중복/분할 청구로 오탐.
# precedent_auditor v3(2026-07-24): fail·warn② 적용 전 "동일 사안 식별"
#   기준(정기성 표현·카테고리면 판례가 여러 건이어도 별개 회차로 간주,
#   title·description 내용이 같은 사건을 가리킬 때만 재청구로 판정)을 추가해
#   v2 회귀 수정. 클린 리셋 후 v1 100.0%(1회) vs v3 100.0%(2회, TPM 429는
#   내부 재시도로 흡수) — v2가 깨뜨렸던 정기 반복 지출 케이스
#   (club-approve-003/004 등) 전부 재통과, v1 대비 오탐 없이 동률 유지하며
#   의도한 중복 탐지 규칙까지 갖춰 승격.
# ── 브랜치 통합 (2026-08-04) ─────────────────────────────────────────────
# cowbro·sblim이 갈라져 있던 것을 팀장 결정에 따라 합쳤다
# (docs/internal/프롬프트_브랜치_통합계획_2026-08-04.md §9).
# adjudicator v4  — sblim v3(확장 입력 대응) 기반에 cowbro v3의 두 문장(요청자용
#   수치 금지 명시·관리자용 결정적 수치 인용 강제)을 이식. 같은 파일명에 다른 내용이던
#   양쪽 v3는 지우지 않고 남겼다.
# digest_writer·policy_drafter — sblim이 고친 방식을 채택(팀장 결정 4). cowbro의
#   digest_writer v2 few_shot 예시 2는 verify_digest_pure를 통과하지 못했다.
# classifier v5 — 카테고리가 전역 9종으로 확정되면서 sblim v2(유형별 6종 전제)는
#   더 이상 성립하지 않는다. 파일은 남기되 기본은 v5.
# judge — cowbro 전용 하네스를 그대로 가져왔다(팀장 결정 3). 사유 품질은 판정
#   정확도로 안 잡혀서 이 도구가 있어야 볼 수 있다.
DEFAULT_VERSIONS = {
    "rule_auditor": "v7",  # v7도 A/B 승격이 아니라 **입력 계약 변경**이다 (2026-08-12):
    #  코드가 user 메시지에 "증빙에서 읽은 사실"(상호·품목)을 넣게 됐다.
    #  종전에는 이 심사관만 claim(제목·설명)만 받아, 청구자가 쓴 제목에
    #  판정이 휘둘렸다 — 제목 "보드게임"·품목 "2시간 이용권 x6"인 시설
    #  이용료를 '보드게임 구입'으로 읽고 개인 물품 조항 위반 판정한 실사용
    #  사례가 있었다. 같은 영수증을 분류기·증빙 심사관은 제대로 읽고 있었다.
    #  few_shot input 5건에 증빙 블록을 넣어 런타임 형식과 맞췄고(형식
    #  불일치는 조용한 품질 저하로 나온다), 제목이 오인을 부르는 예시 1건을
    #  추가했다. 업종 예외를 넣지 않는다 — 다음 사례에서 또 뚫린다.
    #
    #  v6는 A/B 승격이 아니라 **정책 수정**이었다 (2026-08-11):
    #  "관련 조항 없음"을 warn → pass로. v5의 warn은 guardrail의
    #  rule_ambiguous → 에스컬레이션이라, 회칙에 안 적힌 지출이 전부
    #  관리자 대기열로 갔다(배포 데모에서 장소 대관비가 그렇게 보류됨).
    #  회칙은 모든 지출 유형을 열거하지 않으므로 조항 부재가 정상인
    #  항목이 더 많다 — 금지하지 않는 것은 회칙상 허용이 맞다.
    #  Self-RAG(근거 없이 지어내지 않는다)는 불변, 결론만 정정했다.
    #  warn은 '조항이 있는데 해석이 갈리는 경우'로 좁혔다. 코드 쪽
    #  짝은 rule_auditor.py의 grade=="insufficient" 분기(같은 날 동일 정책).
    #  few_shot은 기존 4건 바이트 동일 + 조항 부재 예시 1건 추가
    #  ("규칙보다 예시가 세다" — 규칙만 바꾸면 예시가 이긴다).
    #  ── 아래는 v5 이력 ──
    #  v5는 A/B 승격이 아니라 **정합 수정**이다 (PR-5, 2026-08-08):
    #  카탈로그 밖 라벨 "다과"·"도서"를 few_shot에서 "식비"·"교육"으로
    #  정정. v3 기반(v4 아님 — v4의 ① 조항 번호 인용은 동률이라 미승격
    #  이었던 팀장 결정 5를 그대로 유지). 판정 기준·나머지 예시는 v3
    #  그대로, 실측 재검증은 eval/run_eval 게이트로 확인했다.
    "adjudicator": "v6",  # v5(유사 판례 인용 카탈로그 라벨 정합) + 정합 수정
    #  (2026-08-11): reason_admin few_shot 예시3·4가 판례 인용 시스템 표기
    #  "(approve/ADMIN)"을 사유 문장에 그대로 베끼고 있었다 — 관리자를
    #  "admin"이라 지칭하는 등 비직관 용어 노출 결함. system에 시스템 표기
    #  (ADMIN/AGENT/override/confidence 수치)를 사유에 옮기지 말라는 규칙을
    #  추가하고 두 예시를 한국어 내용만 남게 교정했다. 자세한 실측·근거는
    #  prompts/adjudicator/v6.yaml 헤더 참고.
    "briefing_writer": "v4",  # v3(gap_categories 카탈로그 라벨 정합) + 정합 수정
    #  (2026-08-11): system·few_shot이 "override {override_count}건"을
    #  영문 그대로 쓰도록 강제하고 있었다 — "AI 추천 번복"으로 정정.
    #  app/graphs/writers/briefing.py의 코드 고정 문구(_mock_briefing_text·
    #  _handover_notes)도 함께 정리(eval/golden/writers_golden_v1.json의
    #  notes_contain 기대값도 동반 갱신 필요).
    "report_writer": "v4",  # v3 + 정합 수정(2026-08-10, A 리뷰): 예시1의 by_category에
    #  #37 라벨 치환 부작용으로 식비가 두 행으로 갈라져 있었다(집계 함수가
    #  만들 수 없는 형태) — 293,000원 한 행으로 병합.
    "intake": "v3",  # parse_ok의 의미를 못박음 — 브랜치 통합 후 실모드 스모크에서
    #  6건 중 5건이 receipt_unreadable로 나와 잡았다. v2가 상호·
    #  품목 없는 추출 텍스트를 parse_ok=false로 봤고, 그게
    #  guardrail의 receipt_unreadable → 전건 관리자 확인이 된다.
    #  백엔드 추출 텍스트에는 상호·품목이 없는 경우가 흔해서
    #  운영 자동 처리율을 통째로 죽이는 결함이었다.
    "precedent_auditor": "v5",  # v4(카탈로그 라벨 정합) + 정합 수정(2026-08-11):
    #  화면 심사관 카드 summary에 톤·용어 지침이 없던 공백을 메웠다 — system에
    #  "summary는 한국어로만, ADMIN/AGENT/override는 관리자·AI 자동·AI 추천
    #  번복으로 풀어 쓴다"는 규칙을 추가(few_shot은 이미 한국어라 교정 불요).
    #  similar_cases의 "입력 표기 그대로" 규칙은 유지 — 화면 노출 문구는
    #  출구 경계(callback.py translate_precedent_citation — 콜백·폴링 공용)에서 옮긴다.
    "digest_writer": "v3",  # sblim v2 + advice 계약 복구 (PR #9 리뷰 D2). v2는 코드가
    #  필수로 요구하는 advice를 system·few_shot 어디에서도 언급하지
    #  않아, 목 모드에서만 _mock_advice로 가려지고 실모드에서
    #  verify_digest_pure에 걸려 전건 폐기될 상태였다.
    #  few_shot input도 런타임 compact 직렬화에 맞췄다.
    "policy_drafter": "v6",  # v6(2026-08-11 밤): 한도를 숫자로 인용. v5는 금액 신설만
    #  막았더니 "회칙이 정한 한도 범위에서"로 뭉뚱그렸다 — 실제
    #  한도를 알 수 없는 문구다. user 메시지에 한도 표를 주고
    #  그 값만 인용하게 했다(표 밖 금액은 조립부가 걸러낸다).
    #  ── 아래는 v5 이력 ──
    #  모호 표현 금지·허용 조항 한도 필수·
    #  지출 분류를 시스템 식별자(장소_대관)가 아니라 회칙 표현
    #  (장소 대관비)으로. v4 출력에 "소액 선물"·"고가 메뉴" 같은
    #  AI가 판단할 수 없는 말이 남아 있었다.
    #  ── 아래는 v4 이력 ──
    #  v4는 형식 개편이다: 출력이 list[str] →
    #  list[{title,text}]로 바뀌어 조립부가 "제N조(제목) 본문"으로
    #  렌더링한다. 항(①②③)도 허용해 조건·예외를 담을 수 있다.
    #  종전에는 번호 없는 단문이 기본 조항 뒤에 붙어 회칙이 아니라
    #  메모처럼 보였다("너무 짧고 당연한 이야기뿐" — 배포 데모 지적).
    #  상한 7 → 10, 입력에 예산·인원·기본 조항 목록 추가.
    #  금액을 새로 만들지 않는 규칙은 유지 — 회비·승인 기준·카테고리
    #  한도는 코드가 예산·인원에서 결정론적으로 계산해 기본 조항에
    #  이미 넣는다(verify_draft_pure가 그 밖의 금액을 막는다).
    #  ── 아래는 v3 이력 ──
    #  sblim v2 + cowbro v2의 분량·문체 지침 이식 (PR #9 리뷰 D6).
    #  상한을 코드 MAX_EXTRA_RULES와 일치시켰다 — v2는 프롬프트가
    #  "최대 3개"라 실효 상한이 3이었다. few_shot 출력 건수도 함께
    #  늘렸다(규칙보다 예시가 세다 — 지침만 얹으면 예시가 이긴다).
    "dashboard_writer": "v4",  # v4 = v2 + 인젝션 방어 한 줄 (2026-08-07 팀장 제안 —
    #  largest_expense_title이 사용자 작성 텍스트라 표면이 있다).
    #  A/B 승격이 아니라 **안전 정합 수정**(classifier v6 전례):
    #  v2의 과장 차단 실측 근거는 few_shot·규칙 불변이라 유지된다.
    # ⚠️ v3는 여전히 **의도적으로 승격하지 않았다.**
    #  v3 = v2 + few_shot input을 런타임 compact 직렬화에 정합화
    #  (digest_writer D2 ②와 같은 결함이 여기에도 있다). 다만 v2의
    #  과장 차단은 여러 줄 입력 상태에서 2회 재현으로 승격한 것이라,
    #  형식을 바꾸면 그 실측 근거가 그대로 적용되지 않는다.
    #  "실측으로 재현된 개선만 승격" 규율에 따라 재측정 라운드에서
    #  비교한 뒤 정한다 — 그때는 v3에도 같은 방어 문구를 얹어(=v5)
    #  v4와 비교하면 된다. 같은 형식 불일치가
    #  briefing_writer·report_writer·judge에도 남아 있다(전부 기본값).
    # ── 아래는 v2 이력 ──
    #  수치 과장 표현 차단 — 실모드 승격(2026-08-04, 2회 재현).
    #  v1은 95% 사용·10,000원 잔여를 "전체 예산을 모두
    #  사용했어요"로 썼다. 숫자가 맞아서 verify_summary_pure가
    #  못 잡는다(검증기는 토큰만 보고 서술의 과장은 못 본다).
    #  규칙을 넣어도 2회 다 안 지켜졌고, 원인은 few_shot이
    #  같은 상황을 이미 보여주고 있어서였다 — 규칙보다 예시가
    #  세다. v2는 그 상황을 예시로 못박았다.
    "judge": "v3",  # 근거 충실성(환각 검증) 차원 — 실모드 A/B 승격(2026-07-29):
    #  정상 사유 17/17 v2와 일치(과잉 불합격 0) + 수치 조작
    #  프로브 6/6 탐지(v2는 0/6). 캘리브레이션 2회+judge 모델
    #  mini→4o 승급이 전제(models.yaml 참조)
    "classifier": "v8",  # 전역 9종 대응(v3) → 물건 형태의 교육 지출(v4) →
    #  활동 용품 vs 활동 참가 경계(v5) → 교육 참가비 경계(v7→v8).
    #  전부 실모드 A/B 승격 (각 2회 재현. 하니스 scripts/ab_classifier.py):
    #    v3 11/14(78.6%) → v4 13/14(92.9%)  회귀 0
    #    v4 14/17(82.4%) → v5 17/17(100%)   회귀 0
    #    v6 19/24(79.2%) → v7 23/24(95.8%)  A/B 회귀 0 (2026-08-10)
    #  v7이 승격 후 실모드 골든 73건(2회 동일)에서 회귀 4건 발견 → v8로 교체.
    #  v7의 '복합어는 뒷말이 대상' 규칙이 행사 홍보물(현수막→비품)·학습
    #  자료(구입→비품)·택배(→교통)·행사 숙박(→회의)을 깨뜨렸다.
    #  v8 = v7 − 그 규칙. 자세한 실측은 prompts/classifier/v8.yaml 헤더.
    #  A/B 그물에도 회귀 4유형을 추가해 같은 구멍을 막았다(28케이스).
    #  참가비 경계가 고친 것: 강연·강습 참가비를 v6이 전부 행사_활동으로
    #  보냈다(골든 club-approve-004·social-approve-003 오분류의 원인).
    #  반대 방향(체육대회·페스티벌 참가비)은 유지.
    #  v6은 A/B 승격이 아니라 **정합 수정**이었다 (T7, 리뷰 B-2):
    #  v5의 confidence 문단이 T7로 제거된 category_mismatch
    #  메커니즘("관리자를 부르는 스위치")을 가르치고 있었다 —
    #  실제 의미(0.8 미만 = 답 폐기·키워드 위임)로 정정.
    #  판정 기준·few_shot은 v5 그대로(효과 귀속 보존).
    "budget_planner": "v3",  # 실측 A/B 승격이 아니라 **계약 교체**다 (2026-08-06, T4).
    #  출력 스키마가 ProposalText(adjustments·rationale)에서
    #  BudgetMessage(3블록)로 바뀌어, v1·v2 프롬프트는 코드가
    #  요구하는 필드를 아예 가르치지 않는다. 승격하지 않으면
    #  실모드가 구 계약 프롬프트로 3블록을 만들게 된다.
    #  ⚠️ 이 누락은 테스트가 못 잡는다 — v1이 기본이어도 v1.yaml의
    #  version 필드와는 정합이라 test_prompts는 그대로 통과한다.
    "default_policy": "v3",  # v3는 정책 수정(2026-08-11): 적용되지 않는 조항으로
    #  warn하지 않는다. 데모에서 '친목' 팀의 사업자 등록비가 "과반이
    #  참여하지 않은 활동 비용" 조항을 근거로 보류됐다 — 행정 수수료는
    #  '활동'이 아니라 그 조항의 적용 대상이 아닌데도. 판정 규칙에
    #  '조항 적용 여부' 0단계를 세우고 warn을 "적용되는 조항이 있는데
    #  어긋날 때"로 좁혔다. 원인의 절반은 few_shot 앵무새였다(warn 예시
    #  "…으로 보임 — 다만 …" 틀을 그대로 베낌) — 조항 미적용 pass 예시를
    #  추가했다. 기존 3건은 바이트 동일(이어폰 warn 안전망 보존).
    #  rule_auditor/v6와 같은 날 같은 원칙 — 회칙 유무로 화면이 갈리면 안 된다.
    #  ── 아래는 v2 이력 ──
    #  정합 수정(2026-08-07, classifier v6 전례): 예시 라벨 '다과'가
    #  전역 9종에 없었다 → 식비. 종전에는 **미등재라 v1 폴백**으로
    #  돌았다 — 파일만 만들면 반영이 안 되는 자리라 등재가 수정의
    #  절반이다 (budget_planner의 ⚠️와 같은 함정).
    "query_rewriter": "v2",  # 정합 수정(2026-08-07): 예시 라벨 '회식비'·'도서' → 식비·교육.
    #  마찬가지로 종전 미등재 → v1 폴백이었다. 출력 질의문은 회칙
    #  어휘 자유 텍스트라 그대로 뒀다.
    "rule_amendment": "v3",  # v2(실측 A/B 승격이 아니라 **정합 수정**, 2026-08-07)에 이어
    #  또 정합 수정(2026-08-10, A 리뷰): 군집 요약 예시2의 "[장비/용품비]"가
    #  카탈로그 밖 값이었다 — "[비품]"으로 정정. few_shot 전체가 평문이라
    #  기존 카탈로그 라벨 계약 테스트가 애초에 못 잡던 자리였다.
    #  v2는 2026-08-04 브랜치 통합 때 이미 sblim에만 있던 버전으로 파악됐지만
    #  (docs/internal/프롬프트_브랜치_통합계획_2026-08-04.md 24행
    #  "sblim에만"에 rule_amendment/v2로 기록) DEFAULT_VERSIONS 합류가
    #  누락돼 조용히 v1로 폴백해 왔다. v2는 ① few_shot 입력을
    #  summarize_gap_pure(rule_amendment.py)가 실제로 조립하는 형식에
    #  맞게 다시 썼다(v1 예시 입력은 그 형식과 달랐다) ② few_shot이
    #  한도 상향(승인) 방향 1건뿐이라 반복 반려 군집이 들어와도 모델이
    #  늘 승인 방향을 제안하도록 편향돼 있던 것을, 금지 조항 신설(반려
    #  방향) 예시를 추가해 바로잡았다.
}


class PromptSpec(BaseModel):
    version: str
    system: str
    few_shot: list[dict] = []

    def system_with_few_shot(self) -> str:
        """few_shot이 있으면 system 뒤에 예시 블록을 조립해 반환."""
        if not self.few_shot:
            return self.system
        examples = "\n\n".join(
            f"예시 {i}:\n입력: {ex.get('input', '')}\n출력: {ex.get('output', '')}"
            for i, ex in enumerate(self.few_shot, 1)
        )
        return f"{self.system}\n\n{examples}"


@lru_cache
def _load(agent: str, version: str) -> PromptSpec:
    path = _PROMPTS_DIR / agent / f"{version}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptSpec(
        version=data["version"], system=data["system"], few_shot=data.get("few_shot") or []
    )


def load_prompt(agent: str, version: str | None = None) -> PromptSpec:
    """version 미지정 시 `PROMPT_VERSION_{AGENT}` 환경변수 → DEFAULT_VERSIONS → 'v1'.

    환경변수 해석을 캐시 밖에서 하므로, A/B 비교 러너(eval/compare_prompts.py)가
    같은 프로세스 안에서 버전을 바꿔가며 실행해도 즉시 반영된다.
    """
    version = (
        version
        or os.environ.get(f"{_ENV_PREFIX}{agent.upper()}")
        or DEFAULT_VERSIONS.get(agent, "v1")
    )
    return _load(agent, version)
