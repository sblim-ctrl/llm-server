# BudgetOps LLM 서버

모임(동아리·스터디·친목·동호회·회사) 지출 요청을 AI가 회칙·예산·판례에 근거해
1차 심사하고, 확신 없는 건만 관리자에게 넘기는 멀티 에이전트 시스템.
FastAPI(llm-api) + LangGraph 워커(llm-worker) + Postgres/pgvector(llm-postgres).
설계 근거: `../기획/LLM팀_아키텍처_워크플로우_설계서.md`

## 에이전트 카탈로그

| 에이전트 | 역할 | 엔드포인트 |
|---|---|---|
| 지출 심사 (Intake→분류→3-심사관 병렬→가드레일→Adjudicator) | 승인/반려/에스컬레이션 판정 | `POST /v1/analyze` (비동기 잡) |
| PolicyDrafter | 모임 유형·소개 기반 회칙 초안 생성 (RAG) | `POST /v1/policy-draft` (동기) |
| ReportWriter | 정산 요약 + 다음 예산 활용 추천 | `POST /v1/reports/summary` (비동기 잡) |
| BriefingWriter | 판례 로그 기반 인수인계 브리핑 | `POST /v1/briefings` (비동기 잡) |
| classify_category | 지출 카테고리 자동 분류 (모임 유형별 고정 6개) | 심사 그래프 내부 노드 |

## 빠른 시작 (로컬 개발, Windows)

```powershell
# 1. 의존성 설치 (uv가 .venv 자동 생성, Python 3.12 고정)
cd llm-server              # 반드시 이 폴더 안에서 실행 — 상위 폴더에서 돌리면 uv가 프로젝트를 못 찾음
uv sync

# 2. 환경 파일
copy .env.example .env      # 기본값 = MOCK_LLM/MOCK_BACKEND 켜짐 (키·백엔드 없이 동작)

# 3. DB 기동 (Docker Desktop 필요)
docker compose up -d llm-postgres

# 4. API 서버 (터미널 1) — Windows는 반드시 run_api 사용 (psycopg 비동기 ↔ ProactorEventLoop 비호환 보정)
uv run --active python -m app.run_api

# 5. 워커 (터미널 2) — 심사·문서생성 그래프 실행, DB 폴링
uv run --active python -m app.worker
```

## 내부 검증 대시보드

`http://localhost:8000/ui` — 별도 서버 없이 llm-api가 그대로 서빙하는 단일 HTML 페이지.
4개 탭(지출 심사 / 회칙·예산 초안 / 정산 리포트 / 골든셋 평가)에서 실제 API를 호출해
결과를 눈으로 확인할 수 있다. 팀 내부 개발·디버깅용이며 최종 사용자 화면이 아니다
(사용자 화면은 풀스택 팀의 Next.js).

## MCP 서버

`http://localhost:8000/mcp` — 읽기 전용 툴 4종(`search_rules`, `search_precedents`,
`get_budget_status`, `get_expense_history`)을 Streamable HTTP로 노출. 심사 그래프
내부에서 쓰는 것과 동일한 구현이며, Claude Desktop이나 MCP Inspector로 접속해
디버깅·시연에 사용할 수 있다. 승인/반려 같은 쓰기 툴은 노출하지 않는다(가드레일
우회 방지). 접속 확인: `uv run --active python scripts/smoke_mcp.py`

`/mcp`도 다른 엔드포인트와 동일하게 서비스 토큰이 필요하다. Claude Desktop·MCP
Inspector로 붙을 때는 `Authorization: Bearer <SERVICE_TOKEN>` 헤더를 설정해야 하며,
없으면 `401 invalid service token`이 돌아온다.

## 동작 확인

```powershell
# 심사 잡 생성 (202) — pull 모델 5필드 (PROGRESS §0-2): 지출 상세는 payload에 없고
# 서버가 되물어 조회. 목 모드: expenseId로 eval/fixtures/mock_backend.json에서 상세 조회
curl -X POST http://localhost:8000/v1/analyze `
  -H "Authorization: Bearer dev-service-token-change-me" `
  -H "Content-Type: application/json" `
  -d '{\"jobId\":\"be-job-1\",\"expenseId\":90001,\"organizationId\":9002,\"reviewGoal\":\"회칙·예산·판례에 근거해 심사하라\",\"receiptPath\":\"file://eval/golden/receipts/club-approve-001.png\"}'

# 잡 상태 조회
curl http://localhost:8000/v1/jobs/{job_id} -H "Authorization: Bearer dev-service-token-change-me"
```

전체 컨테이너로 띄우기: `docker compose up --build`

## 테스트·평가

```powershell
uv run pytest -q                                       # 단위 테스트 전체 (가드레일 100% 커버 등)
uv run python eval/run_eval.py                          # 골든셋 회귀 (목 모드) — 정확도·오승인율·Trajectory
$env:MOCK_LLM="false"; uv run python eval/run_eval_real.py  # 골든셋 실모드 실측 (실키·과금 ~$0.3, 판정 P/R·자동처리율 포함)
uv run python eval/upload_langsmith_dataset.py             # 골든셋 → LangSmith Dataset (멱등)
$env:MOCK_LLM="false"; $env:LANGSMITH_TRACING="true"; uv run python eval/run_eval_langsmith.py  # LangSmith Experiment (웹 기록·프롬프트 A/B)
uv run python scripts/smoke_review.py                   # 심사 그래프 E2E 스모크 (DB 불필요)
uv run python scripts/smoke_mcp.py                       # MCP 서버 접속 확인 (API 필요)
uv run python scripts/seed_reference_corpus.py           # PolicyDrafter RAG 참고 문서 인덱싱 (DB 필요, 재실행 가능)
uv run python scripts/seed_demo.py                       # 판례 학습 데모 데이터 4주 시뮬레이션 (DB 필요, 재실행 가능)
uv run python scripts/verify_realmode_proposals.py       # B-8 실모드 검증 하네스 (실키·DB 필요, CI 밖 — 아래 참고)
```

`eval/run_eval.py` 실행 시 `eval/results/golden_run.csv`(엑셀 호환)가 매번 갱신된다.
분석·시각화는 `eval/analysis.ipynb` 참고.

**오승인율 0% 하드 게이트**: 골든셋 중 승인되면 안 되는 건이 하나라도 승인되면
`eval/run_eval.py`가 exit 1로 실패한다 — CI 게이트로 그대로 사용 가능.

## 목(mock) 모드

풀스택 팀과의 연동 방식(필드명·엔드포인트)이 확정되기 전까지 두 스위치로 독립 개발한다 (.env):

| 변수 | true일 때 |
|---|---|
| `MOCK_LLM` | OpenAI 호출 없이 결정적 응답 (비용 0). 키가 비어 있어도 자동으로 이 모드 |
| `MOCK_BACKEND` | 백엔드 API 대신 고정값 반환 + 콜백은 로그로만 출력 |

실연동 시 `.env`만 바꾸면 됨 — 노드 코드는 불변 (`app/tools/backend_client.py`가 경계).

## API 계약 (OpenAPI)

풀스택 팀 공유용 — 우리 API의 엔드포인트·요청/응답 스키마 전체가
[`docs/openapi.json`](docs/openapi.json)에 고정돼 있다(코드 실행 없이 확인 가능).
API를 바꾸면 스펙도 갱신해야 하며, CI가 불일치를 잡는다:

```powershell
uv run python scripts/dump_openapi.py           # API 변경 후 스펙 갱신·커밋
uv run python scripts/dump_openapi.py --check    # 최신성 검사 (CI가 자동 수행)
```

서버 기동 시 대화형 문서도 제공된다: `/docs`(Swagger UI) · `/redoc`.

## 실모드 수동 체크리스트 (A-9/B-8 — 비용 문제로 CI 밖)

`.env`에 `OPENAI_API_KEY` 설정 후, **`.env`의 `MOCK_LLM=true`는 유지**하고
검증 프로세스에만 `MOCK_LLM=false` 환경변수를 주입한다 (전체 pytest는 목 모드에
의존 — .env를 통째로 바꾸면 테스트가 실과금을 시도한다).

개발자 A 몫 (2026-07-20 1차 수행 — 전 항목 통과):

- [x] 회칙 인덱싱(실임베딩) 후 receipt_text 경로 심사 → 3심사관 pass →
      **approve, confidence 0.95, 건당 $0.008** (목표 <$0.05). rule 소견에
      실제 조항 인용 확인
- [x] llm_meta 실측: model/prompt_version/tokens/cost가 콜백·잡 결과에 기록
- [x] Vision(A-6 완료 기준): 실제 영수증 이미지 → 합계 32,000원(품목 합산 아님)·
      날짜·상호·품목 추출 / 노이즈 이미지 → parse_ok=false → escalate 경로
- [x] Digest 실모드(C4): gpt-4o-mini 생성 → 수치 대조 검증 verified=true
      (검증기가 환각 수치를 실제로 1회 차단 — Generator-Evaluator 실증)
- [x] 실판례 루프: escalate 판례 저장 → 동일 청구 재심사에서 의미 검색으로
      인용(warn) 확인 — 실임베딩에서만 가능한 검증
- [x] 마스킹 실전송·LangSmith 트레이스(2026-07-20, 키 수급 후): 실명 포함 청구
      심사 → LangSmith API로 트레이스 역조회 — C9 형식(run_name=review:{job_id},
      tags=[team_id]) 확인, **LLM 전송 프롬프트에 실명 부재·역할 치환 확인**
      (검증도 .env는 LANGSMITH_TRACING=false 유지, 프로세스 주입 방식)
- [x] 개발자 B 몫(B-8, 2026-07-22 실행 — 전 항목 통과): `scripts/verify_realmode_proposals.py`
      실행(exit 0) — ① BudgetPlanner 실모드(cost $0.00019, tokens 781/119, proposal_id 발급)
      ② rule_amendment 실모드(cost $0.00252, tokens 616/98, 제안 1건) +
      `detect_repeated_overrides` 의미 유사 군집 실키 확인(count=4 — 실 임베딩 거리
      0.236~0.355 vs 목 해시 거리 0.669~1.151, **목으론 불가함을 실측으로 증명**)
      ③ jobs 테이블 cost/tokens 실기록 확인 ④ LangSmith API 역조회로
      `proposal_budget:{job_id}`·`proposal_rule_amendment:{job_id}` 둘 다
      `tags=[b8-verify]` 확인. 총 실측 비용 $0.002710

실측에서 나온 수정 3건(전부 이 리포에 반영됨): ① `with_structured_output`은
`method="function_calling"` 필수 — 기본 strict 모드가 `Opinion.figures`(자유 dict)를
400으로 거부 ② `RELEVANCE_MAX_DISTANCE` 0.5→0.65 (실거리 실측: 관련 0.42-0.51 /
무관 0.71+) ③ digest_writer 프롬프트에 필수 표기 형식 명시 (검증기 정합).

## 구조

```
app/
├── main.py               # FastAPI 조립 (라우터·미들웨어·MCP 마운트·/ui, LLM 호출 없음)
├── worker.py              # 잡 폴링 → 그래프 실행 (FOR UPDATE SKIP LOCKED)
├── eval_support.py         # 골든셋 평가 로직 (CLI·GET /v1/eval/golden 공유)
├── mcp_server.py           # FastMCP — 읽기 툴 4종 노출
├── api/                    # analyze, jobs, context, drafts, reports, briefings, precedents, eval, health
├── graphs/
│   ├── review/              # 심사 그래프 — state.py + nodes/ (분류→OCR→3심사관→가드레일→판정→실행→콜백→판례저장)
│   ├── indexing/            # 회칙 인덱싱 파이프라인 (fetch→chunk→embed→upsert, 원자적 버전전환)
│   └── writers/             # PolicyDrafter · ReportWriter · BriefingWriter
├── llm/client.py            # models.yaml 라우팅 + 목 모드 (chat_structured, embed_texts)
├── tools/                   # search_rules/precedents/references(pgvector), budget_calculator(순수),
│                             #   category_catalog(유형별 고정 카탈로그), backend_client(백엔드 경계)
├── middleware/              # 서비스 토큰 인증, 구조화 로깅, PIIMasker
├── schemas/                 # Pydantic 계약 (콜백 스키마 = 풀스택 팀과의 계약)
├── static/dashboard.html    # 내부 검증 대시보드 (/ui)
└── db/                      # psycopg 풀, schema.sql (jobs·context_chunks·precedents)

templates/                  # policy_templates.yaml(유형별 회칙 템플릿), category_catalog.yaml(유형별 카테고리 6개)
reference_docs/              # PolicyDrafter RAG 참고 문서 5종 (실제 규정 관행을 참고해 재구성 — 원문 아님, README 하단 참고)
eval/golden/                # 골든셋 30건 (5개 유형 × 6개 시나리오)
```

## 참고 문서(RAG)에 대한 정직한 안내

`reference_docs/*.txt`는 실제 기관의 공식 회칙 원문이 아니다. 대학 동아리연합회
재정운용세칙, 국세청 경조사비 예규 등 **실제 자료의 일반적인 관행을 조사한 뒤
저작권 문제 없이 직접 재구성해 작성한 예시 자료**다. PolicyDrafter가 생성하는
회칙은 "AI가 제안하는 초안"이며, 실제 모임 정책으로 확정되기 전 관리자 검토를
거치는 것을 전제로 한다. 코드가 보장하는 것은 조항 문구의 법적 완결성이 아니라
회칙에 담긴 숫자·구조(승인 한도 순서, 필수 항목 존재 여부 등)가 심사 로직과
안전하게 맞물린다는 점이다 — 검증은 `verify_draft_pure()`가 담당한다.

## 다음 작업

- [x] 실 OpenAI 키 연결 (`MOCK_LLM=false` + `OPENAI_API_KEY` 설정) — 프롬프트 튜닝
      (2026-07-20 완료, 골든셋 실모드 100%·30/30. 아래 '실모드 수동 체크리스트' 참고)
- [ ] 백엔드 API 계약 확정 반영 (필드명·엔드포인트) — 대기 항목 전체 정리는
      `docs/백엔드_대기항목_정리.md` 참고 (데모 필수 경로 아님)
- [x] LangSmith 트레이싱 연동 (완료, B-4)
- [ ] LangSmith CI 게이트 연동 (Sprint 2)
- [ ] 참고 문서 코퍼스 확장 (유형당 2~3개, 실키로 검색 품질 실측 후 판단)
- [ ] 카테고리 오선택 시 관리자 참고 메모 추가 여부 (팀 논의 중)
- 코드 내 `TODO` 주석이 세부 작업 지점 표시
