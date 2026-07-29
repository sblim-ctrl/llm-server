# PROGRESS.md — BudgetOps LLM 서버 진행 기록

> 새 세션에서 이 파일만 읽고 바로 이어서 작업할 수 있도록 작성. 최종 갱신: 2026-07-29.

## 0-5. HITL 완료 + 프롬프트 승격 2건 (2026-07-29, cowbro)

- **HITL 사람 개입 완료 (674fa3d)**: escalate 노드가 hitl_enabled(데모 경로 전용)일
  때 interrupt()로 정지 → SSE `paused` 이벤트 → `POST /v1/reviews/{id}/decision`
  으로 관리자 승인/반려 → 같은 체크포인트(MemorySaver)에서 재개 → 콜백
  (processedBy=ADMIN)·판례 저장(decided_by=ADMIN, 학습 루프의 사람 축)까지 한 흐름.
  워커 경로 불변(플래그 없음 — 골든셋 42/42 재확인). 브라우저 E2E: 영수증 불일치
  → ⏸ → 승인 재개 → DB [ADMIN] 판례 확인.
- **judge v3 승격** (`DEFAULT_VERSIONS`): 근거 충실성(faithfulness — 관리자 사유
  인용 수치를 심사관 소견과 대조, 환각 검증) 차원. **승격까지의 실측 여정이 곧
  교훈**: 1차 A/B에서 정상 반려 사유 5건 오탐(파생 수치를 환각 판정) → 캘리브레이션
  → 여전히 필드 혼동(요청자/관리자 사유 헷갈림, few_shot 앵무새 — 프롬프트 교정
  2회 무효) → **judge 모델 mini→gpt-4o 승급**(models.yaml, 평가 전용이라 비용 미미)
  → 최종: 정상 사유 17/17 v2와 일치(과잉 불합격 0) + 수치 조작 프로브 **6/6 탐지
  (v2는 0/6)**. "judge 자신도 실측으로 보정해야 한다"(v1→v2 교훈)의 재확인 +
  "약한 모델은 프롬프트로 안 고쳐질 수 있다"가 신규 교훈.
- **policy_drafter v2 승격**: 7/28 실측 2회(비겹침 시나리오 4종, 조항 3.0→5.2개,
  운영규칙→지출기준 전환, 예시 복사 0건) 근거로 기본값 전환.
- **eval/compare_judge.py 신설**: judge 버전 A/B + 환각 프로브(수치 자릿수 시프트
  조작) 정식 러너 — 사유 캐시(eval/results/, gitignored)로 재실행 시 심사비 절약.
  run_eval_judge는 judge v3+일 때 소견을 전달하도록 확장.
- 발표용 아키텍처 스토리 v1 작성(바탕화면 기획 폴더 — 발표 자료 리포 반영 금지
  결정 준수).

## 0-4. 프롬프트 v3 트랙 + 강의 후반부 기법 보강 (2026-07-22~28, cowbro — 전부 push됨)

배경: 기획에 있던 기능(관리자 개입·검색 보강·실시간 표시)이 LLM 작업명세엔 빠져
있던 공백을 메우는 트랙. 커밋 순서대로:

- **judge v3 초안 (f2e9416, 미승격)**: LLM-as-Judge에 근거 충실성(faithfulness)
  차원 추가 — 관리자 사유가 인용한 수치가 심사관 소견에 실재하는지(환각 여부)
  대조. `judge_reasons()`가 opinions 선택 인자 수신(호환), 목 채점 결정적 대조.
  승격은 실모드 A/B 후 (PROMPT_VERSION_JUDGE=v3).
- **policy_drafter v2 초안 (bd5132f, 미승격)**: few_shot 3종(장비/지식/친목) +
  분량·문체 기준, MAX_EXTRA_RULES 3→7. 실측(실키·RAG 연결, few_shot 비겹침
  시나리오 4종): 추가 조항 평균 3.0→5.2개(전체 10.2개 = 모바일 카드 1장),
  운영 규칙 생성 → 전건 인정/불인정 기준으로 개선, 예시 복사 0건.
- **query_rewriter/v1 신설 + rule_auditor CRAG 재작성기 승격 (148dd73)**:
  52줄 TODO 이행 — 재검색 질의를 고정 템플릿에서 gpt-4o-mini 재작성으로(실모드만,
  목은 기존 템플릿 그대로라 골든셋 불변). 실측: 1차 검색이 실제로 빗나간 청구
  ("캠핑 장비")에서 정답 조항(제5조 비품·물품)을 1위(d 0.498)로 견인, 템플릿의
  '금지' 어휘 편향(금지 조항이 1위로 오던 것) 해소. 건당 $0.00008.
- **실시간 심사 SSE (6c86841)**: POST /v1/reviews/stream(데모·관측 전용, §2.2
  동기 예외 관례) + 대시보드 세로 타임라인(병렬 뱃지·소견 인라인·분기 건너뜀
  표시). 노드 목록↔그래프 배선 정합 테스트로 드리프트 방지.
- **카테고리 불일치 가드레일 (d41fba1)** ⚠️ 팀 결정 변경 — 팀장 공유 필요:
  "사용자 카테고리 존중(7/10)"을 유지하되, AI 분류가 **확신을 갖고 불일치**하면
  category_mismatch로 escalate(라벨 불변·반려 아님 — C2 추천만 원칙). 카테고리
  위장(카테고리별 회칙 한도 회피)·통계 오염 방어. 1차 구현이 골든셋 붕괴
  (승인 R 55% — 골든셋 구명칭 `도서` vs 카탈로그 `교재/자료비` 어휘 차이로 전건
  오탐) → "카탈로그 6개 안의 값일 때만 비교" 조건으로 42/42 복구. **어휘 통일
  확인(풀스택 FQ9) 후 '목록 밖 값=비정상 입력→보류'로 강화 예정.**
- **심사 소요시간 실측 (7/28, 표본 9건)**: 그래프 중앙값 3.3s·최대 4.4s —
  백엔드 콜백 예산(bravo "예: 30초") 대비 여유. 단일 워커 순차 처리라 동시
  7~8건이 한계 → 워커 증설은 예상 동시량(풀스택 FQ8) 확인 후.
- **환경 정비 (7/28)**: 도커가 7/22 실모드 실험 잔재로 떠 있던 것 목 모드
  재빌드(핸드오프 경고 항목), demo-% 팀의 실임베딩 잔재 청크 26개 삭제(목 검색과
  좌표계 불일치로 rule_ambiguous 오탐 유발). **OpenAI 429 사건(정정 7/29)**:
  7/28 17:19 워커에서 429 insufficient_quota 연속 — 단 같은 시간대 .env 키
  직접 테스트는 성공했고 팀장 확인 결과 계정 잔액 정상. 429는 **7/22 기동된 구
  컨테이너가 품고 있던 키 스냅샷**에서 난 것으로 추정(컨테이너는 기동 시점 env를
  보존). 심사관 error→escalate fail-safe는 정상 동작. 재빌드로 현행 키와 일치
  확인 — 교훈: 실모드 컨테이너는 키·모드가 기동 시점에 고정되므로 재빌드로 갱신.
- **풀스택 질의 문서 작성 → **팀장 전달메시지와 중복 5건 제거 후 12~15번 보완 4건으로 슬림화**(docs/풀스택_추가_회신요청_12-15_2026-07-29.md)**: 필드명 대조(verdict↔finalVerdict 등)·자동승인
  주체 문서 상충·callback_url·30초 제한·카테고리 명칭 통일/기타 추가.
  리포 반영 완료(e9c1b1c) — 풀스택팀 전달은 사용자 몫.
- **다음**: interrupt() 기반 사람 개입(HITL — escalate에서 그래프 멈춤→관리자
  결정으로 재개) 착수 예정. 조건부 ③④는 계속 회신 대기.

## 0-2. `/v1/analyze` pull 모델 재설계 완료 (2026-07-16)

§0-1이 예고한 재설계를 구현 완료. 단위 테스트 110개 통과, ruff 클린.
**E2E 검증도 완료(재부팅 후 같은 날)**: 골든셋 30/30·Trajectory 23/23·오승인 0건,
멱등성 스트레스 테스트(도커 스택 리빌드 후 새 5필드 payload로) 통과 — 동시 20건
(각기 다른 백엔드 jobId) → 내부 잡 1개 수렴, 완료 후 재제출은 새 잡.

무엇이 바뀌었나 (커밋 1개, 이 세션):
- **`AnalyzeRequest` 5필드 pull 모델** (`app/schemas/analyze.py`): camelCase alias
  (`jobId/expenseId/organizationId/reviewGoal/receiptPath` — 뒤 2개 키 이름은 가정,
  백엔드 회신 후 alias만 조정). 구 push 계약(claim 인라인)은 수락 안 됨.
- **backend_client 신규 3함수**: `get_expense_detail`(목 규약: expense_id의
  `?title=&amount=...` 쿼리 오버라이드 — api/worker가 별도 프로세스라 in-memory
  시딩 불가, ID 인코딩만이 양쪽에서 동작), `get_team_settings`(목 규약: org id에
  `noauto` 포함 → auto_approve=False), `get_receipt_by_path`(Agent 토큰 재요청 자리).
- **load_context가 pull 수행**: claim 없으면 백엔드에 되물어 구성(조회 실패 = 예외
  전파 → 재시도/fail-safe), team_settings → PolicyParams(조회 실패 시
  auto_approve=False fail-safe). 초기 상태에 claim이 있으면(직접 그래프 호출 —
  smoke·seed_demo·단위테스트) 조회 생략.
- **auto_approve 최상위 게이트**: `PolicyParams.auto_approve` 신설(실계약 기본
  FALSE), `evaluate_guardrails` 규칙 0번 `auto_approve_disabled` — 꺼져 있으면
  소견·금액 무관 무조건 escalate(반려 후보도). 소견 수집은 그대로 해서 관리자
  참고용 detail은 콜백에 실림.
- **jobId 매핑**: 백엔드 발급 jobId는 `jobs.external_job_id` 컬럼(신설, ALTER 포함)에
  저장 — 내부 jobs.id(UUID)는 thread_id·체크포인트 키로 유지. 콜백·fail-safe 콜백은
  external을 echo(ai_job_id 대조 통과용), `GET /v1/jobs/{id}`는 양쪽 id 모두 조회
  가능. 활성 잡 dedupe 시 external_job_id 최신화(재제출 대응; 이미 실행 중이면
  payload는 안 건드림 — 옛 jobId 콜백은 백엔드 폴링 안전망에 위임).
- **fail-safe 콜백 버그 수정**: 워커 재시도 소진 콜백이 snake_case dict를 보내고
  있었음 → 정식 CallbackPayload(camelCase) + external jobId echo로 교정.
- **골든셋 30건 입력 재작성** (`eval/golden/golden_v1.json`): pull 모델 5필드로 변환
  (스크립트 일괄 변환, 시나리오·기대값 불변). 쿼리 값은 최소 이스케이프(%,&,=,+,#만)
  — 한글 가독성 유지, parse_qs가 복원.
- **대시보드 심사 탭·stress_idempotency.py** 새 계약으로 갱신. `AnalyzeAccepted`는
  내부 job_id(dedupe 가시성) + external_job_id echo 둘 다 반환.
- **신규 테스트**: `tests/test_analyze_pull_model.py`(계약·목 규약·fail-safe 9건) +
  guardrail auto_approve 2건 + callback external echo 2건.

미결(백엔드 확인 대기, §0-1 질의요청서와 동일): reviewGoal/receiptPath 실제 JSON 키,
지출 상세·team_settings·영수증 조회 엔드포인트 경로, 콜백 수신 경로·토큰 방식,
ESCALATED의 review-result 기록 여부. 전부 `backend_client.py`/alias 한 곳 교체로 대응.

## 0. 최우선 — 실제 풀스택 API 명세 확보됨 (2026-07-15, 같은 날 2차 정정됨)

> **⚠️ 정정(2026-07-15 2차)**: 바로 아래 문단이 "BudgetPlanner·DigestWriter·
> 회칙개정 3개는 진행 안 한다"고 썼는데, **이후 팀장 확인 결과 이 3개 전부
> 예정대로 구현하는 것으로 확정됐다.** MVP 제외 결론은 폐기. 최신 업무분장은
> `기획/업무분장_스프린트1_작업명세_v3.md`(최종본, docx 버전도 있음)를 볼 것 —
> 개발자 A/B 작업 목록에 세 기능이 전부 포함되어 있다. 아래 §0의 API 계약 분석
> (API-043/044/045/024, `/v1/analyze` 재설계 필요성)은 **여전히 유효** —
> 이건 "새 기능이 필요 없다"는 이야기가 아니라 "기존 심사·콜백 파이프라인의
> 입력 계약이 실제와 다르다"는 별개의 발견이라 그대로 유지됨.

`기획/bravo_API명세서.xlsx`(풀스택 bravo팀, API 49개 + 상태코드 시트) 수령.
(**과거 기록, 뒤집힘 — 위 정정 참고**) `기획/업무분장_스프린트1_작업명세.md`(다른
세션이 작성한 A/B 2인 분장 문서)의 신규 기능 3종 — BudgetPlanner(예산 제안)·
DigestWriter(주간 브리핑)·PolicyDrafter 개정 모드(회칙 개정 제안) — 는 49개 API
어디에도 없어서 한때 "진행하지 않는다"고 결론 내렸으나, 팀장 확인 후 3개 다
진행하는 것으로 최종 확정됨. 스프린트1 문서의 A1-A7 항목은 유효하며
`업무분장_스프린트1_작업명세_v3.md`로 갱신됨. B1-B7(실모드 전환·신뢰성·평가)도
아래 내용으로 갱신됨.

**LLM 서버가 실제로 관련된 API는 4개뿐**(명세서 원본은 `기획/` 폴더 참조):
- **API-044** `POST /api/expenses/{id}/ai-review` — 지출 등록(API-016) 시 백엔드가
  내부적으로 호출(프론트가 직접 호출 안 함). 우리 심사 그래프가 이 내부 호출을 받는
  실질적 소비자로 추정(정확한 트리거 경로는 백엔드팀 확인 필요 — 지금 `/v1/analyze`가
  이 역할을 하는지, 백엔드가 별도로 감쌀 것인지 미확정).
- **API-045** `GET /api/expenses/{id}/review-result` — 응답
  `review:{finalVerdict, detail, suggestedCategory, processedBy, createdAt}`.
  우리 콜백(`/agent-callback`, API 목록엔 없음 — 내부 전용 채널로 추정)이 이 필드를
  채울 데이터를 실어 보내야 한다. **2026-07-15 반영**: `CallbackPayload`에
  `suggested_category`(classify_category 결과)·`processed_by`(기본"AI") 추가,
  전체 필드 camelCase 직렬화(`by_alias=True`) — 백엔드 전 API가 camelCase라서
  snake_case로 보내면 백엔드가 못 읽는다. `detail`은 우리 쪽 `reasons`+`opinions`를
  조합해 백엔드가 구성하는 것으로 가정(확정 아님).
- **API-043** `POST /api/policies/recommend` — body는 **`teamId` 하나뿐**, 응답은
  `recommendedPolicies: [{title, policyType, content}]` **배열**. **현재 우리
  `/v1/policy-draft`·`PolicyDraftRequest`(team_type/team_name/initial_budget/
  description 요구)·`PolicyDraft`(rules 문자열 배열+policy_params) 응답 구조와
  완전히 다르다 — 계약 재설계 필요, 아직 미착수.** teamId만 오므로 team_type 등은
  `get_team_profile`/`get_budget_status`로 우리가 직접 조회해야 함. **미해결 — 다음
  세션에서 사용자와 상의 후 착수**(policyType이 뭘 의미하는지, 몇 개 추천할지 등
  백엔드팀 확인 필요할 수 있음).
- **API-024** `GET /api/teams/{id}/dashboard/ai-summary` — 응답은 `{summary}` 문자열
  하나. 지금 우리에게 대응하는 엔드포인트 없음(새 기능 아니라 실제 명세에 있는 진짜
  요구사항). ReportWriter의 `summary` 필드를 재활용해 가벼운 동기 엔드포인트로 노출
  가능해 보임 — **미착수**.

**다음 세션 최우선 순서**: ① API-043 정책 추천 계약 재설계 방향 사용자와 확정
② API-024 AI 요약 엔드포인트 신설 ③ 콜백 API-044/045 실제 트리거 경로 백엔드팀과
확인 ④ 이후 스프린트1 B2~B7(LLM 하네스·LangSmith·워커 신뢰성·Vision OCR) 계속.

## 0-3. 업무분장 후 개발자 A 트랙 진행 (2026-07-20, cowbro 브랜치)

담당 확정: 사용자 = **개발자 A** (`docs/업무분장_스프린트1_작업명세_v2.md` 3차 개정).
브랜치 전략: 각자 개인 브랜치(sblim=팀장/cowbro=A) → 완료 시 main.

- **A-1 로더·A-3 하네스**: 업무분장 전 세션에서 기완료 (07-15 커밋들).
- **A-2 레지스트리·A-5 잔여(콜백 3회 재시도+dry_run)·A-7 digest YAML**: 85e2f3c.
- **A-4 DigestWriter**: eecb883 — 주간 집계·이상 징후 2종(목 데이터 발화 확인)·
  BurnForecast 재사용(C8, B-2는 팀장 커밋 08f72d2 체리픽). E2E 검증 완료
  (202→succeeded→verified=true, weekly_spent 108,000원·식비 급증 발화).
  핸들러 계약 (result, final_state|None) 확장 선반영 (7/20 팀 합의 ①).
- **main 병합·3파일 해소 완료 (983fc21)**: 레지스트리 베이스에 proposal 2종 이식
  +B-7 전부 흡수(_meta_totals·무체크포인트 방어·reclaim), fail-safe 콜백 합집합
  (camelCase echo + review 한정 가드). test_worker_recovery는 레지스트리 디스패치에
  맞게 JOB_HANDLERS setitem 패치·pull 모델 payload로 정합(팀장 리뷰 시 확인 요망).
  테스트 160개·골든셋 30/30·통합 E2E(review+digest+proposal_budget) 통과.
- **A-8 대시보드 탭 완료**: '예산 제안'(PATCH 수락/기각, 재결정 409 처리)·
  'AI 총무 브리핑'(주간 stat 4종+이상 징후) 탭 추가. /ui 서빙·탭 흐름 E2E 검증.
- **A-6 완료**: chat_structured_vision(bytes→base64/URL, 하네스 공유) +
  intake 실모드 배선(get_receipt_by_path seam, 실패=parse_ok=False→escalate 불변).
- **A-9 실모드 검증 완료(2026-07-20, 실키 수급)**: README '실모드 수동 체크리스트'
  참조. 심사 실 E2E approve/conf 0.95/건당 $0.008, Vision 실이미지 추출·판독불능
  escalate, Digest 실생성 verified, 실판례 루프 인용 확인. **실측 수정 3건**:
  ① with_structured_output method="function_calling" (기본 strict가 Opinion.figures
  자유 dict를 400 거부 — 목에선 안 드러나는 버그) ② RELEVANCE_MAX_DISTANCE
  0.5→0.65 (실거리: 관련 0.42-0.51/무관 0.71+) ③ digest_writer 프롬프트 필수 표기
  형식(검증기가 실LLM 환각 수치 1회 실제 차단 후 정합). LangSmith 키 수급 후
  트레이스·마스킹 와이어 확인도 완료(C9 태깅 형식·실명 부재를 LangSmith API
  역조회로 실증). 잔여: B-8(팀장 몫)뿐.
- **다음**: cowbro→main 머지(팀장 리뷰 대기 — 사용자 지시 전 머지 금지).

## 0-1. 더 중요한 발견 — `기획/bravo_기술아키텍처설계서.docx` (풀스택 구현 설계서, 2026-07-15)

xlsx는 "API 목록"일 뿐이고, 이 docx가 **우리 심사 파이프라인이 실제로 받는 요청의
정확한 모양**을 규정한다. **결론: 지금 `/v1/analyze`(`AnalyzeRequest`)의 입력
계약이 실제와 다르다 — 빠른 패치가 아니라 재설계 대상.** API-0XX 번호는 xlsx
버전(v1/v2)마다 바뀌므로(예: ai-review가 문서 안에서도 API-041과 API-044 두 값으로
등장) **URL 경로를 기준으로 식별할 것, 번호는 신뢰하지 말 것.**

### 실제 심사 요청 payload (TABLE 18) — 지금 우리 스키마와 다름
백엔드가 Agent Server(우리)에 보내는 필드는 딱 5개뿐: `jobId, expenseId,
organizationId, 심사목표(자연어 지시문), Spring 내부 영수증 조회 경로`.
**title/amount/category/description/영수증 파일은 요청에 없다.** 즉 지금
`AnalyzeRequest`가 요구하는 `claim{title,amount,category,date,description}` +
`receipt_signed_url` 인라인 방식은 실제와 다르다 — **push 모델(지금 우리) →
pull 모델(실제)로 전환 필요**: 우리가 `organizationId`+`expenseId`로 지출 상세를
백엔드에 되물어 가져와야 함.

### 확인된 사실 (재설계 시 지켜야 할 것들)
1. **jobId는 백엔드가 발급** — 우리가 `insert_job`에서 자체 UUID를 만드는 지금
   방식과 다름. 콜백 때 받은 jobId를 그대로 돌려줘야 백엔드가 `expenses.ai_job_id`와
   대조해 유효성 검증(재제출로 무효화된 옛 jobId면 무시).
2. **영수증은 "조회 경로"(동적 참조)로 옴** — Agent 전용 토큰으로 Spring Boot에
   재요청해서 이미지를 받아온다. 지금처럼 `receipt_signed_url`을 우리가 직접
   fetch하는 방식이 아님. `backend_client.py`에 신규 함수 필요
   (경로/토큰을 인자로 받는 형태).
3. **LLM 호출 2단계 구조가 명시됨**: 1차=OCR "읽기"만(구조화 데이터+공개 가능한
   심사 계획 생성), 2차=`organizationId`로 조회한 예산·회칙·최근지출까지 곁들인
   "판단"(승인/반려/에스컬레이션 추천+근거). **이건 우리 `intake_receipt →
   rule/budget/precedent 3심사관 → adjudicate` 구조와 개념적으로 일치** — 그래프
   큰 골격은 재사용 가능해 보임, 안심 포인트.
4. **`team_settings.auto_approve` 기본값 FALSE** — 꺼져 있으면 금액·판단과
   무관하게 무조건 ESCALATED. 지금 우리 그래프엔 이 최상위 게이트가 없음(항상
   confidence 기준 자동판정 시도) — `backend_client.py`에 team_settings 조회
   함수(`auto_approve`, `auto_approve_limit`, `escalation_threshold`) 신규 필요,
   `guardrail_gate` 이전에 이 체크가 선행돼야 함.
5. **`expenses_reviews.final_verdict`는 APPROVED/REJECTED만 존재, ESCALATED는
   그 테이블에 아예 안 남음** — escalate일 땐 `expenses.status`만 바뀌고 우리
   콜백의 상세 내용은 기록 대상이 아닐 가능성. approve/reject와 escalate를
   콜백에서 다르게 다뤄야 할 수 있음(확정 아님 — 백엔드팀 확인 필요).
6. **`detail`(JSON)은 자유 필드** — 우리 `reasons`+`opinions`+`mismatch` 조합을
   그대로 넣으면 될 걸로 보임(2026-07-15 커밋에서 이미 이 형태로 콜백 구성해둠,
   변경 불필요해 보임).
7. **AgentInternalController(`/api/internal/...`)가 콜백 수신처** — xlsx API
   목록엔 없음(내부 전용). 지금 우리 `send_callback`이 치는 `{BE}/agent-callback`
   경로가 실제로 이 경로와 같은지, Agent 전용 서비스 계정 토큰 인증 방식(4절
   'Agent 전용 토큰')이 지금 `service_token` Bearer 방식과 같은지 확인 필요.
8. **콜백 실패 시 백엔드가 이미 30초 타임아웃+1회 폴링+자동 ESCALATED 안전망을
   가지고 있음** — 우리 쪽 재시도(B4 계획)는 이 백엔드 안전망과 별개로 유효하나,
   중복 안전장치라는 것을 인지할 것(나쁘지 않음, 이중 보호).

### 재설계가 필요한 파일 (✅ 2026-07-16 완료 — §0-2 참고. 아래는 당시 계획 원문)
- `app/schemas/analyze.py`(`AnalyzeRequest`) — 5필드 pull 모델로 축소
- `app/graphs/review/nodes/load_context.py` — organizationId로 지출 상세·
  team_settings·영수증을 백엔드에서 가져오는 로직 추가
- `app/tools/backend_client.py` — `get_expense_detail`, `get_receipt_by_path`,
  `get_team_settings`(또는 기존 `get_budget_status`류에 통합) 신규 함수
- `app/db/pool.py`(`insert_job`) — 백엔드가 준 jobId를 우리 jobs.id로 쓸지,
  별도 컬럼(`external_job_id`)으로 매핑할지 결정 필요
- `app/graphs/review/graph.py` — `auto_approve` 최상위 게이트 추가 위치 결정
- 골든셋 30건(`eval/golden/golden_v1.json`) — 입력 스키마가 바뀌면 전부 재작성
  필요(영향 범위 큼 — 재설계 착수 전 이 점 감안)

**(2026-07-16 갱신)**: 위 재설계는 완료됨 — 상세는 §0-2. 골든셋 입력 스키마도
30건 전부 재작성됨(시나리오·기대값 불변).
> 코드의 최신 진실은 항상 git log와 실제 코드 — 이 문서와 어긋나면 코드가 맞다.

---

## 1. 프로젝트 개요

**BudgetOps** — 모임(동아리/학생회·스터디·친목·동호회·회사 5개 유형)의 지출 요청을
AI가 회칙·예산·판례에 근거해 1차 심사(승인/반려)하고, 확신 없는 건만 관리자에게
에스컬레이션하는 서비스. AI가 "의견 참고인"이 아니라 **승인/반려의 실행 주체**인 것이
핵심 차별점이며, 그만큼 안전장치(코드 가드레일, fail-safe, 오승인율 0% 게이트)를
아키텍처 수준에서 보장한다.

부트캠프 파이널 프로젝트 (2026-07-02 ~ 08-14, 6주). **LLM 에이전트 팀**이 이 리포
(`llm-server`)를 담당하고, 풀스택 팀(Spring 백엔드 + Next.js 프론트)과 협업하되
API 계약(콜백 스키마 등)만 맞추면 독립 배포하는 구조. 설계 근거 문서는
`docs/설계서.md` (원본: `C:\Users\user\Desktop\파이널프로젝트\기획\LLM팀_아키텍처_워크플로우_설계서.md`).

스택: FastAPI(llm-api) + LangGraph 1.x 워커(llm-worker) + Postgres/pgvector(llm-postgres),
Python 3.12 고정, uv로 패키지 관리, docker-compose 3컨테이너.

## 2. 현재 상태 (뭐가 되고 뭐가 안 되나)

### 동작하는 것 (전부 목 모드 E2E 검증 완료)
- **지출 심사 그래프** (`app/graphs/review/`): load_context → classify_category →
  intake_receipt → mismatch_gate → [rule/budget/precedent 3-심사관 병렬 fan-out] →
  guardrail_gate → adjudicate → execute_decision/escalate → callback → persist_precedent.
  AsyncPostgresSaver 체크포인터로 재시도 시 완료 노드부터 재개.
- **판례 학습 루프**: 관리자 결정(`POST /v1/precedents`) → PIIMasker 익명화 → 임베딩 저장 →
  다음 유사 지출에서 PrecedentAuditor가 인용. 반려 판례→escalate 유도, **승인 판례→회칙
  애매(rule_ambiguous)를 상쇄해 자동 승인 유지** 양방향 모두 구현.
- **PolicyDrafter** (`POST /v1/policy-draft`, 동기): 템플릿 로드 → retrieve_references(RAG)
  → generate_draft(LLM, 소개 기반 추가 조항 최대 3개) → verify_draft(코드 검증).
- **ReportWriter** (`POST /v1/reports/summary`, 잡): 지출 집계 + 예산 활용 추천.
- **BriefingWriter** (`POST /v1/briefings`, 잡): 판례 로그 기반 인수인계 브리핑, 회칙 vs
  실운영 갭 감지.
- **카테고리 자동 분류**: 지출 등록 시 카테고리 비면 모임 유형별 고정 6개 중에서 AI 분류.
- **인덱싱 파이프라인** (`POST /v1/context/refresh`): 회칙 원문 → 4단계 청킹 → 임베딩 →
  원자적 버전 전환.
- **MCP 서버** (`/mcp`): 읽기 툴 4종 Streamable HTTP 노출. `scripts/smoke_mcp.py`로 검증.
- **내부 검증 대시보드** (`/ui`): 순수 HTML 단일 파일, 4탭 (심사/초안/리포트/골든셋평가).
- **평가**: 심사 골든셋 30건 verdict 30/30, Trajectory 23/23, 오승인 0건. CSV 자동 출력 +
  `eval/analysis.ipynb` 노트북(실행 검증 완료).
- **라이터 골든셋** (2026-07-15 추가): 문서 생성 3종 시나리오 17건
  (PolicyDrafter 10 / ReportWriter 3 / BriefingWriter 4) 17/17 통과.
  하드 게이트 = verified(Generator-Evaluator 검증) 불통과 0건. CLI
  `eval/run_eval_writers.py` + `GET /v1/eval/writers` + /ui 골든셋 탭 둘째 카드.
  Briefing 케이스는 실행 시 판례를 팀 단위 삭제 후 재시드(멱등, save_precedent 경로 그대로).
- **Docker 전체 스택**: `docker compose up --build` 빌드·기동·E2E 검증 완료 (2026-07-14).
- 단위 테스트 77개 전부 통과, ruff 클린.

### 안 되는 것 / 아직 가짜인 것
- **모든 LLM 판단이 목(mock)**: `.env`의 `OPENAI_API_KEY`가 비어 있고 `MOCK_LLM=true`.
  `app/llm/client.py`의 `chat_structured()`/`embed_texts()`가 mock_response/해시 벡터를
  반환. **"AI가 판단했다"고 보이는 모든 것이 사실은 코드에 박힌 고정 응답·키워드 규칙**.
  임베딩도 해시 기반이라 유사도 검색의 "의미적 관련성"은 검증 불가(SQL·스코프만 검증됨).
  **2026-07-15 진전**: 노드들이 보내던 `system="(prompts/…yaml에서 로드)"` **글자
  그대로의 플레이스홀더 문자열**을 실제로 보내고 있던 버그를 고침 — `app/llm/prompts.py`
  신규(`load_prompt(agent) -> PromptSpec`, YAML의 `version:` 필드가 진실 원천, lru_cache)
  + adjudicate·rule_auditor·precedent_auditor·classify_category·policy_draft 5개 노드
  전부 연결. 목 모드에선 어차피 mock_response를 쓰므로 동작 변화 없음(무회귀 확인) —
  **실키 전환 시 비로소 효과가 나는 수정**이었음. 여전히 남은 문제: PII 마스킹이 LLM
  프롬프트 경로에 미연결(실키 전환 시 실명 유출 위험), Retry/타임아웃 없음, model/cost/
  latency가 정적값(`app/schemas/callback.py`의 `model_version="mock"` 등 하드코딩).
- **백엔드 연동 전부 목**: `MOCK_BACKEND=true`. 실제 필드명·엔드포인트는 풀스택 팀과
  미확정 ("다음에 받기로" 한 상태). 경계는 `app/tools/backend_client.py` 한 파일.
- **Intake Vision OCR**: 실키 필요. 현재 목은 URL 쿼리 파라미터/추출 텍스트 정규식 파싱.
- **LangSmith**: 배선 완료(B3, 2026-07-15 — `app/observability.py`: `setup_langsmith()`
  기동 주입 + `langsmith_config()` C9 태깅, review 잡 적용). **실키·계정으로 트레이스
  실확인은 미완** — `.env`에 `LANGSMITH_TRACING=true`+`LANGSMITH_API_KEY` 넣으면 활성.
- **B2 하네스 완료(2026-07-15)**: Retry(chat·embeddings 각 3회/30s), PII 마스킹
  (`chat_structured(mask_with=)` — load_context가 멤버 명단 적재), 호출 메타
  (`tuple[T, LLMCallMeta]` — tokens/cost/latency, models.yaml `pricing:` 단가표).
  호출부 5곳 전환, 리뷰 노드는 `llm_meta` reducer로 state 적재.
- **콜백·판례에 실측 메타 반영 완료(2026-07-15)**: CallbackPayload의 model_version/
  prompt_version/cost_usd(전 호출 합산)/latency_ms(started_at 대비)가 llm_meta에서
  채워짐 — adjudicator 미실행 escalate 경로는 `.get()` 안전 접근(크래시 방지).
  persist_precedent도 실제 모델·프롬프트 버전 기록. **jobs 테이블 cost/tokens 합산
  (finish_job 확장)만 남음.**
- **프롬프트 A/B 비교 러너 완료(2026-07-15)**: `eval/compare_prompts.py agent=v2` —
  베이스라인 vs 오버라이드 골든셋 2회 실행, 케이스별 판정 변화(↑개선/↓악화)·오승인
  증가 시 exit 1. 오버라이드는 `PROMPT_VERSION_{AGENT}` 환경변수(load_prompt가 해석).
  배관 검증 완료(v1 vs v1) — **실측 비교는 실키 후** (목은 프롬프트를 안 읽음).

## 3. 이 세션에서 변경/생성한 파일 (커밋 순)

전체 커밋: `git log --oneline` 20개. 주요 파일과 역할:

| 파일 | 내용 |
|---|---|
| `app/graphs/review/graph.py` | 심사 그래프 조립. `build_review_graph(checkpointer=None)`. 노드 12개 |
| `app/graphs/review/nodes/classify_category.py` | 유형별 카테고리 분류 v2. `PROMPT_VERSION="classifier/v2"` |
| `app/graphs/review/nodes/guardrail_gate.py` | `evaluate_guardrails()` 순수 함수. 규칙: missing_opinion/auditor_failed/receipt_unreadable/receipt_mismatch/rule_violation/**rule_ambiguous**(승인판례 있으면 미발동)/precedent_suspicion/over_auto_approve_limit/over_force_escalation_amount/budget_insufficient→reject후보 |
| `app/graphs/review/nodes/rule_auditor.py` | CRAG 검색 보정: `_retrieve_with_correction()` — 1차검색→거리 채점(`RELEVANCE_MAX_DISTANCE=0.5`)→재작성 재검색→불충분시 warn |
| `app/graphs/review/nodes/budget_auditor.py` | v2: 잔액 = `total_budget - spent` (총액 기준, 카테고리 한도 아님) |
| `app/graphs/review/nodes/intake_receipt.py` | `parse_receipt_text()` (백엔드 추출 텍스트 경로) + `mock://receipt?amount=&date=` 테스트 훅 |
| `app/graphs/review/nodes/precedent_auditor.py` | ADMIN 판례만 위험/지원 신호. `figures={"admin_approve_support": n}` 규약 |
| `app/graphs/writers/policy_draft.py` | 4노드: load_template→retrieve_references→generate_draft→verify_draft. `_mock_extra_rules()` 키워드 휴리스틱(등산/스터디/신입 3그룹만) |
| `app/graphs/writers/report.py` | `aggregate_pure()` 결정적 집계 + `_recommendations()` (편중≥40%/저활용≤5% 규칙) + `verify_report_pure()` 수치 대조 |
| `app/graphs/writers/briefing.py` | `aggregate_precedents_pure()` + 갭 감지(`ESCALATE_GAP_THRESHOLD=0.3`) |
| `app/graphs/indexing/nodes/chunk.py` | `split_into_clauses()` 4단계: 제N조→번호목록(`1.` `①`)→빈줄 문단→문장경계+overlap(100자) |
| `app/tools/category_catalog.py` | `load_catalog()`/`categories_for()`/`classify_by_keywords()` — writers·review 공유 |
| `app/tools/search_references.py` | PolicyDrafter RAG. `REFERENCE_SCOPE="__reference_corpus__"` 센티널로 context_chunks 재사용 |
| `app/tools/search_rules.py` / `search_precedents.py` | pgvector 검색 (version 고정 / active만) |
| `app/tools/precedent_store.py` | `save_precedent()`(마스킹+임베딩), `summarize_claim()`, `masked_claim_summary()` |
| `app/tools/backend_client.py` | 백엔드 경계. 목 규약: team_id에 `lowbudget`→잔액1000원, `club/study/social/hobby/company`→유형 추론(`get_team_profile`) |
| `app/llm/prompts.py` | **(07-15)** 프롬프트 YAML 로더 — `load_prompt(agent) -> PromptSpec(version, system, few_shot)`. C3 계약 |
| `prompts/*/v1.yaml` | **(07-15)** 4종 보강: few_shot(인젝션 방어 사례 포함)·confidence 산출 기준(adjudicator)·근거 인용 규칙(rule_auditor). `prompts/intake/v1.yaml` 신규 — 실명세 'LLM 2단계' 중 1차(읽기 전용) 프롬프트, B6 Vision 배선 대기. **실키 후 골든셋 실측으로 튜닝 시작점** |
| `기획/업무분장_스프린트1_작업명세_v3_초안.md` | **(07-15)** 리포 밖 — 실명세 정합(N1~N6) 반영 + 사용자=프롬프트·평가·관측 축 배정. 팀 리뷰 대기 |
| `app/schemas/callback.py` | **(07-15)** camelCase 직렬화(`alias_generator=to_camel`) + `suggested_category`/`processed_by` 추가 — bravo_API명세서 API-045 정합 |
| `app/middleware/pii_masker.py` | `mask_names()` 실명→역할 치환 |
| `app/mcp_server.py` | FastMCP, `mcp.settings.streamable_http_path="/"`로 `/mcp` 마운트. lifespan에서 `mcp_session_manager()` 필요 |
| `app/eval_support.py` | `run_golden_set()` — CLI와 `GET /v1/eval/golden` 공유. Trajectory 채점 + CSV 출력(`export_results_csv`) |
| `app/static/dashboard.html` | /ui 대시보드. **id 중복 주의** (아래 §7) |
| `app/run_api.py` | Windows 전용 런처 — `asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)` |
| `templates/category_catalog.yaml` | **팀 확정** 유형 5종×카테고리 6개 + keywords + fallback |
| `templates/policy_templates.yaml` | 유형별 base_rules + auto_approve_ratio (categories는 제거됨) |
| `reference_docs/*.txt` (5개) | PolicyDrafter RAG 참고 문서 — **실제 기관 원문 아님, 관행 조사 후 재구성** (README에 명시) |
| `eval/golden/golden_v1.json` | 골든셋 30건 + `expected_gate_includes`(Trajectory 라벨 23건) |
| `eval/run_eval.py` / `eval/analysis.ipynb` | 회귀 CLI / 분석 노트북 |
| `eval/golden/writers_golden_v1.json` | **(07-15)** 라이터 골든셋 17건. expect 규칙: `*_contain`/`*_not_contain`=부분 문자열, 그 외=동등 비교 |
| `app/eval_writers.py` | **(07-15)** 라이터 평가 러너 — `run_writers_golden_set()`, `evaluate_expectations()` 순수 함수, CSV(`writers_golden_run.csv`). CLI(`eval/run_eval_writers.py`)와 `GET /v1/eval/writers`가 공유 |
| `scripts/seed_reference_corpus.py` | 참고 문서 인덱싱 (멱등, DB 필요) |
| `scripts/seed_demo.py` | 4주 시뮬레이션 — 에스컬레이션 100%→33%→25%→0% (데모 핵심 그래프) |
| `scripts/smoke_review.py` / `smoke_mcp.py` | 스모크 |
| `scripts/stress_idempotency.py` | **(07-15)** 동시 중복 제출 멱등성 실증 — API·워커 떠 있어야 함 |

## 4. 핵심 결정사항 (왜 이렇게 만들었나)

- **판단은 LLM, 숫자·최종 통제는 코드**: 금액 계산·가드레일·검증은 전부 순수 함수.
  LLM 출력이 목록 밖이면 코드가 교정. 프롬프트 인젝션으로 뚫을 수 없는 구조가 세일즈 포인트.
- **목 모드 우선 개발**: 키·백엔드 없이 전체 배관을 완성/검증하고, 실키는 마지막에 스위치만.
  `chat_structured(..., mock_response=X)` 패턴 — 모든 LLM 호출 지점에 목 응답 필수.
- **팀 확정 사항들**: ① 예산 = 모임 총액 하나 (잔액=총예산−승인지출합, 카테고리는 표시용)
  ② 카테고리 동적 추가 금지(백엔드 DB 우려) — 유형별 고정 6개, yaml로만 관리
  ③ 회칙 입력 3경로(파일업로드/직접입력은 **원문 무수정** 인덱싱, AI초안·건너뛰기는 동일
  생성 경로 — 차이는 미리보기 여부, 팀 최종확정 대기) ④ 영수증은 추출 텍스트(receipt_text)
  수신 방향 ⑤ **챗봇은 MVP 제외** (시간 남으면 확장)
- **업로드/직접입력 회칙을 LLM으로 재작성하지 않기로 결정**: 수치·조건 변형 위험 때문.
  4단계 청킹이 형식 문제를 흡수.
- **에이전트는 1개, 데이터가 팀별**: "모임마다 에이전트 생성"의 실체는 모든 조회의
  team_id 하드필터. 전 쿼리 `WHERE team_id=` 강제 (멀티테넌시).
- **정직한 상태 표기**: 다이어그램·README에 구현됨/예정 구분, RAG 문서 출처의 한계 명시.
  발표 때 "실제 규정 원문을 넣었다"고 말하면 거짓 — "관행 조사 후 재구성한 시드,
  실서비스에선 교체 가능" 프레이밍 사용.
- **PolicyDrafter만 동기 API** (마법사 UX): §2.2 "LLM 호출은 워커만" 원칙의 유일한 예외.
- **모델 라우팅**: `models.yaml` — 판단=gpt-4o, 분류·요약=gpt-4o-mini, embeddings=text-embedding-3-small.
- **프롬프트**: `prompts/{agent}/{version}.yaml`, 판정마다 PROMPT_VERSION 태깅.

## 5. 알려진 이슈 / 미결

- **카테고리 오선택 미검증**: 사용자가 교재 구입을 "식비"로 선택해도 그대로 승인됨
  (의도된 동작 — 승인은 카테고리 안 봄). 관리자 사유에 "카테고리 재확인" 참고 메모를
  넣을지 팀 논의 중, **사용자 답변 대기**. 재현: /ui에서 아무 지출이나 카테고리만 엉뚱하게.
- **Docker Desktop dockerInference 잠김 (3회 발생 — 최근 2026-07-16)**:
  `C:\Users\user\AppData\Local\Docker\run\dockerInference` 파일이 커널 레벨로 잠겨
  Docker가 안 뜸. **어떤 삭제 방법도 안 통함 — 재부팅만이 해결책.**
  증상: "The file cannot be accessed by the system" / `ls`에서 `-?????????` 표시.
  이것 때문에 pull 모델 재설계(§0-2)의 골든셋 E2E 재실행이 재부팅 대기 중.
- **목 임베딩은 의미 없음**: 해시 기반이라 회칙이 인덱싱된 팀에서 rule_auditor가 거의 항상
  "근거 불충분(insufficient)"→escalate. 실키 후 `RELEVANCE_MAX_DISTANCE=0.5` 임계값 재조정 필요.
- **hankyung-docker는 별개 프로젝트**: `C:\Users\user\hankyung-docker` (강의 실습).
  `settings.py`의 `Settings` → `Settings()` 오타 수정 + 포트 8000→8001 변경해줬음. BudgetOps와 무관.

## 6. 남은 작업 (우선순위 순)

0. ~~재부팅 후 골든셋 E2E 재실행~~ — **완료(2026-07-16)**: 골든셋 30/30·오승인 0,
   스트레스 테스트 통과. §0-2 참고.
1. **실 OpenAI 키 전환 — 완료(2026-07-20)**. ①골든셋 실측 ②임계값 조정(0.65)
   ⑤Vision까지 완료. **골든셋 실모드 1차 실측 결과(§0-3 참조): 19/30=63.3%,
   오승인 0건(하드 게이트 유지!), 건당 $0.005.** 실패 11건 전부 approve/reject→
   escalate(안전 방향 편향). 원인: 목 회칙 텍스트가 골든 시나리오 카테고리
   (홍보·비품·대관 등)를 안 다뤄 rule_auditor가 '조항 없음→애매(warn)'→
   rule_ambiguous escalate. **튜닝 3회전 완료(2026-07-20, 전부 오승인 0)**:
   1차 63.3%(v1·회칙4조) → 2차 80.0%(회칙 11조 확장 + 하니스 목 판례 사전 정리)
   → **3차 93.3%(프롬프트 v2)**. v2 변경점: rule_auditor — pass/warn/fail 결정
   규칙 명확화('인정 조항 있으면 세부 미명시여도 pass', 예산은 역할 밖) /
   adjudicator — 잔액 부족 reject_candidate는 수치 명확 시 확신 반려(0.85+) +
   반려 few_shot 추가. **v2 재현 확인(90.0%) 후 기본값 승격 완료**
   (prompts.py DEFAULT_VERSIONS — env 오버라이드는 계속 우선). 추가로 가드레일
   정책 신설: '회칙 애매 단독 + 예산 부족 명확 → 반려 후보'(반려는 안전 방향,
   adjudicate 백스톱 — 순수 함수 테스트 3건). **6차 최종 100.0%(30/30), 6회전 내내
   오승인 0.** 추이: 63.3→80.0→93.3→90.0(재현)→96.7→**100.0**. 6차 변경:
   ① temperature=0 고정(심사 재현성 — 편차 케이스 해소의 본질) ② rule_auditor/v3
   (연 한도 조항은 '제공된 정보만으로 — 누적 미제공 시 이번 청구만 비교' +
   해당 few_shot). v3 승격 완료(DEFAULT_VERSIONS).
   CSV: eval/results/golden_realmode_*.csv. **실모드 하니스 정식화 완료
   (`eval/run_eval_real.py` — Sprint 2 선행)**: 6회전 절차 전부 코드화, 오승인>0이면
   exit 1. **골든셋 v1.1(42건, 신규 12건 포함) 실모드 42/42=100% (2026-07-20,
   $0.30)** — noauto 게이트·경계 정밀·복합 불일치·자동 분류까지 실 LLM 검증.
2. **백엔드 계약 반영**: 필드명·Swagger 받으면 `app/schemas/`와 `backend_client.py`의
   URL·필드명만 교체 (노드 코드 불변이 설계 의도). camelCase면 Pydantic alias 사용.
3. **LangSmith 연동 — 완료 (개발자 B, B-4, 커밋 5c8d4ff `app/observability.py`)**: 트레이싱 배선·
   C9 태깅 형식 정의 완료. CI 게이트 연동은 Sprint 2.
4. **골든셋 확장 — 완료 (2026-07-15)**: 라이터 3종 시나리오 골든셋 17건 추가, 17/17 통과.
   실키 전환 후 LLM 생성 문구 기반 케이스(현재는 목 휴리스틱 기준) 재검토 필요.
5. **동시요청·멱등성 스트레스 테스트 — 완료 (2026-07-15)**: 같은 expense_id의
   활성(queued/running) 심사 잡은 1개만 생성 — `uq_jobs_active_review` 부분 유니크
   인덱스(DB 레벨 보장) + `insert_job(dedupe_active=True)` 멱등 수락(기존 job_id 반환).
   완료 후 재제출은 새 잡(재심사 허용). `scripts/stress_idempotency.py`로 실증
   (동시 20건→잡 1개, 대조군 5건→5개, 도커 스택 상대로 통과).
6. **참고 코퍼스 확장**: 유형당 1→2~3개 문서. 실키로 검색 품질 실측 후 판단.
7. **팀 저장소 push**: 원격 미연결 상태. GitHub Organization + 별도 리포 권장(모노리포 아님),
   main 직push 말고 `feature/llm-server-skeleton` 브랜치→PR로.
8. 시연 영상·PPT (5~6주차). 다이어그램 3종은 클로드 아티팩트에 있음
   (PDF 사본: `기획/회칙생성_에이전트_파이프라인_v1.pdf`).

## 7. 주의할 점 (했던 실수·함정)

- **반드시 `llm-server` 폴더 안에서 명령 실행** — 부모 폴더(`final project`)에서 `uv run`
  하면 uv가 pyproject를 못 찾고 **Python 3.14로 임시 venv를 새로 만들어버림** (실제 발생).
- **Windows 이벤트 루프**: psycopg 비동기는 ProactorEventLoop 비호환. API는 반드시
  `python -m app.run_api`(uvicorn 직접 실행 금지), worker는 `__main__`에서
  WindowsSelectorEventLoopPolicy 설정돼 있음. 새 스크립트 만들 때도 항상
  `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` 필요.
- **콘솔 한글 깨짐**: cp949 문제. 스크립트에 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
  + 실행 시 `PYTHONIOENCODING=utf-8`. curl로 한글 JSON 보낼 땐 **파일로 저장 후
  `--data-binary @file`** (인라인 -d는 인코딩 깨져 422).
- **matplotlib 한글**: `mpl.rc("font", family="Malgun Gothic")` 없으면 그래프 한글이 네모.
- **HTML id 중복 버그 (실제 발생)**: dashboard.html에서 `rv-category`를 input과 결과 div에
  중복 사용 → getElementById가 input을 잡아 결과가 조용히 안 보임. 새 요소 추가 시 id 확인.
- **코드 수정 후 프로세스 재시작 필수**: uv 실행 중인 API/워커는 코드 반영 안 됨(리로드 없음).
  Docker는 `up --build` 재빌드 필요. "고쳤는데 안 바뀌어요"의 원인 1순위.
- **포트 8000 충돌**: llm-api(로컬이든 도커든)와 다른 프로젝트(hankyung은 8001로 옮겨둠),
  로컬 uv API와 도커 API 동시 실행 불가.
- **골든셋/데모 팀 id 규약을 깨지 말 것**: `lowbudget` 포함=잔액부족, `club/study/social/hobby/company`
  포함=유형 추론, `noexpense` 포함=지출 이력 없음, `balanced` 포함=편중·저활용 없는 균형 이력
  (뒤 2개는 07-15 라이터 골든셋용 추가). 목 규약이 테스트 결정성의 기반.
- **AGENT 자기 판례는 위험 신호에서 제외** (자기 오염 루프 방지) — precedent_auditor 수정 시 유지할 것.
- **판례 검색 쿼리도 마스킹 필수**: 저장본이 마스킹돼 있으므로 `masked_claim_summary()` 사용.
  실명으로 검색하면 유사도가 어긋남 (실제 버그였음).
- **`eval/run_eval.py`와 `seed_*.py`는 DB 필요** — llm-postgres(포트 5433) 먼저 기동.

## 8. 다음 세션에서 바로 실행할 명령어

```powershell
# 0. 위치 (반드시!)
cd "C:\Users\user\final project\llm-server"

# 1. DB (Docker Desktop 켜져 있어야 함 — 안 뜨면 §5의 dockerInference 이슈, 재부팅)
docker compose up -d llm-postgres

# 2-A. 로컬 개발 모드 (코드 수정하며 작업할 때) — 터미널 2개
uv run --active python -m app.run_api     # 터미널 1 (API, http://localhost:8000)
uv run --active python -m app.worker      # 터미널 2 (워커)

# 2-B. 또는 도커 전체 스택 (배포 검증용 — 2-A와 동시 실행 불가, 포트 충돌)
docker compose up --build -d
docker compose logs -f llm-api            # 로그 확인
docker compose down                        # 내리기

# 3. 검증 루틴 (코드 고칠 때마다)
uv run ruff check app tests scripts
uv run pytest -q                           # 70 passed 기대
uv run python eval/run_eval.py             # 30/30, Trajectory 23/23, 오승인 0 기대
uv run python eval/run_eval_writers.py     # 라이터 골든셋 17/17, 검증 불통과 0 기대

# 4. 데모·시드 (필요시, 멱등)
uv run python scripts/seed_reference_corpus.py   # PolicyDrafter RAG 코퍼스 35청크
uv run python scripts/seed_demo.py               # 에스컬레이션 감소 데모 (demo-growth 팀)

# 5. 눈으로 확인
# 브라우저: http://localhost:8000/ui   (토큰: dev-service-token-change-me, 자동 입력됨)
# API 문서: http://localhost:8000/docs
uv run python scripts/smoke_mcp.py               # MCP 확인

# 6. 실키 받은 날 (TODO #1)
# .env 열어서: OPENAI_API_KEY=sk-... 넣고 MOCK_LLM=false 로 변경 → API·워커 재시작
# → uv run python eval/run_eval.py 로 실 LLM 첫 성적 확인부터
```
