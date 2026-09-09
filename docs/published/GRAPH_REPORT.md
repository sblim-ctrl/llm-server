# Graph Report - test_set-extension  (2026-09-09)

## Corpus Check
- 400 files · ~358,306 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3070 nodes · 6943 edges · 164 communities (130 shown, 18 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 391 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Settings & DB Pool
- Analyze & Briefings API
- Eval Metrics & SSE Stream
- Digest Writer
- Policy Wizard Step 2
- Category Classifier
- Precedents & MCP Server
- Guardrail Gate
- Worker Job Queue
- HITL Escalation
- Dashboard Summary
- Reviews SSE Stream
- Worker Recovery
- Golden Set v2 Generator
- Budget Planner Writer
- Review Graph & Budget Auditor
- Policy Draft Writer
- Keyword Classifier
- Prompt Loader
- Document Parser
- Rule Amendment Writer
- Callback Payload
- Checkpointer Setup Tests
- Budget Figures & Proposal
- API Endpoint Catalog
- Load Context & Backend Client
- Pull Model Analyze Contract
- Intake Receipt (Vision)
- Report Writer
- Adjudicator
- Eval Judge
- Policy Draft Request
- Policy Templates
- Backend Client Normalization
- Policy Draft Validation
- Banned Terms Scanner
- Briefing Writer
- Budget Planner Graph
- Docker Compose Services
- Eval API Endpoints
- Health Check Endpoints
- Categories API
- Receipt Intake & Default Policy
- Mock Fixture Consistency
- Job Polling & Term Translation
- Writer Golden Eval
- Default Policy Audit
- Rule Auditor (RAG)
- Backend Contract Verifier
- Rule Auditor Receipt Facts
- Policy Draft Clause Rules
- LLM Client
- Policy Proposals
- Indexing Upsert Tests
- Deploy Contract Verification
- Proposals API
- Rule Auditor Design Principles
- Bylaw Amount Rounding
- Rule Text Chunking
- Dashboard Writer
- Architecture Concepts (Design Doc)
- API Query Param Boundaries
- Indexing Pipeline Graph
- Precedent Auditor & Judge Prompts
- Burn Rate Forecast
- Architecture ADRs (Design Doc)
- Policy Draft API
- Budget Calculator
- Backend Spec Reconciliation Notes
- Figma Screen Dump
- Auth Middleware
- Guardrail Real Config Tests
- Precedents API Contract
- Dashboard Schemas
- Backend Pending Items
- Backend Spec Review Requests
- Eval Dataset Export
- Dashboard Summary API
- Receipt Text Parsing
- Default Policy Rules
- v1.2 Conditional Track Notes
- Budget Proposal API
- PII Masker
- Policy Document Fetch
- Adjudicator Prompt Cross-Refs
- Briefing Writer Prompt Cross-Refs
- Deploy & Backend Gaps
- Context Status API
- Execute Decision
- Screen vs Callback Field Audit
- Automation Boundary Risk Review
- Golden Receipt Image Generator
- Claude
- T11 반영사항 2026 08 06
- 골든셋 목 규약 재설계안 2026 08 04
- 프롬프트 브랜치 통합계획 2026 08 04
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Readme
- Trajectory Gate Derivation
- Send Callback Retry
- Golden V2 Report
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Readme
- 풀스택 회신 반영 2026 08 04
- 작업리스트 배포전 2026 08 04
- Models
- Progress
- Progress
- Policy Draft
- 백엔드 회신 초안 2026 08 10
- 풀스택 협의 2026 08 04 반영
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Progress
- Stress Idempotency
- Drafts
- Budget Planner
- V3
- Auth
- Request Log
- Conflict Rules V1
- Progress
- Make Report Charts
- Env
- 0001 Initial Schema
- V3
- Dump Openapi
- Budget Planner
- Gate
- Api Query Params
- Run Api
- Format
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Export Golden Csv
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Auth Middleware
- Auth Middleware
- Auth Middleware
- Digest
- V6
- 백엔드 요구 내부api 명세
- 백엔드 요구 내부api 명세
- 백엔드 요구 내부api 명세
- 백엔드 요구 내부api 명세
- Llm팀 아키텍처 워크플로우 설계서 V1.1
- Models
- Pyproject
- Progress
- Progress

## God Nodes (most connected - your core abstractions)
1. `Opinion` - 86 edges
2. `get_settings()` - 77 edges
3. `ExpenseClaim` - 76 edges
4. `load_prompt()` - 65 edges
5. `ReceiptData` - 51 edges
6. `evaluate_guardrails()` - 49 edges
7. `ReviewState` - 49 edges
8. `get_pool()` - 48 edges
9. `classify_category()` - 45 edges
10. `open_pool()` - 41 edges

## Surprising Connections (you probably didn't know these)
- `RuleAuditor 프롬프트 v7` --references--> `receipt_facts_block()`  [INFERRED]
  prompts/rule_auditor/v7.yaml → app/graphs/review/nodes/rule_auditor.py
- `RuleAuditor 프롬프트 v7` --references--> `_search_text()`  [INFERRED]
  prompts/rule_auditor/v7.yaml → app/graphs/review/nodes/rule_auditor.py
- `Adjudicator Prompt v1` --references--> `AdjudicationResult`  [EXTRACTED]
  prompts/adjudicator/v1.yaml → app/graphs/review/nodes/adjudicate.py
- `DashboardWriter v1 프롬프트 — 대시보드 AI 요약` --references--> `verify_summary_pure()`  [EXTRACTED]
  prompts/dashboard_writer/v1.yaml → app/graphs/writers/dashboard.py
- `DashboardWriter v2 프롬프트 — 수치 과장 표현 차단` --references--> `verify_summary_pure()`  [EXTRACTED]
  prompts/dashboard_writer/v2.yaml → app/graphs/writers/dashboard.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **escalation_threshold→confidence_threshold 오매핑 버그 계열 (3개 문서에서 독립적으로 발견·수정 추적)** — docs_internal_pulseutaek_munseo_banyeongsahang_2026_07_27_immediate_fix_3, docs_internal_baekendeu_daegi_hangmok_jeongli_3_bugs_not_reflected, docs_internal_hwamyeon_daejo_2026_07_29_followup_0731_step2_gap [INFERRED 0.85]
- **cowbro·sblim 브랜치 통합 조율 문서군 (골든셋 재설계·프롬프트 충돌·발산표·배포전 선행조건이 공통으로 겨냥)** — docs_internal_goldenset_mok_gyuyak_jaeseolgyean_2026_08_04_order_correction_branch_first, docs_internal_peurompteu_beuraenchi_tonghap_gyehoek_2026_08_04_integration_order_8steps, docs_internal_jageopliseuteu_baepojeon_2026_08_04_0_prereq_3items, docs_internal_simsa_gyeonggye_geomto_hoesin_2026_08_04_e5_branch_divergence [INFERRED 0.85]
- **카테고리 9종 통일 흐름 — ENUM 교집합0 발견부터 확정·매핑·xlsx반영까지** — docs_internal_pulseutaek_munseo_banyeongsahang_2026_07_27_new_issues_tier1_3, docs_internal_pulseutaek_hyeobui_2026_08_04_banyeong_item6_category_9_unify, docs_internal_pulseutaek_hoesin_banyeong_2026_08_04_category_mapping_gap, docs_internal_t11_banyeong_sahang_2026_08_06_category9_xlsx_notion, docs_internal_baekendeu_myeongseseo_geomto_hoesinyocheong_2026_08_10_a2_category_enum [INFERRED 0.85]
- **백엔드 내부 조회 API 8종 계약** — internal_api_expense_detail, internal_api_team_settings, internal_api_budget, internal_api_receipt_image, internal_api_policy_document, internal_api_team_profile, internal_api_team_members, internal_api_expense_history [EXTRACTED 1.00]
- **모임 유형별 정책 템플릿 + 참고 회칙 자료군** — templates_policy_templates, reference_docs_동아리_재정운용_참고, reference_docs_동호회_운영_참고, reference_docs_스터디_운영_참고, reference_docs_친목모임_회칙_참고, reference_docs_회사_복리후생_경조사비_참고 [INFERRED 0.85]
- **LLM 서버 배포 문서 세트(역할 분담)** — docs_llm_deploy_llm팀_배포방안_2026_08_06, docs_llm_deploy_배포_실행순서_2026_08_07, docs_llm_deploy_t8_배포체크리스트_2026_08_07, docs_llm_deploy_배포_작업_매뉴얼, docs_llm_deploy_t2_track3_실행매뉴얼_2026_08_10 [EXTRACTED 1.00]
- **병렬 3-심사관 Fan-out/Fan-in 패턴** — llm_v1_1_ruleauditor, llm_v1_1_budgetauditor, llm_v1_1_precedentauditor, llm_v1_1_adjudicator, llm_v1_1_guardrail_gate [EXTRACTED 1.00]
- **판례 학습 루프 — 이중 학습 회로 (심사 재사용 + 회칙 개정 피드백)** — llm_v1_1_판례학습루프, llm_v1_1_precedentauditor, llm_v1_1_briefingwriter, llm_v1_1_policydrafter [EXTRACTED 0.90]
- **Pull 모델 재설계 — bravo 문서 발견→스키마 변경→백엔드 함수 신설** — progress_bravo_arch_doc, progress_pull_model_redesign, progress_analyzerequest, progress_backend_client_functions [EXTRACTED 0.90]
- **사용자 입력 지시문 무시 규칙 (프롬프트 인젝션 방어 패턴)** — prompts_adjudicator_v6_prompt, prompts_briefing_writer_v4_prompt, prompts_budget_planner_v3_prompt [INFERRED 0.85]
- **수치는 코드, LLM은 문구만 — mini 모델 경제성 패턴** — models_digest_writer, models_dashboard_writer, models_budget_planner [EXTRACTED 0.90]
- **A/B 실측 기반 DEFAULT_VERSIONS 승격 메커니즘** — app_llm_prompts_default_versions, prompts_classifier_v2_prompt, prompts_classifier_v7_prompt, prompts_classifier_v8_prompt, prompts_intake_v2_prompt [INFERRED 0.85]
- **'규칙보다 예시가 세다' 반복 결함 패턴** — concept_few_shot_beats_rules, prompts_classifier_v4_prompt, prompts_dashboard_writer_v2_prompt, prompts_default_policy_v3_prompt, prompts_intake_v3_prompt [EXTRACTED 1.00]
- **정합 수정 vs A/B 승격 구분 (classifier v6 전례)** — concept_consistency_fix_vs_ab_promotion, prompts_classifier_v6_prompt, prompts_dashboard_writer_v4_prompt, prompts_default_policy_v2_prompt [EXTRACTED 1.00]
- **카테고리 카탈로그 전역 9종 정합 수정 그룹** — prompts_query_rewriter_v2_prompt, prompts_precedent_auditor_v4_prompt, prompts_report_writer_v3_prompt, templates_category_catalog [EXTRACTED 1.00]
- **Judge 프롬프트 자기 캘리브레이션 계보(v1→v2→v3)** — prompts_judge_v1_prompt, prompts_judge_v2_prompt, prompts_judge_v3_prompt [EXTRACTED 1.00]
- **PolicyDrafter 한도 금액 인용 방식 단계적 정교화(v4→v5→v6)** — prompts_policy_drafter_v4_prompt, prompts_policy_drafter_v5_prompt, prompts_policy_drafter_v6_prompt [EXTRACTED 1.00]
- **RuleAuditor 프롬프트 버전 계보 (v1~v7)** — prompts_rule_auditor_v1_prompt, prompts_rule_auditor_v2_prompt, prompts_rule_auditor_v3_prompt, prompts_rule_auditor_v4_prompt, prompts_rule_auditor_v5_prompt, prompts_rule_auditor_v6_prompt, prompts_rule_auditor_v7_prompt [EXTRACTED 1.00]
- **RuleAmendment 프롬프트 버전 계보 (v1~v3)** — prompts_rule_amendment_v1_prompt, prompts_rule_amendment_v2_prompt, prompts_rule_amendment_v3_prompt [EXTRACTED 1.00]
- **RuleAuditor 전 버전이 공유하는 Opinion 출력 계약** — prompts_rule_auditor_v1_prompt, prompts_rule_auditor_v2_prompt, prompts_rule_auditor_v3_prompt, prompts_rule_auditor_v4_prompt, prompts_rule_auditor_v5_prompt, prompts_rule_auditor_v6_prompt, prompts_rule_auditor_v7_prompt, app_schemas_common_opinion [EXTRACTED 1.00]

## Communities (164 total, 18 thin omitted)

### Community 0 - "Settings & DB Pool"
Cohesion: 0.05
Nodes (78): get_settings(), 환경 설정 — .env 로드 (pydantic-settings)., Settings, apply_schema(), _apply_schema_unlocked(), close_pool(), open_pool(), psycopg3 비동기 커넥션 풀 + 잡 테이블 헬퍼 (ADR-4). (+70 more)

### Community 1 - "Analyze & Briefings API"
Cohesion: 0.06
Nodes (50): create_analyze_job(), post, POST /v1/analyze — 심사 잡 수락 (202). LLM 호출 없음 — 그래프 실행은 워커 몫 (§2.2). pull 모델…, 지출 1건의 AI 심사를 요청한다. **즉시 202로 접수만 하고 심사는 비동기 실행**된다. **pull 모델** — 요청에는 5필드만…, create_briefing_job(), post, POST /v1/briefings — 인수인계 브리핑 잡 생성 (§7.2). 결과는 GET /v1/jobs/{id}., post (+42 more)

### Community 2 - "Eval Metrics & SSE Stream"
Cohesion: 0.07
Nodes (58): 그래프 updates 스트림 → SSE 이벤트 제너레이터 (최초 실행·재개 공용). interrupt를 만나면 paused를 내고 끝낸다.…, _stream_run(), automation_rate(), category_metrics(), confusion_matrix(), per_class_prf(), _prf(), Any (+50 more)

### Community 3 - "Digest Writer"
Cohesion: 0.08
Nodes (57): aggregate(), aggregate_digest_pure(), build_digest_graph(), detect_anomalies_pure(), DigestDoc, DigestFigures, DigestState, fetch() (+49 more)

### Community 4 - "Policy Wizard Step 2"
Cohesion: 0.06
Nodes (53): BigIntQuery, get, 승인 정책 반영 상태 — 마법사 2단계 확인용. `/context/status`(3단계 회칙 반영 확인)와 같은 이유로 있다. 2단계는 저장이…, 2단계에서 저장한 값이 실제 심사에 어떤 기준으로 적용되는지 돌려준다. 마법사 2단계나 관리자 설정 화면에서 저장 직후 호출해…, read_policy_params_status(), PolicyParams, 팀별 심사 파라미터 — 관리자 설정 (team_settings에서 load_context가 채움)., PolicyParamsStatus (+45 more)

### Community 5 - "Category Classifier"
Cohesion: 0.07
Nodes (58): CategoryPrediction, classify_category(), CLASSIFY_MIN_CONFIDENCE (분류 채택/폐기 임계값, 0.8), BaseModel, 지출 카테고리를 AI가 정한다 — **항상 실행된다** (T7, 2026-08-06). 종전에는 `claim.category`에 값이 있으면…, DEFAULT_VERSIONS (에이전트별 기본 프롬프트 버전 레지스트리), app/llm/prompts.py (PROMPT_VERSION_{AGENT} 환경변수 → DEFAULT_VERSIONS → v1 해석기), ExpenseClaim (+50 more)

### Community 6 - "Precedents & MCP Server"
Cohesion: 0.07
Nodes (45): create_precedent(), post, POST /v1/precedents — 관리자 결정 수신 → 판례 저장 (REQ-042 학습 루프의 입구). 에스컬레이션된 건을 관리자가…, precedent_auditor(), precedent_auditor — 판례·이상탐지 심사관 (병렬). search_precedents로 유사 판례를 실제 검색해 소견에 인용한다…, embed_texts(), 임베딩 생성. 목 모드면 결정적 목 벡터를 반환 (§4.4-a 인덱싱 파이프라인)., get_budget_status() (+37 more)

### Community 7 - "Guardrail Gate"
Cohesion: 0.08
Nodes (52): evaluate_guardrails(), Opinion, 심사관 1명의 소견 — opinions 딕셔너리의 값., RuleAuditor 프롬프트 v1, RuleAuditor 프롬프트 v2, 마법사 2단계 구간표가 실제 가드레일과 맞는지 전수 확인. 화면 표: 소액(5만 미만) AI 자동 승인 / 중간(5~20만) 대기·자동 /…, _ok_opinions(), parametrize (+44 more)

### Community 8 - "Worker Job Queue"
Cohesion: 0.07
Nodes (50): claim_next_job(), finish_job(), get_context_status(), get_job(), get_pool(), Any, 내부 UUID 또는 백엔드 발급 jobId(external_job_id) 어느 쪽으로도 조회 가능 — 백엔드 폴링 fallback은 자기가…, 팀의 활성 회칙 인덱스 요약 — 조항 수·버전·인덱싱 시각. 인덱싱 이력이 없으면 chunk_count 0에 나머지는 None으로… (+42 more)

### Community 9 - "HITL Escalation"
Cohesion: 0.07
Nodes (52): describe_rules(), escalate(), _escalation_detail(), 요청자용 에스컬레이션 사유 — 트리거 종류별 5종. 내부 수치·LLM 원문은 담지 않는다 (요청자에게 승인/반려로 오인될 수 있는 문구를…, 가드레일 규칙 목록 → 관리자가 읽는 한 줄 (순수 함수). 종전에는 `", ".join(triggered_rules)`라 관리자 화면에…, _requester_message(), GateResult, guardrail_gate(순수 함수) 출력 (§3.3 1단계). (+44 more)

### Community 10 - "Dashboard Summary"
Cohesion: 0.08
Nodes (51): allowed_money(), 본문에 나와도 되는 금액 표기. 집계값에서만 유도한다., 요약문의 수치가 집계에서 나온 것인지 대조한다. 문장 자체는 강제하지 않는다 — 실모드 LLM이 자유롭게 다듬는 영역이다. 다만 **숫자는…, verify_summary_pure(), DashboardSummaryDoc, _doc(), _figures(), 대시보드 AI 요약 (풀스택 협의 2026-08-04 5번). 집계는 순수 함수라 그대로 검증하고, 요약문은 '수치가 집계에서만 나왔는가'를… (+43 more)

### Community 11 - "Reviews SSE Stream"
Cohesion: 0.07
Nodes (41): DecisionRequest, BaseModel, post, 심사 그래프를 직접 실행하며 노드 진행을 SSE로 중계 (HITL 데모·관측 전용)., 재개 잠금 해제 — 어떤 예외도 밖으로 흘리지 않는다. 연결이 닫히면 세션 잠금은 함께 풀리므로 unlock 실패는 치명적이지 않다. 여기서…, 관리자 결정으로 멈춘 심사를 재개 — 콜백·판례 저장(ADMIN)까지 SSE 중계. 확인("대기 중인가")과 실행(그래프 재개) 사이를…, _release_resume_lock(), resume_review() (+33 more)

### Community 12 - "Worker Recovery"
Cohesion: 0.07
Nodes (41): handle_job(), _meta_totals(), poll_loop(), 그래프 final_state의 llm_meta(dict[str, LLMCallMeta]) 합산 — B-7 잡 비용 계측. llm_meta를…, review 잡이 dead로 전환됐을 때 ESCALATED fail-safe 콜백 발송 (§8). 합집합 (7/20 팀 합의 ②): ·…, (잡 결과, 그래프 final_state) 반환 — final_state는 llm_meta 합산(B-7)용., run_review_job(), _send_review_failsafe() (+33 more)

### Community 13 - "Golden Set v2 Generator"
Cohesion: 0.10
Nodes (33): main(), 골든셋 v2 결정적 생성기 — 7유형 원안 + receipt_mismatch(8번째, Phase 0 커버리지 갭 보강) × 약 100건 =…, build_case(), Any, 골든 v2 케이스 딕셔너리 빌더 — eval/golden/golden_v1.json과 같은 필드 모양 + v2 신규…, 골든 v2 생성기 공용 상수 — 카테고리 힌트·팀 유형·정책 기본값. templates/category_catalog.yaml(9종 키워드)과…, evaluate(), ExpectedOutcome (+25 more)

### Community 14 - "Budget Planner Writer"
Cohesion: 0.09
Nodes (48): allowed_money(), 본문에 나와도 되는 금액 표기. 집계값에서만 유도한다., 3블록의 수치·카테고리가 집계에서 나온 것인지 대조한다. 문장 자체는 강제하지 않는다 — 해석·패턴 진단·권고는 실모드 LLM이 자유롭게 쓰는…, verify_budget_message_pure(), _figures(), _msg(), BudgetPlanner 단위 테스트 — 순수 함수 + 목 모드 generate 노드 (DB 무접촉)., float 그대로 두면 검증기 허용 목록이 '6,210.5원'을 만들어 실제 표기와 어긋난다. (+40 more)

### Community 15 - "Review Graph & Budget Auditor"
Cohesion: 0.10
Nodes (37): build_review_graph(), 지출 심사 그래프 조립 (§4.1 메인 워크플로우). START → load_context → intake_receipt →…, budget_auditor(), budget_auditor — 예산 심사관 (병렬). 수치 계산은 코드(budget_calculator), LLM은 해석만. [팀 확인…, callback(), callback — 백엔드에 결과 전문 통보 (§7.2 콜백 스키마)., _admin_message(), _amount_context() (+29 more)

### Community 16 - "Policy Draft Writer"
Cohesion: 0.07
Nodes (46): _amounts_in(), _article_applies(), article_text(), build_policy_draft_graph(), dedupe_rules(), DraftState, drop_vague_rules(), effective_dues() (+38 more)

### Community 17 - "Keyword Classifier"
Cohesion: 0.06
Nodes (46): classify_by_keywords(), keyword_category_or_none(), 키워드가 실제로 적중한 경우에만 카테고리 반환 — 미적중이면 None. '기타' 재질의(classify_category)의 핵심 경로다…, 카탈로그 키워드 기반 결정적 분류 — 순수 함수. 미매칭 시 '기타'., _classify_with(), parametrize, 지출 카테고리 분류 — 전역 9종 (풀스택 협의 2026-08-04 확정). 모임 유형 축이 없어져 어떤 모임이든 같은 9개 중에서 고른다.…, 못 알아본 지출은 실제 카테고리에 섞지 않고 '기타'로 — 통계 오염 방지. (+38 more)

### Community 18 - "Prompt Loader"
Cohesion: 0.07
Nodes (38): classify_category — 지출 카테고리 자동 분류 (전역 9종, 풀스택 협의 2026-08-04). 카테고리는 **AI가 고정 9종…, _load(), load_prompt(), PromptSpec, BaseModel, 프롬프트 YAML 로더 (스프린트1 C3 계약) — `prompts/{agent}/{version}.yaml`. 버전의 진실 원천은 YAML…, few_shot이 있으면 system 뒤에 예시 블록을 조립해 반환., version 미지정 시 `PROMPT_VERSION_{AGENT}` 환경변수 → DEFAULT_VERSIONS → 'v1'. 환경변수 해석을… (+30 more)

### Community 19 - "Document Parser"
Cohesion: 0.09
Nodes (42): _detect_kind(), DocumentParseError, EmptyDocumentError, _extract_docx(), _extract_pdf(), extract_text(), Exception, 회칙 파일(PDF·Word) → 텍스트 추출 (T2, 회의 4번 결정). 마법사 3단계에서 관리자가 회칙 파일을 올리면 백엔드가 저장하고… (+34 more)

### Community 20 - "Rule Amendment Writer"
Cohesion: 0.11
Nodes (40): AmendmentState, AmendmentText, build_rule_amendment_graph(), detect(), draft_amendment(), _has_clusters(), _mock_amendment(), BaseModel (+32 more)

### Community 21 - "Callback Payload"
Cohesion: 0.10
Nodes (39): build_callback_payload(), ordered_opinions(), Any, 최종 처리 주체. 아직 처리자가 없으면 None. - 관리자가 직접 결정한 건(HITL 재개)은 ADMIN - AI가 승인·반려까지 끝낸 건은…, LLM 호출 계측 4종 — worker가 jobs.result에 남기는 관측값. 2026-08-03까지는 콜백 페이로드의 일부였다. 지출 상세…, 소견을 고정 순서로 정렬. 목록에 없는 키(향후 신설 심사관)는 뒤에 이름순으로., resolve_processed_by(), trace_meta() (+31 more)

### Community 22 - "Checkpointer Setup Tests"
Cohesion: 0.08
Nodes (31): _FakeCheckpointer, _FakeConn, _FakeCursor, _patch(), _patch_apply_schema(), apply_schema_locked·setup_checkpointer_locked — 다중 프로세스 동시 기동 직렬화 계약 (pool.py).…, setup이 죽어도 잠금은 풀린다 — 안 풀리면 다른 프로세스 기동이 영영 막힌다., unlock이 실패해도(연결 유실) setup 성공이 예외로 바뀌지 않는다 — 연결 종료가 세션 잠금을 함께 푼다. (+23 more)

### Community 23 - "Budget Figures & Proposal"
Cohesion: 0.08
Nodes (38): _allowed_dates(), BudgetFigures, BudgetMessage, ProposalText, BaseModel, LLM 산출은 문장만 — 수치는 코드(BudgetFigures)가 계산한다. Figma 확정 3블록., 소진 예상일만 허용한다. as_of·period_end까지 열면, 소진 예상이 없는 달에 LLM이 기간 말일을 소진일로 인용해도…, 프롬프트 v1·v2의 output_schema 이력 — **삭제 금지**. v3부터 산출은 BudgetMessage(3블록)로 바뀌었지만,… (+30 more)

### Community 24 - "API Endpoint Catalog"
Cohesion: 0.12
Nodes (38): POST /agent-callback, POST /v1/analyze, GET /v1/categories, POST /v1/context/refresh, GET /v1/context/status, POST /v1/digests, GET /v1/eval/golden, GET /v1/eval/writers (+30 more)

### Community 25 - "Load Context & Backend Client"
Cohesion: 0.11
Nodes (36): load_context — pull 모델 컨텍스트 로드 (bravo 설계서 TABLE 18, §4.2). 읽기 전용. 백엔드 심사 요청에는…, normalize_team_type(), 백엔드 표기 → 내부 표기. 모르는 값은 그대로 두어 Literal 검증이 거절하게 한다., approve_expense(), _client(), _fixture_expense(), _fixture_history(), _fixture_org() (+28 more)

### Community 26 - "Pull Model Analyze Contract"
Cohesion: 0.07
Nodes (37): load_context(), _budget_with_response(), /v1/analyze pull 모델 계약 테스트 (bravo 설계서 TABLE 18). - AnalyzeRequest: 백엔드…, 직접 그래프 호출(smoke·seed_demo·단위테스트) — 주입된 claim을 덮지 않는다., team_settings 조회 실패 → auto_approve=False (자동판정 권한 미확인이면 판정 금지)., get_context_status가 돌려준 활성 판번호가 그대로 state["rule_version"]에 실린다.…, team_settings.escalation_threshold는 금액 → force_escalation_amount.…, auto_approve_limit은 NULL 허용(자동승인 미사용 팀) — 예외 없이 0으로 처리. (+29 more)

### Community 27 - "Intake Receipt (Vision)"
Cohesion: 0.10
Nodes (34): detect_media_type(), intake_receipt(), _mock_receipt_from_url(), pdf_receipt_text(), intake_receipt — 영수증 OCR·정규화 (Intake 에이전트, REQ-028, A-6). 영수증 참조는 두 경로로 온다…, 영수증 바이트의 media type. 이미지면 문자열, PDF면 "application/pdf", 미상이면 None., PDF 영수증에서 텍스트 레이어를 뽑는다. 실패·스캔본이면 빈 문자열. 카드전표·전자영수증 PDF는 대부분 텍스트 레이어가 있어 Vision…, chat_structured_vision() (+26 more)

### Community 28 - "Report Writer"
Cohesion: 0.12
Nodes (35): aggregate(), aggregate_pure(), build_report_graph(), fetch_expenses(), generate_report(), _mock_report_text(), TypedDict, ReportWriter + 예산 추천 — 정산 리포트 AI 요약 (REQ-019, §4.4-c). 패턴: 수집 → 결정적 집계 → 생성(요약)… (+27 more)

### Community 29 - "Adjudicator"
Cohesion: 0.11
Nodes (33): adjudicate(), build_adjudication_user(), adjudicate — LLM 판정 합성 (§3.3 2단계). 가드레일 통과 건만 도달. confidence < threshold →…, 심사관 소견 → adjudicator user 메시지 (순수 함수). verdict·summary 외에 각 소견의…, route_after_adjudicate(), _precedent_lines(), 판례 인용 라인 (순수 함수) — (결정/결정주체) 표기로 ADMIN/AGENT·override를 노출. 프롬프트(v2+)의 "ADMIN…, _llm() (+25 more)

### Community 30 - "Eval Judge"
Cohesion: 0.11
Nodes (31): _digits(), judge_reasons(), JudgeResult, _mock_judge(), _opinion_numbers(), passes(), BaseModel, LLM-as-Judge — 심사 사유(reason) 품질 채점 (§4 Sprint 2). verdict 정확도는 골든셋이 채점하지만… (+23 more)

### Community 31 - "Policy Draft Request"
Cohesion: 0.09
Nodes (31): _mock_extra_rules(), 목 모드 휴리스틱 — 소개 문구 키워드 기반 추가 조항 제안. 소개 없으면 빈 목록., PolicyDraftRequest, model_validator, 마법사 1~3단계 통합 요청 (API 명세서 개정안 §1 — 회의 2·3·5번). 0단계(모임 생성)는 백엔드 별도 API — 여기는 그…, 문서 생성 에이전트 순수 함수 테스트 — 검증(Generator-Evaluator)·집계., 우리 템플릿이 정당하게 쓰는 표현은 걸리지 않아야 한다 — 좁게 잡은 이유., 백엔드 ENUM은 언더바 표기(2026-08-06 확정) — 경계에서 내부 표기로 접는다. 변환 없이는 템플릿·카탈로그 조회가 조용히 기본… (+23 more)

### Community 32 - "Policy Templates"
Cohesion: 0.08
Nodes (31): load_template(), load_templates(), parametrize, 소개가 없으면 LLM을 부르지 않고 유형별 회칙 조항만 나온다. 회사 유형은 dues_default=0이라 회비 조가 빠진다 — '회비 1인당…, 금지 조항을 '목적과 무관한 지출'만으로 쓰지 않는다 — 개인성 같은 확인 가능한 기준을 함께 둔다. 허용 조항은 열거식인데 금지가…, 유형별 기본 조 수가 표와 일치해야 한다., AI 맞춤 조항 상한도 유형별이다 — 종전에는 전 유형 10개 공통이었다., 기본 조 + AI 추가 상한이 18조를 넘지 않는다 (전 유형 공통 천장). (+23 more)

### Community 33 - "Backend Client Normalization"
Cohesion: 0.08
Nodes (30): _normalize_budget(), normalize_expense_category(), 지출 이력의 category를 전역 9종 중 하나로 접는다. 이미 9종이면 그대로 두고, 구 값이면 위 대응표로 옮긴다. 둘 다 아니면…, 예산 응답 키 흡수 — DB 표기(used_budget)·프론트 API 표기(usedBudget) 양쪽 수용. 어느 표기도 없으면…, parametrize, 공유 httpx 클라이언트 (성능 고도화) — 싱글턴·정리·재생성 동작 + 응답 키 정규화., 실모드 응답에 구 값이 섞여 와도 이력을 쓰는 네 곳은 9종만 본다., 상세도 이력과 같은 경계에서 접는다 — claim.category가 구 값으로 서지 않게. load_context가… (+22 more)

### Community 34 - "Policy Draft Validation"
Cohesion: 0.10
Nodes (31): _draft(), 문장부호·공백만 다른 사실상 같은 조항도 중복으로 잡는다., 템플릿에 모호어가 섞이면(우리 쪽 결함) 검증이 불통과시킨다., LLM 추가 조항이 설정 금액과 다른 금액을 말하면 불통과 — 회칙과 심사 기준이 갈라진다., 정당한 인용값은 사용자가 입력한 기준 금액 하나뿐이다., 옛 4배 에스컬레이션 금액은 더 이상 정당한 인용값이 아니다 (배수 계산식 폐기)., 자동'이라는 말 없이 관리자 확인으로 기준을 말해도 금액이 어긋나면 잡는다., 자동 심사와 무관한 조항의 금액(식비 한도 등)은 대조 대상이 아니다. (+23 more)

### Community 35 - "Banned Terms Scanner"
Cohesion: 0.13
Nodes (29): 사용자 노출 문자열에서 금지 용어를 찾는다 (순수 함수) — 위반 없으면 빈 리스트., 콜백 페이로드의 사용자 노출 텍스트(reasons·opinions) 전량 스캔., scan_banned_terms(), scan_callback_payload_terms(), _mock_result(), 판례 인용 문자열의 시스템 표기 접두만 한국어로 옮긴다 (순수 함수). 접두 뒤 본문("사유: ..." 포함)은 관리자가 원래 남긴 자유…, _translate_opinion_citations(), translate_precedent_citation() (+21 more)

### Community 36 - "Briefing Writer"
Cohesion: 0.16
Nodes (28): aggregate(), aggregate_precedents_pure(), BriefingState, build_briefing_graph(), fetch_precedents(), generate_briefing(), _mock_briefing_text(), TypedDict (+20 more)

### Community 37 - "Budget Planner Graph"
Cohesion: 0.12
Nodes (28): aggregate(), build_budget_figures(), build_budget_planner_graph(), CategoryShare, fetch(), generate_proposal(), _mock_budget_message(), PlannerState (+20 more)

### Community 38 - "Docker Compose Services"
Cohesion: 0.07
Nodes (30): FastAPI app object (app/main.py), Worker entrypoint module (app/worker.py), llm-api Service (uvicorn app.main:app), llm-postgres Service (pgvector/pgvector:pg16), llm-worker Service (python -m app.worker), pgdata Volume, gpt-4o model (input $2.50 / output $10.00 per 1M tokens), intake agent (Vision OCR) (+22 more)

### Community 39 - "Eval API Endpoints"
Cohesion: 0.11
Nodes (26): get_golden_eval(), get_writers_eval(), get, GET /v1/eval/golden · /v1/eval/writers — 골든셋 회귀를 API로 노출 (대시보드 전용, §9.1). 내부 검증…, export_writers_csv(), Any, Path, 라이터 골든셋 평가 로직 — CLI(eval/run_eval_writers.py)와 대시보드 API가 공유. 심사… (+18 more)

### Community 40 - "Health Check Endpoints"
Cohesion: 0.13
Nodes (27): check_config_ready(), check_llm_ready(), healthz(), get, /healthz (liveness) · /readyz (readiness — DB + LLM 준비) (§10.2). readyz는 배포…, 운영 설정 점검 — (ready, 상태문자열). 순수 헬퍼(단위 테스트 대상). 설정 기본값이 전부 '개발에서 바로 뜨는' 쪽으로 잡혀 있어,…, LLM 준비 상태 — (ready, 상태문자열). 순수 헬퍼(단위 테스트 대상). 목 모드: 키 없이도 ready("mock"). 실모드: 키…, readyz() (+19 more)

### Community 41 - "Categories API"
Cohesion: 0.11
Nodes (24): get, GET /v1/categories — 지출 카테고리 조회 (마법사 1단계). 마법사 1단계 화면이 "AI가 지출 카테고리를 추천해 드려요"라고…, 카테고리 9종을 돌려준다. 모임 유형과 무관하게 항상 같은 목록이다. 계산이 없는 고정값이라 **매번 부르실 필요가 없다.** 서버 기동 시나…, read_categories(), CategoryCatalog, BaseModel, 카테고리 조회 계약 — GET /v1/categories (마법사 1단계). 전역 9종으로 통일되면서(풀스택 협의 2026-08-04) 모임…, fallback_category() (+16 more)

### Community 42 - "Receipt Intake & Default Policy"
Cohesion: 0.14
Nodes (25): Intake(OCR) 결과 — 영수증에서 추출한 구조화 데이터., ReceiptData, app/tools/policy_defaults.py (유형별 기본 정책 조항), DefaultPolicy v1 프롬프트 — 회칙 미등록 팀 기본 정책 심사, Intake v1 프롬프트 — 영수증 인식(읽기 전용 1차 호출), Intake v2 프롬프트 — items 출력 형식 고정, 증빙 심사관 소견 (풀스택 협의 2026-08-04 — 지출 상세 'AI 심사결과' 네 번째 심사관). `mismatch_gate`가 영수증-…, 라우팅은 mismatch 리스트만 본다 — 소견이 추가돼도 경로가 그대로다. (+17 more)

### Community 43 - "Mock Fixture Consistency"
Cohesion: 0.08
Nodes (23): parametrize, eval/fixtures/mock_backend.json 정합성 (T9) — golden_v1.json과의 참조 무결성 포함. 이 파일이…, 골든셋 전 케이스의 expenseId·organizationId가 전부 fixture에 등재돼 있어야 한다. fixture 미등재 ID는…, expenseId가 더 이상 쿼리스트링이 아니므로, fixture의 title/amount/date/ description이 옛 쿼리값과…, `file://` 영수증 경로는 POSIX 슬래시여야 하고 파일이 실재해야 한다.…, 골든셋 치환 후 옛 규약(? 쿼리)이 하나라도 남아 있으면 여기서 잡는다., 조직 키가 숫자 문자열이 아니면 str(team_id) 조회가 옛 문자열 규약처럼 부분 일치로 오작동할 여지가 생긴다 — 키는 전부 순수 정수…, map_team_settings의 force=limit 해석(app/tools/policy_params.py:44-49)이 깨지지 않으려면… (+15 more)

### Community 44 - "Job Polling & Term Translation"
Cohesion: 0.13
Nodes (24): Any, get, 잡 결과의 판례 인용을 콜백과 같은 규칙으로 한국어화 (순수 함수). **왜 조회 시점인가** (#71). 용어 치환은 콜백 조립부에만 있었고…, 심사·생성 잡의 진행 상태와 결과를 조회한다. 콜백이 유실됐을 때의 **폴링 안전망**(§7.1). `job_id`는 우리 내부 id와…, read_job(), translate_result_terms(), 폴링 응답(`GET /v1/jobs/{job_id}`의 `result`) 사용자 노출 텍스트 스캔. 콜백과 같은 심사 결과인데 **출구가…, scan_job_result_terms() (+16 more)

### Community 45 - "Writer Golden Eval"
Cohesion: 0.11
Nodes (24): evaluate_expectations(), expect 대 actual 대조 — 실패한 검사 설명 목록 반환 (통과 시 빈 목록). 순수 함수. 규칙: - `<필드>_contain` :…, 라이터 골든셋 평가기 테스트 — expect 대조 규칙 + 목 이력 규약., rp-standard가 의존하는 2026-06 슬라이스는 8건 399,000원 그대로여야 한다., 시연에서 달을 바꾸면 숫자가 달라져야 한다 — 팀마다 3개월 이상을 보장한다. 2026-08-07까지 14개 팀이 `default`…, 허용 표현 중 하나만 있으면 통과 — 패러프레이즈를 흡수한다., 아무 표현이나 통과시키지 않는다 — 허용 목록은 못박혀 있다., 중첩 리스트는 그룹마다 하나씩 — 한 조항에 두 주제를 함께 요구할 때 쓴다. (+16 more)

### Community 46 - "Default Policy Audit"
Cohesion: 0.12
Nodes (24): _audit_by_default_policy(), 기본 정책 user 메시지에 넣는 영수증 첨부·판독 상태 한 줄. 2026-08-11 데모(팀2 expense 9) 재현 당시엔 기본 조항에…, 기본 정책 모드 — 회칙 미등록 팀을 유형별 기본 조항으로 본다 (마법사 3단계 건너뛰기). 전에는 무조건 pass여서 회칙 축이 통째로 비어…, _receipt_status_line(), LLMCallMeta, LLM 호출 1건의 계측 메타 (§5.3 재현성·§9 비용 지표) — chat_structured가 채운다., _capture_user_message(), 기본 정책 모드 — 회칙 미등록 팀 심사 (마법사 3단계 '건너뛰기'). 마법사 3단계는 회칙 등록을 "나중에 등록해도 돼요. 없으면 기본… (+16 more)

### Community 47 - "Rule Auditor (RAG)"
Cohesion: 0.13
Nodes (21): _fallback_query(), BaseModel, rule_auditor — 회칙 심사관 (병렬). 회칙 RAG 검색 → 위반 여부·근거 조항 판정. 검색은 CRAG/Self-RAG 스타일…, CRAG 스타일 검색: 채점 → 재작성 재검색. (chunks, grade, rewrite_meta) 반환. grade:…, RAG 1차 검색 질의 — 제목·설명에 증빙의 상호·품목을 더한다. 검색도 같은 이유로 제목에 휘둘렸다. 판정 입력만 고치고 검색 질의를…, query_rewriter 출력 — 회칙 검색용으로 재작성된 질의 한 줄., 결정적 재작성 템플릿 — 목 모드 응답이자 실모드 빈 출력 방어값., CRAG 재작성기 (강의 08-03) — 1차 검색이 빗나간 청구를 규정 어휘 질의로 재작성. 실모드: gpt-4o-mini (드문 경로라… (+13 more)

### Community 48 - "Backend Contract Verifier"
Cohesion: 0.13
Nodes (23): Namespace, _camel(), check_keys(), describe_category(), _euro(), get_json(), main(), Any (+15 more)

### Community 49 - "Rule Auditor Receipt Facts"
Cohesion: 0.13
Nodes (22): 증빙에서 읽은 객관적 사실(상호·품목) — 없으면 빈 문자열. **왜 회칙 심사관에게 이것이 필요한가.** 이 노드는 종전에…, receipt_facts_block(), _captured_llm_user(), parametrize, rule_auditor — 증빙에서 읽은 사실(상호·품목)을 판단 근거로 받는다 (2026-08-12). **무엇이 문제였나.** 이 심사관만…, LLM user 메시지에 상호·품목이 실려야 한다. 이 검사가 없으면 `receipt_facts_block`을 만들어 두고 호출부에서 안 쓰는…, 사실이 조항보다 먼저 온다 — 무엇을 산 것인지 확정한 뒤 조항을 댄다. 순서가 뒤집히면 조항을 먼저 읽고 제목에 끼워 맞추는 경로가 남는다., 영수증이 없으면 빈 헤더를 붙이지 않는다 — 없는 사실을 있는 것처럼 보이면 안 된다. (+14 more)

### Community 50 - "Policy Draft Clause Rules"
Cohesion: 0.09
Nodes (23): _draft_for(), 조 번호와 제목이 붙어야 회칙 문서로 읽힌다 — 종전엔 번호 없는 단문 목록이었다., 한도가 예산에 따라 달라져야 한다 — 종전엔 PER_MEAL_LIMIT 상수 하나였다., 승인 기준 금액은 화면 입력값이 **숫자 그대로** 회칙에 들어간다 (2026-08-11 저녁). 한때 숫자를 빼고 "관리자가 설정한 기준…, 잔액 부족(반려)과 항목 한도 초과(예외 승인)를 회칙이 **다른 조에서** 구분한다. 가드레일 동작과 대응한다 — 잔액 부족은…, 1인당 15,000원'만으로는 언제 내는지 알 수 없다 — 주기를 함께 적는다., 회칙에는 시스템 내부 표기 대신 사람이 쓰는 말을 쓴다 (장소_대관 → 장소 대관비)., 소액'·'고가'·'적절한' 같은 말은 심사 기준이 되지 못한다. (+15 more)

### Community 51 - "LLM Client"
Cohesion: 0.16
Nodes (20): chat_structured(), cost_usd(), embedding_model(), _invoke_structured(), model_for(), prepare_user_prompt(), LLM 클라이언트 — models.yaml 라우팅 + 목 모드 + 하네스(B2). MOCK_LLM=true(기본)면 OpenAI 호출 없이…, models.yaml pricing(USD/1M tokens) 기준 비용. 단가 미등록 모델은 0 (경고만). (+12 more)

### Community 52 - "Policy Proposals"
Cohesion: 0.15
Nodes (20): PolicyProposalRequest, 회칙·정책 관리 화면의 초안 요청 (풀스택 협의 2026-08-04 7번). 입력은 마법사 3단계와 같다 — 초안을 만드는 재료가 달라질…, _draft(), 회칙 초안 제안 흐름 (풀스택 협의 2026-08-04 7번). "AI 추천 → 요청 → 있으면 반환·없으면 없다고 반환 → 승인/거절"이…, 이미 승인·거절된 초안은 '있는 것'으로 치지 않는다., list_proposals는 최신순이다 — 결정된 것을 건너뛰고 가장 최근 미결정을 준다., 초안을 만드는 재료는 마법사 통합 요청과 같다 — 달라질 이유가 없다. to_draft_request는 model_dump 전체를…, 관리 화면의 목적은 AI 초안 생성 — 다른 rule_source를 열면 빈 초안이 저장된다. (+12 more)

### Community 53 - "Indexing Upsert Tests"
Cohesion: 0.12
Nodes (9): FakeConn, FakeConnCtx, FakeCursor, FakePool, _NullCtx, upsert — 판번호 발급(MAX(version)+1) 배선 검증. 실 DB 없이 FakeConn으로 단위 테스트.…, 이 팀의 첫 인덱싱(MAX가 NULL)이면 COALESCE가 1을 준다., test_upsert_first_indexing_starts_at_version_1() (+1 more)

### Community 54 - "Deploy Contract Verification"
Cohesion: 0.14
Nodes (21): 배포 전 계약 검증 도구의 값 검사 (scripts/verify_backend_contract.py). 이 스크립트는 배포 당일 백엔드 내부…, 가짜 백엔드로 run_checks를 돌리고 {항목명: (통과여부, 비고)}를 돌려준다., 지출 상세는 **빈 값이 정상**이다 (BE-001 등록 시 null)., 구 어휘가 실려 오면 X로 찍혀야 한다 — 이 PR이 막으려던 바로 그 경우. 통과로 기록하면 배포 당일 화면이 아직 구 카테고리를 보낸다는…, 9종 값은 재심사 에코라 정상이다 — 실패로 찍으면 배포 당일 오탐이 된다., 이력에 9종 밖 값이 섞이면 X — 몇 건이 무엇으로 접히는지까지 보여준다., 빈 값 집계가 다른 등급을 세면 안 된다 — 전부 9종이면 빈 값은 0건이다., 계약을 어긴 행(문자열)이 섞이면 건수가 맞지 않는다는 게 드러나야 한다. 조용히 걸러내면 "2건 중 0건 이상 없음"으로 통과해, 형태가… (+13 more)

### Community 55 - "Proposals API"
Cohesion: 0.16
Nodes (20): BigIntQuery, get, AI가 올린 제안 목록을 돌려준다. 없으면 빈 배열이다 — 404가 아니다 (LLM-015). `type` 미지정 시 마법사 회칙…, read_proposals(), ProposalOut, datetime, 제안 목록 조회 (LLM-015, `GET /v1/proposals`) — 회칙·정책 관리 화면. 회의 7번 항목("생성된 제안이 있으면…, 상태코드는 데코레이터에 선언돼 있어 코루틴 직접 호출로는 안 보인다 — 라우터를 본다. (+12 more)

### Community 56 - "Rule Auditor Design Principles"
Cohesion: 0.17
Nodes (20): rule_auditor(), '규칙보다 예시가 세다' 원칙, few_shot 입력은 런타임 직렬화와 바이트 단위로 일치해야 한다 (설계 원칙), Self-RAG 근거 기반 판정 원칙, DefaultPolicy v2 프롬프트 — 카테고리 라벨 카탈로그 정합, DefaultPolicy v3 프롬프트 — 미적용 조항으로 warn 금지, RuleAuditor v3 프롬프트 (이 청크 밖 파일, 참조로만 확인), RuleAuditor 프롬프트 v4 (+12 more)

### Community 57 - "Bylaw Amount Rounding"
Cohesion: 0.12
Nodes (21): _bylaw_unit(), round_bylaw_amount가 쓰는 반올림 단위 — 하한 올림에서도 같은 단위를 써야 한다., 같은 단위로 **올림** — 선언한 하한을 반올림이 깎지 않도록 쓰는 짝 함수. `round_bylaw_amount`는 가까운 쪽으로 붙이므로…, 같은 단위로 **내림** — 선언한 상한을 반올림이 키우지 않도록 쓰는 짝 함수. `round_bylaw_amount_up`(min 보호)과…, 회칙에 적을 금액으로 반올림 — **금액 크기에 따라 단위를 키운다**. 사람이 쓴 규정은 19,000원·48,000원·320,000원처럼…, 카테고리별 한도 앵커를 예산·인원에서 산출 (결정적 — LLM 아님). 종전에는 `PER_MEAL_LIMIT = 30_000` 상수 하나가…, round_bylaw_amount(), round_bylaw_amount_down() (+13 more)

### Community 58 - "Rule Text Chunking"
Cohesion: 0.15
Nodes (17): _fixed_chunks(), 구분자 없는 텍스트 — 문장 경계를 존중하며 overlap을 두고 자른다., split_into_clauses(), 컨텍스트 인덱싱 청크 분할 단위 테스트 (§4.4-a)., 조항 표기 없이 '1. 2. 3.' 번호 목록으로 쓴 규정도 항목 단위로 분할., 구분자 없는 긴 문서 — 문장 중간에서 자르지 않고, 청크 간 맥락이 겹친다., test_empty_text_returns_no_chunks(), test_falls_back_to_fixed_size_when_single_blob() (+9 more)

### Community 59 - "Dashboard Writer"
Cohesion: 0.18
Nodes (18): aggregate(), aggregate_dashboard_pure(), allowed_percent(), build_dashboard_graph(), DashboardState, fetch(), generate(), _in_period() (+10 more)

### Community 60 - "Architecture Concepts (Design Doc)"
Cohesion: 0.12
Nodes (19): 심사관 4종 (rule/budget/precedent/evidence), auto_approve_limit / 관리자 확인 설정 금액, 시연 시나리오 (판례 학습 단건 인과), 평가 지표 (golden_v1 97건, 정확도 100.0%), Generator-Evaluator 패턴 (writers 7종), 머지 게이트 (pytest + run_eval + run_eval_writers), 판례 학습 루프 (암묵지→형식지), RAG(pgvector) 회칙·판례 인덱싱 (+11 more)

### Community 61 - "API Query Param Boundaries"
Cohesion: 0.12
Nodes (18): parametrize, 쿼리 파라미터 계약 — **실제 HTTP 계층**을 지나가는 테스트. 이 파일이 있는 이유: 2026-08-07에 `GET…, 상한값 자체는 유효한 ID다 — `le`는 포함 경계여야 한다., 상한을 1 넘으면 422 — BIGINT 범위를 벗어난 값은 DB까지 가면 안 된다., 본문(strict) 쪽도 같은 경계 — 상한값은 접수, 초과는 422., organizationId도 같은 상한 — 위 테스트는 expenseId 초과만 덮고 있었다(팀장 지적, 2026-08-10).…, 평범한 팀 ID로 부르면 열려야 한다 — 422면 그 화면이 통째로 죽는다., strict를 뺀 대신 범위 검사는 남아 있어야 한다 — 0·음수·비숫자는 거절. (+10 more)

### Community 62 - "Indexing Pipeline Graph"
Cohesion: 0.25
Nodes (12): build_indexing_graph(), 컨텍스트 인덱싱 파이프라인 그래프 (§4.4-a). EV(백엔드 이벤트: team_id·change_type) → fetch → chunk →…, chunk(), chunk — 원문을 조항 단위로 분할 (§4.4-a). split_into_clauses는 순수 함수 — 단위 테스트 대상…, embed(), fetch(), fetch — 팀 회칙·카테고리 원본 조회 (REQ-041 파이프라인 1단계). 읽기 전용. 회칙은 **텍스트로 등록될 수도,…, upsert — 신규 판번호 발급 + 활성화 + 구판 비활성화, 원자적 전환 (§4.4-a). 판번호는 백엔드에서 받지… (+4 more)

### Community 63 - "Precedent Auditor & Judge Prompts"
Cohesion: 0.16
Nodes (18): guardrail_gate — 자동 승인 경로 판단 게이트, _precedent_lines — 판례 라인 포맷 함수, _rewrite_query — CRAG 질의 재작성 호출부, translate_precedent_citation — 판례 인용 한국어 변환(콜백·폴링 공용), Judge v1 프롬프트 — 심사 사유 품질 채점(JudgeResult), Judge v2 프롬프트 — 내부수치 노출 오탐 캘리브레이션, judge 자신도 실측(A/B)으로 검증·보정이 필요하다는 교훈, Judge v3 프롬프트 — 근거 충실성(admin_grounds_faithful) 채점 추가 (+10 more)

### Community 64 - "Burn Rate Forecast"
Cohesion: 0.18
Nodes (16): forecast(), 소진 속도 예측 — 순수 Python. 수치 계산은 LLM에 맡기지 않는다 (§9.1). spent 출처 단일화 규칙 (B-2 ④ — 목…, 소진 예측. expenses는 호출부가 이미 APPROVED로 필터한 목록을 넘긴다., _forecast(), burn_rate_forecast 단위 테스트 — 엣지 4종(B-2 ③) + 비중 임계 경계., 지출이 극히 적은 팀 — 2026-08-06 발견한 기존 결함. 소진 예정일이 date.max를 넘으면 `as_of +…, test_already_depleted_returns_as_of(), test_as_of_equals_period_end_past_month_scenario() (+8 more)

### Community 65 - "Architecture ADRs (Design Doc)"
Cohesion: 0.16
Nodes (18): Adjudicator — 판정 합성, ADR-7: 카테고리 분류를 Intake에 통합, 전용 Classifier 노드 폐지, BriefingWriter — 인수인계 브리핑, BudgetAuditor — 예산 심사관, context_chunks 테이블 (회칙 임베딩, REQ-041), Indexer — 회칙 재인덱싱 파이프라인, Intake — 영수증 OCR + 카테고리 자동 분류, load_context 노드 — 팀 정책·회칙 버전 로드 (+10 more)

### Community 66 - "Policy Draft API"
Cohesion: 0.20
Nodes (15): create_policy_draft(), create_policy_proposal(), _generate(), _latest_open_proposal(), post, 회칙·정책 초안 API — 마법사 3단계와 회칙·정책 관리 화면 (§7.2). §2.2 'LLM 호출은 워커만' 원칙의 명시적 예외: 마법사…, 가장 최근의 미결정(proposed) 회칙 초안. 승인·거절된 것은 제외한다., 마법사 1~3단계 통합 요청 (LLM-005 전면 개정) — 저장 없이 결과만 돌려준다. `rule_source=ai`면 'AI 초안' 버튼… (+7 more)

### Community 67 - "Budget Calculator"
Cohesion: 0.18
Nodes (14): BudgetCheck, check_budget(), BaseModel, 예산 수치 계산 — 순수 Python. 수치 계산은 LLM에 맡기지 않는다 (§5.1)., budget_calculator 단위 테스트 — 수치 판단 정확도 100% 목표 (§9.1)., test_exact_boundary_is_sufficient(), test_insufficient(), test_sufficient() (+6 more)

### Community 68 - "Backend Spec Reconciliation Notes"
Cohesion: 0.13
Nodes (17): §1-b: '반영 완료'로 문서 기재됐으나 실제 코드 미반영이었던 3건 — escalation_threshold 오매핑·auto_approve_limit NULL TypeError·budget spent KeyError (2026-07-31 해소), 모임 생성·AI 마법사 화면 ↔ 우리 API 대조 결과 (2026-07-29), 코드 반영 완료(2026-07-29) — PolicyDraftRequest.dues 추가·DUES_RULE 조항·FORCE_ESCALATION_MULTIPLE=4·PolicyParams 기본값 300000→200000·골든셋6건 동반수정, LLM팀 결정(2026-07-29) — 회비는 초안 생성 시에만 사용(회칙조항+notes), 자동승인한도 계산·심사에는 미사용, 후속검토(2026-07-31) — 마법사2단계 값이 실제 심사(load_context)에 도달하지 않고 있었음: escalation_threshold(금액)→confidence_threshold(θ) 오매핑, force_escalation_amount는 백엔드값 미조회, 2. 화면엔 있으나 계약·코드에 없음 6건 — 회비(dues)+없음옵션·무료플랜20명·auto_approve토글위치·중간구간대기자동·회칙업로드/직접입력·건너뛰기 기본정책모드, 1. 일치 항목 5건 — team_type enum·team_name·description·recommended_categories(1단계)·auto_approve_limit 5만원(소액기준), 0. 전제 — 화면 4장(모임생성+마법사1~3단계) 중 llm-server 소관은 POST /v1/policy-draft 하나뿐 (+9 more)

### Community 69 - "Figma Screen Dump"
Cohesion: 0.14
Nodes (17): Figma 화면 텍스트 덤프 — 예산관리시스템 (24화면·741텍스트, 기계 추출 원문), Figma 예산관리시스템 원본 (fileKey aob4NGJ2WiQoxEcFm5nRJ0, page 0:1), get_metadata 1회 호출로 페이지 전체 26화면 텍스트 추출 — 기계 추출 원문, 수동 수정 금지(재추출 시 덮어씀), Figma Starter 플랜 읽기 도구 월 6회 쿼터 — 단위는 '파일 전체 재동기화 6회'이지 화면 수가 아님, 화면: 대시보드 (152:789), 화면: 지출 상세 - 반려 (152:2179), 화면: 지출 상세 - 승인 대기 (152:1688), 화면: 승인 대기 - 에스컬 (152:1930) (+9 more)

### Community 70 - "Auth Middleware"
Cohesion: 0.15
Nodes (16): MonkeyPatch, _app(), AuthMiddleware — 서비스 토큰 경계 (§4.3). 보안 경계인데 테스트가 없었다. 특히 /mcp는 "읽기 전용이라 안전"이라는…, /mcp는 더 이상 면제가 아니다 — 토큰 없이는 401 (마운트된 실제 앱에서)., 없는 경로도 미들웨어를 먼저 지난다 — 404가 아니라 401이어야 한다. (종전 이름이 위…, 미들웨어만 단독으로 태운 앱 — 실제 라우트·DB와 무관하게 경계만 본다., 헬스체크·문서·데모 UI는 토큰 없이 열린다., 토큰 없이 실제 보호 경로를 치면 401. 2026-08-10까지 이 테스트는 동명 함수에 가려 실행되지 않았다 — 즉 '보호 경로가 토큰을… (+8 more)

### Community 71 - "Guardrail Real Config Tests"
Cohesion: 0.15
Nodes (15): _opinions(), parametrize, guardrail_gate — **실서비스 구성**에서의 판정 고정 (2026-08-11 리뷰 Blocking 대응). ## 왜 이 파일이…, 잔액 계산의 전제가 흔들리면(영수증 불일치) 실서비스 구성에서도 반려하지 않는다., 판정 권한이 없으면 반려도 못 한다 — 실서비스 기본값(auto_approve=False) 경로., 실서비스 형태에서는 두 금액 임계값이 같은 값이 된다. 이 전제가 깨지면(백엔드가 escalation_threshold를 다시 보내기…, 목 fixture의 모든 조직도 같아야 한다 — 목이 실제와 다르면 목 모드에서만 통과한다., 배포 데모의 그 건: 잔액 부족 + 한도(=절대 상한) 초과 → 반려. **이 테스트가 없어서 직전 변경의 무동작을 못 잡았다.** 갈린… (+7 more)

### Community 72 - "Precedents API Contract"
Cohesion: 0.17
Nodes (16): _body(), parametrize, POST /v1/precedents — 관리자 결정 수신 계약 (REQ-042 학습 루프의 입구). 이 엔드포인트는 테스트가 하나도 없었다.…, team_id는 본문에서 strict 정수 — 문자열 "2"는 422(BigIntId 계약)., 수신 엔드포인트도 서비스 토큰이 필요하다 — 토큰 없으면 401., 정상 요청 바디(예시 계약). 개별 필드를 덮어써 불일치 케이스를 만든다., 정상 요청 → 201, 그리고 decided_by='ADMIN'·요청 필드가 그대로 save_precedent로 넘어간다.…, claim에 제목 문자열만 보내면 422 — 백엔드가 처음 겪은 바로 그 케이스. (+8 more)

### Community 73 - "Dashboard Schemas"
Cohesion: 0.19
Nodes (15): app/graphs/writers/dashboard.py (대시보드 작성 노드), CategoryTrend, DashboardFigures, DashboardSummary, BaseModel, 대시보드 AI 요약 계약 — POST /v1/dashboard/summary (풀스택 협의 2026-08-04 5번). 정산 리포트의 AI…, 카테고리 하나의 이번 달 지출과 전월 대비 변화., 결정적 집계 — 요약문의 수치는 반드시 이 값과 일치해야 한다. LLM은 문장만 쓰고 숫자는 전부 여기서 나온다.… (+7 more)

### Community 74 - "Backend Pending Items"
Cohesion: 0.12
Nodes (16): 백엔드(풀스택) 대기 항목 정리 — 스프린트1 이후 v1.2 조건부 트랙 대기 통합 요약, C2: 승인/반려 콜백 단일화 사실상 확정(2026-07-27 DB 스키마 근거) — 잔여는 전이결과·멱등성 책임 소재, Q6: OCR 미리보기 토큰 스펙 미확정 — 구 API-050 번호 폐기(신규 API-050은 정산리포트로 재배정), 기능으로 재질의 필요, R1(내부 Agent API 전체) 최상위 승격(2026-07-27 수령분) — 우리가 호출하는 조회 API 8종 중 프론트↔백엔드 명세(API-001~050)에 등재된 것 0건, R2/Q7: 콜백 필드 매핑표 동결 대기 — category_assigned↔suggestedCategory 명칭 통일, R6(API-024): 대시보드 AI 요약 — 동기 GET+summary 문자열로 정식 등재, 스코프 재결정 필요, R6(신 API-044): 정책 추천 계약 — 무-teamId 요구는 철회(범위 축소), 잔여는 응답 필드(policy_params) 불일치, 회신요청 15: 모임생성·AI마법사 화면 대조 신규 대기 6건 — 코드는 이미 반영 완료(dues·배수4·기본값200000) (+8 more)

### Community 75 - "Backend Spec Review Requests"
Cohesion: 0.13
Nodes (16): Q3: 관리자 결정→LLM 전달 경로 — pull 폴링(커서·60초), 응답 필드 제안 완료(2026-07-22), 원천·주기·인증 잔여, 백엔드 API 명세서·테이블 스키마 검토 — 확인·요청 사항 (2026-08-10, 초안), A-10: 회칙 '팀당 1건' 전제가 policies 테이블 구조(UNIQUE(team_id) 없음, API-030/031)와 어긋남, A-11: 회칙 등록·수정·삭제(API-031/033/034) 시 POST /v1/context/refresh 호출이 명세에 없음 — 재인덱싱 누락 위험, A-12: API-052가 참조하는 /v1/budget-insights는 미존재 경로 — 실제 계약은 POST /v1/proposals/budget 202잡+GET 조회, A-13: 관리자 승인/반려 결정이 LLM에 전달되는 경로 없음(BE-008) — push(POST /v1/precedents) vs pull(커서 폴링) 방향 확정 요청, A-14: 영수증 파일 접근 API(GET /api/files/{fileName}) 명세 누락 — receipt_url 상대경로 강력 권장(Agent 토큰 유출 방지), A-2★: expenses.category ENUM이 구 7종 — 확정 9종(templates/category_catalog.yaml v2) 마이그레이션 반영 재확인 요청 (+8 more)

### Community 76 - "Eval Dataset Export"
Cohesion: 0.21
Nodes (15): export_review_golden(), export_run_results(), export_submission_single(), export_writers_golden(), _join(), _latest(), main(), Path (+7 more)

### Community 77 - "Dashboard Summary API"
Cohesion: 0.16
Nodes (12): create_dashboard_summary(), post, POST /v1/dashboard/summary — 대시보드 AI 요약 (풀스택 협의 2026-08-04 5번). **동기 방식**이다.…, 이번 달 지출 집계를 바탕으로 대시보드에 띄울 요약 2~4문장을 만든다. `message`를 화면에 그대로 띄우시면 된다. 함께 오는…, DashboardSummaryRequest, field_validator, model_validator, 생략됐을 때만 당월로 채운다 — 이후 코드는 period가 항상 있다고 보면 된다. 여기서 채우는 이유는 소비처(`dashboard.py`의… (+4 more)

### Community 78 - "Receipt Text Parsing"
Cohesion: 0.20
Nodes (14): _intake_from_text(), parse_receipt_text(), 추출 텍스트 → ReceiptData. 실모드면 LLM 구조화 추출, 아니면 정규식. 풀스택 협의 2026-08-04(8번)에서 OCR…, 백엔드가 추출해 준 영수증 텍스트에서 금액·날짜를 뽑는다 (정규식·결정적). 실모드에서는 `_intake_from_text`가 LLM 구조화…, 영수증 추출 텍스트 파싱 테스트 — 백엔드가 텍스트를 주는 경로 (팀 방향 2026-07-09)., 목 모드는 결정적 경로만 쓴다 — 테스트 재현성 때문., 실모드는 intake 프롬프트로 상호·품목까지 뽑는다 (Vision 경로와 같은 프롬프트)., 추출이 실패해도 금액·날짜는 살린다 — 판독 불능보다 낫다. (+6 more)

### Community 79 - "Default Policy Rules"
Cohesion: 0.15
Nodes (14): default_conduct_rules(), 모임 유형별 기본 정책 — 회칙을 등록하지 않은 팀의 심사 근거. 마법사 3단계에서 회칙 등록을 건너뛰면 화면이 "나중에 등록해도 돼요.…, 기본 정책 모드의 심사 근거 — 유형별 성격 조항만. 금액 한도·영수증 조항은 뺀다. tuple을 반환하는 것은 lru_cache 캐시값이…, parametrize, 금액 한도 조항은 근거에서 빠진다 — 가드레일이 이미 보고, 합의된 금액도 아니다., 영수증·증빙 첨부 조항은 근거에서 빠진다 — 그 판단은 evidence 심사관(증빙 심사관)과…, 지어낸 조항이 아니라 템플릿 원문 그대로여야 한다., 유형 조회 실패(load_context fail-open)로 낯선 값이 와도 심사가 멈추지 않는다. (+6 more)

### Community 80 - "v1.2 Conditional Track Notes"
Cohesion: 0.15
Nodes (15): §2.5 조건부 트랙 — 설계서 v1.2 개정 작업(①~⑦) 계약 동결 시 발화, Day6 데모 일정은 조건부 트랙에 비의존, 4. teamId 확보시점 해소 — 모임생성 CTA('모임 만들고 설정 시작하기') 이후 마법사 진입이므로 teamId 이미 확보로 확정 간주, 설계서 v1.1 → v1.2 개정안 (초안 — 풀스택 계약 회의 결과에 따라 확정 예정), BudgetAuditor 범위(Q8 결과에 따라) — 카테고리별 예산 미제공 확정 시 총예산 잔액·사용률·기간소진율로 책임 축소, llm-server 코드 영향(계약 확정 후 작업 목록) — analyze 스키마·영수증 프록시·execute_decision 재설계·콜백 완성·OCR 미리보기·가드레일 스위치·pull 폴링, §2.1/§5.1 영수증 접근(C4 확정 시) — receipt_signed_url→백엔드 프록시+Agent 토큰, parse_receipt(receipt_ref)로 시그니처 변경, §2.3/§4.4-b 판례 루프 입력(Q3, pull 방향 합의 진행중) — 관리자 결정 60초 커서 폴링 후 멱등 upsert+임베딩·판례 저장, §3.1/§3.3 가드레일 파라미터(Q4 확정 시) — auto_approve 마스터 스위치(기본 OFF, 심사는 수행·자동실행만 차단), θ는 LLM 내부 파라미터로 명시 (+7 more)

### Community 81 - "Budget Proposal API"
Cohesion: 0.16
Nodes (13): create_budget_proposal_job(), decide_proposal(), post, proposals API — 제안 잡 등록·조회·관리자 결정 기록 (§6, §9 수락률 지표의 기록 경로)., 예산관리 페이지 AI 메시지 생성 잡 접수 (LLM-016). 결과는 `GET /v1/jobs/{job_id}` 또는 `GET…, ProposalAccepted, ProposalPatch, BaseModel (+5 more)

### Community 82 - "PII Masker"
Cohesion: 0.24
Nodes (12): build_alias_map(), mask_names(), PIIMasker — 멤버 실명 → 역할명 치환 (§4.3, REQ-042·043 익명화). 프롬프트 투입 전·판례 저장 전·브리핑 생성 전에…, [{name, role}] → {실명: 역할별칭}. 같은 역할이 여럿이면 번호를 붙여 구분한다. 예:…, 텍스트 내 멤버 실명을 역할명으로 치환. 긴 이름부터 치환해 부분 일치 오염 방지., PIIMasker 순수 함수 단위 테스트 (§4.3, REQ-042·043)., test_duplicate_roles_get_numbered(), test_empty_text() (+4 more)

### Community 83 - "Policy Document Fetch"
Cohesion: 0.29
Nodes (13): PolicyDocumentSource, 회칙 원본 — **텍스트이거나 파일이거나** 둘 중 하나다 (T2, 회의 4번). 관리자는 마법사 3단계에서 회칙을 ① 직접 입력하거나 ②…, _docx(), _fetch(), 인덱싱 fetch — 회칙이 텍스트로 오든 파일로 오든 인덱싱까지 이어지는가 (T2). 회칙은 마법사 3단계에서 **직접 입력**되거나…, 파일 회칙이 **조항 단위로 인덱싱되는지** — 이게 안 되면 회칙 검색 품질이 무너진다. 관리자가 docx를 올렸을 때 조항 4개가 청크…, 스캔본 PDF 등 파싱 실패는 예외로 올라와 잡을 failed로 만든다. 조용히 넘어가면 회칙이 등록됐는데 심사에는 반영 안 된 상태가 되고,…, 백엔드가 텍스트도 파일도 안 주면 계약 위반이다 — 빈 인덱스를 만들지 않는다. (+5 more)

### Community 84 - "Adjudicator Prompt Cross-Refs"
Cohesion: 0.23
Nodes (13): AdjudicationResult, build_adjudication_user() (app/graphs/review/nodes/adjudicate.py), BaseModel, precedent_auditor node (app/graphs/review/nodes/precedent_auditor.py), _LEGACY_CATEGORY_ALIASES (app/tools/backend_client.py), classify_by_keywords() (app/tools/category_catalog.py), adjudicator agent, Adjudicator Prompt v1 (+5 more)

### Community 85 - "Briefing Writer Prompt Cross-Refs"
Cohesion: 0.21
Nodes (13): aggregate_precedents_pure() (app/graphs/writers/briefing.py), BriefingText, _handover_notes() (app/graphs/writers/briefing.py), _mock_briefing_text() (app/graphs/writers/briefing.py), BaseModel, LLM 산출은 summary만 — handover_notes는 판례 로직 그대로, figures는 코드가 붙인다…, verify_briefing_pure() (app/graphs/writers/briefing.py), briefing_writer agent (+5 more)

### Community 86 - "Deploy & Backend Gaps"
Cohesion: 0.37
Nodes (13): BE-007 팀 멤버 명단 API 미구현, BE-009 지출 이력 API 미구현, GCE 인스턴스 + docker-compose 배포 방식, 역방향 토큰 (BACKEND_SERVICE_TOKEN), claude_session_handoff.md (§3 백엔드 회신 요지 사실 확정표, §4 Track 1), LLM 서버 배포 방안 (2026-08-06), T2 + Track 3 실행 매뉴얼, T8 GCP 배포 체크리스트 (+5 more)

### Community 87 - "Context Status API"
Cohesion: 0.26
Nodes (11): BigIntQuery, get, 이 팀 회칙이 실제로 심사에 반영될 수 있는 상태인지 알려준다. `indexed=false`면 회칙 기준 심사가 되지 않는다. 그 경우 심사는…, read_context_status(), GET /v1/context/status — 회칙이 실제로 심사에 반영될 수 있는지 조회. 인덱싱은 202로 접수만 하고 비동기로 돌기…, 회칙이 없는 것은 정상 상태다 — 예외가 아니라 indexed=false로 알린다., 조항이 하나라도 있으면 indexed다 — 화면이 이 값 하나로 분기할 수 있어야 한다., _rows() (+3 more)

### Community 88 - "Execute Decision"
Cohesion: 0.29
Nodes (11): execute_decision(), 판정을 확정하고 실행 위임 사실을 기록한다. 외부 호출 없음. `idempotency_key`로 job_id를 남겨 둔다 — 콜백이 중복…, execute_decision — 실행은 백엔드 소유, 우리는 판정만 확정한다 (C2 콜백 단일화). 이 노드는 전에 백엔드…, 승인·반려 어느 쪽도 백엔드 실행 API를 부르지 않는다 (규율 3). backend_client를 통째로 감시해서, 이 노드가 어떤 경로로도…, 콜백 중복 도착 시 백엔드가 이중 처리를 막을 수 있도록 job_id를 남긴다. 콜백 페이로드의 jobId와 같은 값이어야 백엔드가 대조할 수…, 백엔드가 꺼져 있어도 동작한다 — 실행 위임이라 외부 의존이 없다., _state(), test_does_not_call_backend_execute_apis() (+3 more)

### Community 89 - "Screen vs Callback Field Audit"
Cohesion: 0.17
Nodes (12): LLM팀 결정(2026-07-29) — 고액기준을 화면 기준 200,000원으로 정렬(FORCE_ESCALATION_MULTIPLE 배수 6→4), 지출 심사 화면 ↔ 콜백 페이로드 대조 결과 (2026-08-03), 3-4: 화면 'AI 검토 중' 4번째 상태 vs verdict 3종(approve/reject/escalate) — 심사관 소견이 이미 채워진 채 최종판정 비어있는 모순 확인 필요, 3-8: '모임관리-AI추천예산' 대응 엔드포인트 없음 — /v1/proposals/budget MVP 제외 상태, budget_planner.py·핸들러는 코드에 생존, 2. 필드대조 — 콜백 15필드 중 화면이 실제로 쓰는 건 8개, 나머지는 불일치이거나 미표시, 3-3: evidence[]+figures{}+similar_cases[] 3필드를 화면은 '판정 근거 · …' 한 줄로 표시 — 조립 주체 미정, 3-7: 두 화면이 서로 다른 배수 — 마법사2단계 4배(5만/20만) vs 예산관리시스템 5배(10만/50만), FORCE_ESCALATION_MULTIPLE=4 상수 하나로 둘 다 만족 불가, 5. 선행조치(관측 보강) — callback.py의 계측 4종 계산을 trace_meta()로 분리해 콜백·jobs.result가 같은 계산지점 공유 (+4 more)

### Community 90 - "Automation Boundary Risk Review"
Cohesion: 0.18
Nodes (12): 심사 자동화 경계 검토 — 회신 및 후속 검토 (2026-08-04, sblim이 개발자A 문서 검토), 논의사항 7건 권고 — (b)기본정책모드 조건부 채택(E3·E7 선행)·한도초과 AI위임 미결·확신도기준 종속·회칙위반반려 유지+E4강제·절대상한 유지·마법사구간표 정정완료·5만원경계 화면수정, E2🔴: CI가 이 파손을 볼 수 없는 구조 — sblim 브랜치는 push 트리거 없음, cowbro/sblim CI 정의 자체가 상이, E3🔴: 화면은 'v2 반영됨'이라는데 load_context.py의 rule_version:1 하드코딩으로 심사는 v1 조항으로 동작, E4🔴: 실키 전환 시 LLM verdict가 게이트 결정을 대조 없이 넘어설 수 있음 — reject_candidate에도 adjudicate가 approve 채택 가능, E5🟡: 브랜치 발산이 8/3 문서 서술보다 훨씬 넓음 — 골든셋·콜백계약·execute_decision·심사노드·API·CI 6영역 표로 정리, E6🟡: worker.py 재시도소진 fail-safe가 expense_id=""로 CallbackPayload 생성 시 BigIntId(strict int) 검증 위반 가능, E7🟡: '골든셋 42/42 통과'가 기본 정책 모드를 보증 못함 — 골든팀 전부 회칙 미인덱싱, no_rules 경로 단위테스트 0건 (+4 more)

### Community 91 - "Golden Receipt Image Generator"
Cohesion: 0.23
Nodes (11): FreeTypeFont, Image, KoreanFontNotFound, _load_font(), main(), _merchant_for(), 골든셋 영수증 이미지 생성 — receiptPath의 https://example.com 플레이스홀더를 실제 로컬 이미지…, 기본은 신규 생성(example.com 잔여분). `--ids a,b,c`면 **재생성 모드**. 재생성 모드가 따로 있는 이유: 이미… (+3 more)

### Community 92 - "Claude"
Cohesion: 0.18
Nodes (11): BudgetOps LLM Server (프로젝트 개요), LLM팀 작업리스트 MVP 2026-08-05 (파일 소유권 정본), 모의 모드 (MOCK_LLM / MOCK_BACKEND), 머지 게이트 — pytest 전체 통과 + 오승인 0건·정확도 ≥90%, 설계서 v1.2 개정안 (협의중), 업무분장 스프린트1 작업명세 v2 (구판, 보조 근거), 저장소 밖 파일 인용 시 전체 경로 명시 규칙 (PR #17 교훈), detect_repeated_overrides 툴 [v1.1] — 동일 사유 반복 판례 탐지 (+3 more)

### Community 93 - "T11 반영사항 2026 08 06"
Cohesion: 0.20
Nodes (11): 개발자B_Todo_MVP_2026-08-06.md (비공개, B-4 항목 근거), LLM팀_작업리스트_MVP_2026-08-05.md (비공개, 파일소유권 정본 §7), 백엔드_요구_내부API_명세.md (LLM팀→풀스택 전달 내부 Agent API 명세), A-1★: 내부 에이전트 API(/internal/agent/** 8종)·POST /agent-callback이 API-001~052 명세서에 없음 — 섹션 추가 요청, T11(B-4) 명세 정본 동기화 반영사항 체크리스트, 카테고리 9종 정규화(B-8) — 저장소 명세는 반영 완료, xlsx·Notion 반영 여부 미확인, GET /v1/jobs/{job_id} result의 dead 케이스 계약 신설 (PR #18, 5180772), escalation_threshold 저장 규약 정정은 T13(B-7) 소관, T11과 경계 구분 (+3 more)

### Community 94 - "골든셋 목 규약 재설계안 2026 08 04"
Cohesion: 0.18
Nodes (11): 골든셋 목 규약 재설계안 — BIGINT 전환 이후 골든셋 미작동 원인·개선안, 고쳐야 할 목 분기 5곳 + 부수 수정 6곳(run_eval_real.py·run_eval_langsmith.py·테스트류·dashboard.html·smoke_mcp.py), 팀장 결정 필요 7건 — DB 1174행 삭제·fixture 방식 동의·ID 대역·60건 이관 주체·파일 공유 여부·브랜치통합 순서, 1차 벽 — BIGINT 전환 후 옛 문자열 team_id 행(1174개)에서 apply_schema() DB 마이그레이션 거부, 골든셋 42건 카테고리 vs 카탈로그 후보 교집합 0건 — classify_category가 후보 밖이면 LLM 미호출, classifier A/B 불가, 제안 — eval/fixtures/mock_backend.json 파일로 목 데이터 이관, MOCK_BACKEND_FIXTURES 환경변수로 경로 지정, ID 대역 매핑 제안 — 조직 9001~/지출 90001~(cowbro 42건), sblim 60건은 9100~/91000~, 2차 벽 — 목 규약이 expense_id·organizationId 문자열에 시나리오 단서 인코딩(backend_client.py 5개 단서) (+3 more)

### Community 95 - "프롬프트 브랜치 통합계획 2026 08 04"
Cohesion: 0.18
Nodes (11): cowbro·sblim 프롬프트 브랜치 통합 계획 (2026-08-04, 개발자A 작성), adjudicator/v3 충돌 — 양쪽 다 승격, 내용 다름(cowbro:관리자용 수치누락방지 vs sblim:환각방지+확장입력) → v4 신설 제안, 브랜치 갈라짐 원인 — 7ec8d73이 sblim의 ba06b6c(BIGINT)만 체리픽, 공통조상 bbd9bb7, 미머지 커밋 20개 이상(양방향), cowbro 프롬프트 공통 결함 계열 — few_shot이 런타임 실제 직렬화 형식과 불일치(공백·date필드·빈줄 등, rule_auditor/v3·digest_writer/v2·adjudicator/v3·precedent_auditor/v1), digest_writer/v2 충돌 — cowbro few_shot 예시2가 verify_digest_pure 자체 검증기 통과 못함(누락 토큰 284,000원), judge 하네스는 cowbro 전용 — 판정정확도로 못 잡는 관리자 사유 품질 편차를 LLM-as-Judge로 탐지, 머지 시 충돌 25건(git merge-tree 실측) — 프롬프트3(add/add)·코드8·골든셋2·테스트4·기타(ci.yml 등), policy_drafter/v2 충돌 — 양쪽이 서로 다른 문제를 같은 버전칸에서 고침, 병합 필요 (+3 more)

### Community 96 - "Llm팀 아키텍처 워크플로우 설계서 V1.1"
Cohesion: 0.18
Nodes (11): adjudicate 노드 — LLM 판정 합성, callback 노드 — 백엔드 결과 통보, dry-run 모드 — 사전 문의 심사 [v1.1], execute_decision 노드 — Agent 승인 API 호출, Fail-safe 매트릭스 — 어떤 실패도 자동승인으로 귀결되지 않음, guardrail_gate 노드 — 결정적 가드레일 (순수함수), persist_precedent 노드 — 판정 로그 저장, precedents 테이블 (판례, REQ-042) (+3 more)

### Community 97 - "Readme"
Cohesion: 0.20
Nodes (10): get_budget_status 툴 (백엔드 읽기 API), MCP 서버 — 읽기 툴 4종 이중 노출 (내부·FastMCP), search_precedents 툴 (pgvector), 골든셋 v1.1 (42건) 실모드 100%, 골든셋 실모드 튜닝 6회전 (63.3%→100.0%) — temperature=0 고정 + rule_auditor v3, eval/run_eval_real.py — 실모드 하니스 정식화, /mcp 엔드포인트 — Streamable HTTP, 서비스 토큰 필요, MOCK_LLM / MOCK_BACKEND 스위치 (+2 more)

### Community 98 - "Trajectory Gate Derivation"
Cohesion: 0.20
Nodes (9): Trajectory 채점용 가드레일 도출 — 하니스 두 벌이 갈리지 않게 고정. 2026-08-12에 실제로 갈렸다. `run_case`(로컬…, mismatch_gate 단락 경로 — gate_result가 없어도 궤적은 남아야 한다., 가드레일까지 도달한 건은 그쪽 규칙이 궤적이다 — mismatch로 덮어쓰지 않는다., **배선 그물** — 순수 함수만 검사하면 이 결함을 다시 놓친다. LangSmith target이…, test_empty_state_is_empty_trajectory(), test_gate_result_rules_pass_through(), test_gate_result_wins_over_mismatch(), test_langsmith_target_uses_the_shared_derivation() (+1 more)

### Community 99 - "Send Callback Retry"
Cohesion: 0.42
Nodes (8): POST {BE}/agent-callback — 지수 백오프 3회 재시도 (A-5). 최종 실패해도 예외 없이 False — 백엔드의 폴링…, send_callback(), send_callback 재시도 (A-5) — 3회 지수 백오프, 최종 실패는 False (예외 금지). 실모드 경로 검증을 위해…, _real_mode_settings(), test_exhausts_three_attempts_and_returns_false(), test_mock_mode_skips_http_entirely(), test_retries_then_succeeds(), test_succeeds_first_try_without_retry()

### Community 100 - "Golden V2 Report"
Cohesion: 0.22
Nodes (9): 골든셋 v2 — 8유형 799건 유형별 평가 리포트 (2026-09-08 작성, 2026-09-09 갱신), 오승인 원인조사 5단계 — 결정론적경로확인→LangSmith추적불가 신발견→케이스 재실행 재현(정확히 기대값 escalate)→초기가설 반증→비결정성 결론, 실패 분류 6개 패턴 — 판례유사검색 목모드무력·예산사용률90%경계 게이트무관측·분할결제 별도탐지로직없음·회칙우선순위 코드미정의·표기변형 부분문자열한계·실LLM도 23%오답('기타'로 보수화), 가정 목록 7건 — 7유형→8유형 승격(receipt_mismatch 신설)·ID대역 9100~9999 확장·rule_conflict '특별조항이 일반보다 우선' 원칙(법해석 일반원칙 채택, 실측 85%로 확인), 참고문헌 7편 — CheckList(Ribeiro2020)·ISTQB경계값분석·RAG벤치마크(Chen2024)·LegalBench(Guha2023)·LLM-as-Judge(Zheng2023)·HELM(Liang2022)·Metamorphic Testing(Chen1998/2018), 유형별 정의·mock/real 커버리지 매트릭스 — clear_approve·clear_reject·boundary·missing_info·receipt_mismatch·notation_variant·rule_conflict·circumvention 8종, 실 799건 중 오승인 1건(v2-rule_conflict-091) — temperature=0에서도 남는 LLM 비결정성으로 최종 판명, 발견 — eval/run_eval_v2_real.py가 setup_langsmith() 미호출로 799건 배치 실행 자체가 트레이싱 없이 진행됨 (+1 more)

### Community 101 - "Llm팀 아키텍처 워크플로우 설계서 V1.1"
Cohesion: 0.25
Nodes (9): ADR-1: LLM 제공자로 OpenAI GPT-4o 계열 채택, ADR-2: 벡터저장소·checkpointer를 Postgres+pgvector로 단일화, ADR-3: 성능 평가는 LangSmith+골든셋, LangSmith (트레이싱·평가), llm-api (FastAPI 게이트웨이), llm-postgres (Postgres + pgvector), llm-worker (LangGraph 실행기), OpenAI API (gpt-4o / gpt-4o-mini / embeddings) (+1 more)

### Community 102 - "Readme"
Cohesion: 0.25
Nodes (8): 목 골든셋 100%는 품질 지표 아님 — adjudicate.py 확신도 0.95 고정으로 '확신없으면 사람에게' 안전장치 미작동, 목 모드 확신도가 항상 0.95 고정 — '확신 없으면 사람에게' 안전장치가 이번 측정에서 한 번도 작동하지 않음, 5건은 최악값, 3개 유형(rule_conflict·circumvention·notation_variant 분류)은 목 모드로 원리적 검증 불가능 — 이번 확장의 핵심 발견, 실모드로 실증, 심사 기준 측정 도구 README (scripts/eval_tools, 일회성 측정 스크립트 — CI/머지게이트 비대상), band_check.py — 마법사 2단계 구간표가 실제 가드레일과 맞는지 금액대별 대조(DB불필요, 자동승인 토글 on/off 모두 확인), gate_stats.py — 골든셋에서 관리자에게 올라간 건이 무엇 때문인지 집계(DB필요, 금액단독사유 별도 집계), 주의 — 목 모드에서는 adjudicate 확신도가 항상 0.95 고정, simulate_c_layer의 오승인 건수는 최악값(실모드는 더 적을 수 있음), simulate_c_layer.py — 자동승인한도 초과건을 AI판단에 맡길 때 정확도·오승인·자동종결 비율을 현행과 비교(DB필요)

### Community 103 - "풀스택 회신 반영 2026 08 04"
Cohesion: 0.25
Nodes (8): 4. 콜백 15→11필드 정제 완료 — modelVersion/promptVersion/latencyMs/costUsd 4필드 제거, jobs.result로 관측 보존 이관, 풀스택 팀 회신(3건) 반영사항 — jobId타입·회비0·카테고리매핑 (2026-08-04), 카테고리 매핑표가 '동아리/학생회' 유형 1개만 커버 — 나머지 24종(스터디·친목·동호회·회사) 초안을 LLM팀이 직접 작성해 HTML로 전달, 맞물린 항목 — expenses.category NOT NULL이라 실연동 시 classify_category 노드가 사실상 미실행(입력 echo화), 팀확정사항 변경은 ③회신과 함께 처리, IT카테고리 3표기 확정(2026-08-05) — ENUM저장은 언더바(IT_인프라), 화면표시는 슬래시(IT/인프라), 'IT인프라'(구분자없음)는 오기, jobId 문자열·회비'없음'=0 확정 — 코드변경 0건, 문서 미확정 문구만 확정표기로 정정, 매핑결과 수치 — 30행 중 40%가 '기타' 귀결, 친목유형 83%(5/6) 기타 — 매핑은 되지만 통계 해상도 문제 잔존, 풀스택_연동_계약.md (배지 규칙표 등 LLM팀-풀스택 연동 확정 계약)

### Community 104 - "작업리스트 배포전 2026 08 04"
Cohesion: 0.25
Nodes (8): 배포 전 작업 리스트 (LLM팀 2인, 회의록 10항목+Figma 화면 5종 기준, 배포 D-2), 0. 선행 3건 — 백엔드 내부조회API 8종 확인·브랜치통합(sblim 29커밋·충돌 25건)·DB 옛 문자열ID 1174개 정리, 2. 회의록 내 모순 2건 — 정산리포트AI 제외 vs 대시보드AI요약 신설 / force_escalation_amount만 설정 시 실제 무효화, 9. 배포 자신감 — 실모드 스모크 확인: BIGINT 깨끗DB적용·실모드심사6/6·회칙RAG작동·확신도실값(0.90·0.95)·비용건당$0.007, 4. 개발자A 작업 — 카테고리직접입력삭제대응(4-1)·OCR상호명확장(4-2)·대시보드AI요약·회칙정책제안API·분류기잔여오분류·골든셋9종반영, 5. 팀장(sblim) 작업 — 내부API8종확인·DB정리+BIGINT마이그레이션·마법사3단계일괄수신·category ENUM9종·GCP배포환경변수, 결정: 자동승인 한도 입력 하나로 통일(코드변경 0) — 중간구간 별도동작(옵션2)은 오승인 5건 리스크로 기각, C를 열어본 실측 — 자동승인 한도 초과건을 AI에 위임 시 오승인 5건 발생(정확도 100%→88%, AI처리비율 40%→52%)

### Community 105 - "Models"
Cohesion: 0.29
Nodes (8): budget_auditor agent, classifier agent (카테고리 자동 분류), dashboard_writer agent (대시보드 요약), default_policy agent (회칙 미등록 팀 기본 정책 심사), digest_writer agent (주간 브리핑), gpt-4o-mini model (input $0.15 / output $0.60 per 1M tokens), query_rewriter agent (CRAG 재검색 질의 재작성), report_writer agent

### Community 106 - "Progress"
Cohesion: 0.25
Nodes (8): AnalyzeRequest 5필드 pull 모델 (jobId/expenseId/organizationId/reviewGoal/receiptPath), auto_approve 최상위 게이트 (PolicyParams.auto_approve), backend_client 신규 3함수 (get_expense_detail/get_team_settings/get_receipt_by_path), app/tools/backend_client.py — 백엔드 경계, 기획/bravo_기술아키텍처설계서.docx (풀스택 구현 설계서), Docker dockerInference 커널 잠김 이슈 — 재부팅만이 해결책, jobId 매핑 — external_job_id 컬럼, `/v1/analyze` pull 모델 재설계

### Community 107 - "Progress"
Cohesion: 0.25
Nodes (8): eval/compare_judge.py — judge A/B + 환각 프로브 러너, HITL 사람 개입 — interrupt() 기반 escalate 정지·재개, judge v3 승격 — LLM-as-Judge 근거 충실성(faithfulness) 차원, policy_drafter v2 승격 — few_shot 3종 + 분량·문체 기준, PROGRESS.md — BudgetOps LLM 서버 진행 기록, app/llm/prompts.py — load_prompt(agent) YAML 로더, 실시간 심사 SSE (POST /v1/reviews/stream), /ui 내부 검증 대시보드 — 4탭

### Community 108 - "Policy Draft"
Cohesion: 0.29
Nodes (6): ExtraRule, BaseModel, LLM이 제안하는 추가 조 하나 — 기본 조항과 같은 형식으로 렌더링하기 위해 제목을 분리한다. 외부 계약(`PolicyDraft.rules:…, 조 번호를 뺀 "(제목) 본문" — 번호는 기본 조항 개수에 이어 조립부가 붙인다., LLM이 모호어 조항을 내놓아도 초안에는 실리지 않는다 — 초안 전체는 살린다., test_llm_clause_with_vague_wording_is_dropped_from_the_draft()

### Community 109 - "백엔드 회신 초안 2026 08 10"
Cohesion: 0.29
Nodes (7): 백엔드 팀 회신 — 확인·요청 사항 (2026-08-10, 배포 위치·역방향 토큰·내부API 오픈 현황), ① 내부 Agent API 401 종결 — 원인은 LLM팀 VM 컨테이너가 토큰분리(b67a643) 이전 낡은 이미지로 구동, nginx 확인 요청은 오진이었음 (2026-08-10 해소), BE-007(멤버명단)·BE-009(지출이력) 미구현 — 백엔드 인지 완료, LLM팀은 fail-open 유지, receiptPath는 심사요청(LLM-003) 필드로 계속 전달 확인 — 코드 변경 불요 확정, 별건: 백엔드→LLM 방향 401(SERVICE_TOKEN) 문의 — POST /v1/dashboard/summary가 422(인증 통과·빈 본문 검증에러)로 LLM팀 쪽 설정 문제 아님 확인, 역방향 토큰 공유값 .env 적용 완료 — 확인 완료 항목, 검증용 지출 ID — team 1/expense 1 데이터가 배포 DB에 실재해 계약 검증 통과, 별도 전달 불필요

### Community 110 - "풀스택 협의 2026 08 04 반영"
Cohesion: 0.29
Nodes (7): 풀스택 협의 반영 (2026-08-04, 회의 메모 10항목 코드·문서 반영 결과), 정해주셔야 하는 것 6건 — 최소값검증주체①·2단계추천값처리방식②·회칙PDF텍스트변환주체③(백엔드추출권장)·신규API3종요구사항④·정산리포트AI제외방식⑤·카테고리경계2건⑥, 1. 마법사 1단계 이름·초기예산 필수 — 이미 구현되어 있음(확인만, 변경 불필요), 2. 마법사 2단계 자동승인한도·auto_approve bool 이미 반영 — 최소값(1만원) 검증 주체 미정(결정필요①), 6. 카테고리 전역 9종 통일 — 식비·교통·IT/인프라·교육·회의·장소/대관·행사/활동·비품·기타, 순서기반 매칭+짧은키워드 함정 제거, classifier/v3 승격, 8. 지출상세 — 증빙 심사관(mismatch_gate) 추가, 회칙·예산·판례와 같은 Opinion 형식 출력, 판정권한은 없음(에스컬은 가드레일이 결정), 9. 회칙 버전 이력 MVP 제외 — LLM팀에 이력기능 없음, context/status의 version은 현재값 1개뿐, 영향 없음

### Community 111 - "Llm팀 아키텍처 워크플로우 설계서 V1.1"
Cohesion: 0.29
Nodes (7): ADR-8: 제안(proposal) 기능 실행 경계 — 수락 실행은 백엔드 CRUD 경유, BudgetPlanner — 예산 조정 제안 [v1.1], burn_rate_forecast 툴 [v1.1] — 소진 시점·이관 여력 계산, DigestWriter — 대시보드 AI 총무 브리핑 [v1.1], proposals 테이블 (예산·회칙 개정 제안, v1.1), LLM 서버는 메인 DB에 직접 접속하지 않는다 — 백엔드 API 경유 원칙, 기획/업무분장_스프린트1_작업명세_v3.md (최종 업무분장)

### Community 112 - "Progress"
Cohesion: 0.29
Nodes (7): API-024 GET /api/teams/{id}/dashboard/ai-summary, API-043 POST /api/policies/recommend, API-044 POST /api/expenses/{id}/ai-review, API-045 GET /api/expenses/{id}/review-result, 기획/bravo_API명세서.xlsx (풀스택 API 49개), app/schemas/callback.py — camelCase 직렬화, docs/풀스택_회신요청.md (통합 질의 문서)

### Community 113 - "Stress Idempotency"
Cohesion: 0.48
Nodes (6): main(), _payload(), AsyncClient, 동시요청·멱등성 스트레스 테스트 (PROGRESS §6-5) — Idempotency 설계 실증. 같은 expense_id로 POST…, _submit(), _wait_done()

### Community 114 - "Drafts"
Cohesion: 0.33
Nodes (6): BigIntQuery, get, 아직 결정되지 않은 회칙 초안을 돌려준다. 없으면 `null`이다. 회의록의 "생성된 메시지가 있으면 반환, 없으면 없다고 반환"이 이…, read_policy_proposal(), 초안이 아직 없음'은 오류가 아니라 정상 상태라 200 + null이다., test_read_returns_null_when_nothing_saved()

### Community 115 - "Budget Planner"
Cohesion: 0.53
Nodes (6): _period_bounds(), (as_of, period_end) 계산 — 순수 함수 (단위 테스트 대상). period 미지정이면 today의 당월. 지난달 지정 시…, date, test_period_bounds_current_month(), test_period_bounds_future_month_clamps_to_start(), test_period_bounds_past_month_clamps_to_end()

### Community 116 - "V3"
Cohesion: 0.47
Nodes (6): app/graphs/writers/digest.py (주간 브리핑 작성 노드), DigestText, LLM 산출은 문구만 — 수치 figures는 코드가 붙인다 (digest_writer 프롬프트). advice(총무 코멘트): 이상…, DigestWriter v1 프롬프트 — 주간 지출 브리핑(AI 총무), DigestWriter v2 프롬프트 — few_shot 자기모순·검증 누락 해소, DigestWriter v3 프롬프트 — advice 계약 복구 + few_shot 정합

### Community 117 - "Auth"
Cohesion: 0.33
Nodes (5): AuthMiddleware, BaseHTTPMiddleware, Request, 타이밍 공격 방어 — 문자열 ==가 아니라 hmac.compare_digest를 쓴다., test_token_compared_in_constant_time()

### Community 118 - "Request Log"
Cohesion: 0.33
Nodes (4): BaseHTTPMiddleware, Request, RequestLogMiddleware — 구조화 로깅(JSON), request_id 전파 (§4.3)., RequestLogMiddleware

### Community 119 - "Conflict Rules V1"
Cohesion: 0.33
Nodes (6): 회칙 충돌 조항 세트 (golden_v2 rule_conflict 유형 전용, 실모드 전용 자료), 제12조 송년회 특별조항 — 회식비 1인당 5만원(제2조 통상한도 3만원 대비 상향, 12월 공식 송년행사 한정), 제13조 신입회원 환영회 조항 — 회식비 1인당 2만원(제2조 대비 하향, 조건부), 제14조 전체총회 조항 — 회식비 1인당 4만5천원(상향, 총회참석자명부 근거), 목적 — rule_auditor(실 LLM)가 일반조항vs특별조항 중 무엇을 근거로 삼는지, 어느쪽이 더 구체적 규정으로 우선하는지 관찰(목모드는 항상 pass 고정이라 효과 없음), 실 전체 정확도 96.0%(767/799, 목표≥90% 상회) — 비용 $17.6115(건당 $0.0220), 소요 1022초, 동시성4

### Community 120 - "Progress"
Cohesion: 0.33
Nodes (6): app/graphs/review/nodes/budget_auditor.py — 잔액 = 총예산 - 승인지출합, app/graphs/review/nodes/classify_category.py — 유형별 카테고리 분류 v2, app/graphs/review/graph.py — build_review_graph, 노드 12개, app/graphs/review/nodes/guardrail_gate.py — evaluate_guardrails() 순수함수, app/graphs/review/nodes/precedent_auditor.py — ADMIN 판례만 신호, app/graphs/review/nodes/rule_auditor.py — CRAG 검색 보정

### Community 121 - "Make Report Charts"
Cohesion: 0.53
Nodes (5): _bar(), label_bars(), main(), golden_v2_report.md용 유형별 정확도 막대차트 2장 생성 — 목 모드 실측값만 사용 (실모드는 이 세션에서 API 키 접근…, style()

### Community 122 - "Env"
Cohesion: 0.40
Nodes (4): Run migrations in 'offline' mode. This configures the context with just a URL…, Run migrations in 'online' mode. In this scenario we need to create an Engine…, run_migrations_offline(), run_migrations_online()

### Community 123 - "0001 Initial Schema"
Cohesion: 0.40
Nodes (4): downgrade(), schema.sql을 그대로 실행 (SSOT 유지)., 초기 스키마 되돌리기 (신규 4개 테이블 DROP) — 되돌린 뒤 재적용 시 alembic_version이 초기화되어야 함., upgrade()

### Community 124 - "V3"
Cohesion: 0.40
Nodes (5): MAX_EXTRA_RULES — 추가 조항 상한 상수(policy_draft.py:35), PolicyDrafter v1 프롬프트 — 모임 맞춤 추가 조항 제안, PolicyDrafter v2 프롬프트 — few_shot 3건 추가 + 금액 정책 명시, '규칙보다 예시가 세다' — few_shot 출력 개수가 실효 상한을 정하는 원칙, PolicyDrafter v3 프롬프트 — 분량·문체 지침 이식(상한 3→7)

### Community 125 - "Dump Openapi"
Cohesion: 0.50
Nodes (4): docs/openapi.json — API 계약 스펙, current_spec(), main(), OpenAPI 스펙을 docs/openapi.json으로 덤프 (Sprint 2 'OpenAPI 커밋'). 실행: uv run python…

### Community 126 - "Budget Planner"
Cohesion: 0.50
Nodes (4): allowed_percent(), 본문에 나와도 되는 백분율. 반올림 자리수가 갈리므로 이웃값까지 허용한다., round()는 half-even이라 22.5→22를 준다 — 2026-08-06 적대적 리뷰 발견. 프롬프트는 "반올림해 정수로"라고…, test_allowed_percent_accepts_half_up_rounding()

### Community 127 - "Gate"
Cohesion: 0.67
Nodes (3): has_python_changes(), main(), Stop 훅 — 작업 트리에 .py 변경이 있으면 pytest를 실행하는 테스트 게이트. 실패 시 {"decision": "block",…

### Community 128 - "Api Query Params"
Cohesion: 0.50
Nodes (4): fixture, TestClient, client(), DB를 타는 자리만 막고 HTTP 계층을 그대로 태운다.

### Community 131 - "Llm팀 아키텍처 워크플로우 설계서 V1.1"
Cohesion: 0.67
Nodes (3): ADR-6: 지출 상태 2컬럼 모델 (status × actor_type), ADR-9: UI 용어 override → 'AI와 다른 결정', 지출 상태 모델 — status × actor_type 2축

## Knowledge Gaps
- **197 isolated node(s):** `budgetops-llm-server`, `openapi.json 실측 23경로 — 구 14/17경로 서술이 낡음(브랜치 통합으로 소멸)`, `PR #4(docs-handover, LLM_API_명세서.md 신설) 머지 충돌 — 존치 여부 T11에서 결정`, `LLM팀_작업리스트_MVP_2026-08-05.md (비공개, 파일소유권 정본 §7)`, `개발자B_Todo_MVP_2026-08-06.md (비공개, B-4 항목 근거)` (+192 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1312 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `Settings & DB Pool` to `Analyze & Briefings API`, `Digest Writer`, `Precedents & MCP Server`, `Worker Job Queue`, `Auth Middleware`, `Reviews SSE Stream`, `Worker Recovery`, `Prompt Loader`, `Load Context & Backend Client`, `Intake Receipt (Vision)`, `Health Check Endpoints`, `Backend Contract Verifier`, `LLM Client`, `Auth Middleware`, `Precedents API Contract`, `Receipt Text Parsing`, `Send Callback Retry`, `Stress Idempotency`, `Auth`, `Env`? — ✅ traced, see "Traced Questions" below**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `load_prompt()` connect `Prompt Loader` to `Settings & DB Pool`, `Digest Writer`, `Category Classifier`, `Precedents & MCP Server`, `Dashboard Summary`, `Policy Draft Writer`, `Keyword Classifier`, `Rule Amendment Writer`, `Budget Figures & Proposal`, `Intake Receipt (Vision)`, `Report Writer`, `Adjudicator`, `Eval Judge`, `Briefing Writer`, `Budget Planner Graph`, `Default Policy Audit`, `Rule Auditor (RAG)`, `Rule Auditor Design Principles`, `Dashboard Writer`, `Receipt Text Parsing`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `docs/openapi.json — API 계약 스펙` connect `Dump Openapi` to `Readme`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `Opinion` (e.g. with `build_adjudication_user()` and `_translate_opinion_citations()`) actually correct?**
  _`Opinion` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `ExpenseClaim` (e.g. with `_receipt_opinion()` and `_audit_by_default_policy()`) actually correct?**
  _`ExpenseClaim` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `ReceiptData` (e.g. with `_intake_from_text()` and `_receipt_opinion()`) actually correct?**
  _`ReceiptData` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `budgetops-llm-server`, `openapi.json 실측 23경로 — 구 14/17경로 서술이 낡음(브랜치 통합으로 소멸)`, `PR #4(docs-handover, LLM_API_명세서.md 신설) 머지 충돌 — 존치 여부 T11에서 결정` to the rest of the system?**
  _197 weakly-connected nodes found - possible documentation gaps or missing edges._

## Traced Questions

### Why does `get_settings()` bridge ~19 communities?

`app/config.py:48`의 `@lru_cache`가 붙은 전역 싱글턴 설정 접근자(pydantic-settings 패턴, `.env`를 한 번만 읽고 캐싱된 `Settings` 객체를 반환)다.

직접 연결 77개를 전수 확인한 결과 **전부 `EXTRACTED`**(AST가 확인한 결정적 사실, LLM 추론 0건)였다 — `calls` 47건, `imports` 29건, `contains` 1건. 즉 이 노드가 여러 커뮤니티를 잇는 이유는 숨겨진 의미적 결합이 아니라, **설정값(API 키·DB URL·모델 라우팅·기능 플래그)이 필요한 거의 모든 모듈이 의존성 주입 없이 `get_settings()`를 직접 호출**하는 단순한 구조적 사실이다.

직접 연결이 닿는 커뮤니티(상위): Settings & DB Pool 27건(같은 커뮤니티 내부) · Load Context & Backend Client 12건(`backend_client.py`의 백엔드 프록시 함수 전부) · Worker Job Queue 6건 · Analyze & Briefings API 5건 · Health Check/Intake(Vision)/LLM Client/Prompt Loader 각 3건 · 그 외 Auth Middleware·Reviews SSE Stream·Precedents & MCP Server·Digest Writer 등 다수 1건씩.

**시사점**: 이 코드베이스는 설정을 계층별로 주입하지 않고 API 라우터·워커·심사관 노드·라이터·미들웨어·LLM 클라이언트 전 계층에서 "필요할 때 `get_settings()`를 직접 부른다"는 단일 전역 접근 패턴을 일관되게 쓴다. `@lru_cache` 덕에 실행 비용은 없지만, 테스트에서 설정을 오버라이드하려면 캐시 무효화 처리가 필요하다는 뜻이기도 하다 — `Backend Contract Verifier`·`Guardrail Real Config Tests` 커뮤니티가 이 함수와 연결된 것도 그 때문으로 보인다.

`load_prompt()`(2번째 다리 노드)·`Opinion`의 INFERRED 8건 등 나머지 제안 질문은 이 세션에서 추적하지 않았다.