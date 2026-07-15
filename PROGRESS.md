# PROGRESS.md — BudgetOps LLM 서버 진행 기록

> 새 세션에서 이 파일만 읽고 바로 이어서 작업할 수 있도록 작성. 최종 갱신: 2026-07-15(2차).

## 0. 최우선 — 실제 풀스택 API 명세 확보됨 (2026-07-15)

`기획/bravo_API명세서.xlsx`(풀스택 bravo팀, API 49개 + 상태코드 시트) 수령.
**`기획/업무분장_스프린트1_작업명세.md`(다른 세션이 작성한 A/B 2인 분장 문서)의 신규
기능 3종 — BudgetPlanner(예산 제안)·DigestWriter(주간 브리핑)·PolicyDrafter 개정
모드(회칙 개정 제안) — 는 49개 API 어디에도 없다. 사용자 확인: "신규 기능 마음대로
추가 금지, 그런 기능(주간 리포트) 없음" → **이 3개는 진행하지 않는다.** 스프린트1
문서의 A1~A7 항목은 폐기, B1~B7(실모드 전환·신뢰성·평가)만 유효하고 그마저 아래
내용으로 갱신됨.

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
- **LangSmith**: 미연동 (키·계정 필요).

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
- **Docker Desktop dockerInference 잠김 (2회 발생)**: `C:\Users\user\AppData\Local\Docker\run\dockerInference`
  파일이 커널 레벨로 잠겨 Docker가 안 뜸. **어떤 삭제 방법도 안 통함 — 재부팅만이 해결책.**
  증상: "The file cannot be accessed by the system" / `ls`에서 `-?????????` 표시.
- **목 임베딩은 의미 없음**: 해시 기반이라 회칙이 인덱싱된 팀에서 rule_auditor가 거의 항상
  "근거 불충분(insufficient)"→escalate. 실키 후 `RELEVANCE_MAX_DISTANCE=0.5` 임계값 재조정 필요.
- **hankyung-docker는 별개 프로젝트**: `C:\Users\user\hankyung-docker` (강의 실습).
  `settings.py`의 `Settings` → `Settings()` 오타 수정 + 포트 8000→8001 변경해줬음. BudgetOps와 무관.

## 6. 남은 작업 (우선순위 순)

1. **실 OpenAI 키 전환** (키 받으면 최우선): `.env`에 `OPENAI_API_KEY=` 채우고 `MOCK_LLM=false`.
   그 다음 ① 골든셋 재실행(LLM 판정 품질 첫 실측) ② rule_auditor 거리 임계값 조정
   ③ 프롬프트 튜닝 ④ 참고 코퍼스 검색 품질 확인 ⑤ Intake Vision OCR 구현(`parse_receipt` 툴).
2. **백엔드 계약 반영**: 필드명·Swagger 받으면 `app/schemas/`와 `backend_client.py`의
   URL·필드명만 교체 (노드 코드 불변이 설계 의도). camelCase면 Pydantic alias 사용.
3. **LangSmith 연동**: 트레이싱 + CI 게이트 (`.env`에 LANGSMITH_* 이미 자리 있음).
4. ~~골든셋 확장~~ → **완료 (2026-07-15)**: 라이터 3종 시나리오 골든셋 17건 추가, 17/17 통과.
   실키 전환 후 LLM 생성 문구 기반 케이스(현재는 목 휴리스틱 기준) 재검토 필요.
5. ~~동시요청·멱등성 스트레스 테스트~~ → **완료 (2026-07-15)**: 같은 expense_id의
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
