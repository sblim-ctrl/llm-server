# BudgetOps LLM 서버

모임(동아리·스터디·친목·동호회·회사) 지출 요청을 AI가 회칙·예산·판례에 근거해
1차 심사하고, 확신 없는 건만 관리자에게 넘기는 멀티 에이전트 시스템.
FastAPI(llm-api) + LangGraph 워커(llm-worker) + Postgres/pgvector(llm-postgres).

## 한눈에 보기

| | |
|---|---|
| **핵심 문제** | 모임 총무가 지출 하나하나를 회칙과 대조하는 수작업. 자동화하면 편하지만, **틀린 승인(오승인)은 돈이 나가고 되돌리기 어렵다** |
| **접근** | 심사관 3종(예산·판례·회칙)이 각각 소견을 내고, 결정론적 가드레일이 LLM 판정을 덮어쓸 수 있는 구조. 확신 없으면 승인하지 않고 사람에게 넘긴다 |
| **검증 규모** | 골든셋 **799건**(8유형 × ~100건) — 실모드 전량 실행 **96.0%**(767/799) |
| **오승인** | 799건 중 **1건**. 원인 조사 결과 프롬프트 결함이 아니라 `temperature=0`에서도 남는 LLM 비결정성으로 판명 |
| **비용** | 심사 건당 평균 **$0.0220** (실모드 799건 총 $17.61) |
| **테스트** | `pytest` 1,915건 수집 / 1,670 passed (2026-09-09 기준) |
| **하드 게이트** | 승인되면 안 되는 건이 하나라도 승인되면 평가 스크립트가 `exit 1` — CI에 그대로 연결 |

읽을 거리:

- **[`eval/results/golden_v2_report.md`](eval/results/golden_v2_report.md)** — 골든셋 v2
  평가 리포트. **정확도를 올리려고 케이스나 프롬프트를 조정하지 않고**, 틀린 케이스와
  그 원인을 그대로 남겼다. "목 모드로는 원리적으로 검증 불가능한 유형이 있다"는 발견과
  오승인 1건의 원인 추적이 핵심.
- **[`PR_HISTORY.md`](PR_HISTORY.md)** — 팀 저장소 PR 94건의 리뷰 이력 보존본. 이 저장소는
  코드만 이전한 개인 사본이라 PR 페이지가 없다(커밋 메시지의 `#107` 같은 참조는 링크되지
  않는다). 리뷰 왕복의 실제 내용은 이 파일에 있다.
- [`LLM팀_아키텍처_워크플로우_설계서_v1.1.md`](LLM팀_아키텍처_워크플로우_설계서_v1.1.md) — 설계 근거
- [`docs/openapi.json`](docs/openapi.json) — API 계약 전문(코드 실행 없이 확인 가능)

## 에이전트 카탈로그

**심사 그래프** — `POST /v1/analyze` (비동기 잡)

```
Intake(영수증 OCR) → 분류 → [예산 · 판례 · 회칙] 3-심사관 병렬 → 가드레일 → Adjudicator
```

| 노드 | 역할 |
|---|---|
| `intake_receipt` | 영수증 이미지/PDF 판독 (Vision). 판독 실패는 `parse_ok=false`로 에스컬레이션 |
| `classify_category` | 지출 카테고리 자동 분류 (전역 9종 고정 ENUM) |
| `budget_auditor` | 잔액·한도 대조 (`budget_calculator`는 순수 함수) |
| `precedent_auditor` | pgvector 의미 검색으로 유사 과거 판례 인용 |
| `rule_auditor` | 회칙 조항 RAG 검색 후 위반 여부 판정 |
| `guardrail_gate` | **결정론적 안전장치** — LLM 판정을 덮어쓴다 (예산 부족은 금액 임계값·회칙 위반을 이긴다) |
| `adjudicate` | 최종 승인/반려/에스컬레이션 |

**문서 생성 에이전트**

| 에이전트 | 역할 | 엔드포인트 |
|---|---|---|
| PolicyDrafter | 모임 유형·소개 기반 회칙 초안 생성 (RAG) | `POST /v1/policy-draft` (동기) |
| ReportWriter | 정산 요약 + 다음 예산 활용 추천 | `POST /v1/reports/summary` |
| BriefingWriter | 판례 로그 기반 인수인계 브리핑 | `POST /v1/briefings` |
| BudgetPlanner | 다음 기수 예산안 제안 | `POST /v1/proposals/budget` |
| RuleAmendment | 반복 번복 패턴 탐지 → 회칙 개정 제안 | `POST /v1/proposals/rule-amendment` |
| DigestWriter | 기간 요약 다이제스트 | `POST /v1/digests` |
| DashboardWriter | 대시보드 요약 문구 | `POST /v1/dashboard/summary` |

전체 라우트 23개는 [`docs/openapi.json`](docs/openapi.json) 참고. 프롬프트는
`prompts/{agent}/{version}.yaml`로 버전 관리하며, 기본 버전과 승격 근거는
`app/llm/prompts.py`의 `DEFAULT_VERSIONS` 주석에 실측치와 함께 기록돼 있다.

## 빠른 시작 (로컬 개발)

> **API 키 없이도 전 기능이 돈다.** 기본값이 목(mock) 모드라 `.env`만 복사하면
> OpenAI 키·백엔드 없이 결정적 응답으로 심사·문서생성이 동작한다. 실연동은 §목 모드 참고.

uv 미설치라면 먼저 설치한다 — macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
· Windows PowerShell: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

> pip만 쓰는 환경이라면 `pip install -r requirements.txt`로도 설치할 수 있다
> (`uv.lock` 기준으로 고정한 런타임 의존성 목록).

```bash
# 1. 의존성 설치 (uv가 .venv 자동 생성, Python 3.12 고정)
cd llm-server              # 반드시 이 폴더 안에서 실행 — 상위 폴더에서 돌리면 uv가 프로젝트를 못 찾음
uv sync

# 2. 환경 파일 — 기본값 = MOCK_LLM/MOCK_BACKEND 켜짐 (키·백엔드 없이 동작)
cp .env.example .env        # Windows PowerShell: copy .env.example .env

# 3. DB 기동 (Docker 필요)
docker compose up -d llm-postgres

# 4. API 서버 (터미널 1) — 모든 OS 공통. run_api가 psycopg 비동기 ↔ 이벤트 루프 보정을
#    처리한다 (Windows는 ProactorEventLoop 비호환 때문에 이 방식이 필수)
uv run --active python -m app.run_api

# 5. 워커 (터미널 2) — 심사·문서생성 그래프 실행, DB 폴링
uv run --active python -m app.worker
```

전체 컨테이너로 띄우기: `docker compose up --build`

### 동작 확인

```powershell
# 심사 잡 생성 (202) — pull 모델 5필드: 지출 상세는 payload에 없고 서버가 되물어 조회.
# 목 모드에서는 expenseId로 eval/fixtures/mock_backend.json에서 상세를 가져온다
curl -X POST http://localhost:8000/v1/analyze `
  -H "Authorization: Bearer dev-service-token-change-me" `
  -H "Content-Type: application/json" `
  -d '{\"jobId\":\"be-job-1\",\"expenseId\":90001,\"organizationId\":9002,\"reviewGoal\":\"회칙·예산·판례에 근거해 심사하라\",\"receiptPath\":\"file://eval/golden/receipts/club-approve-001.png\"}'

# 잡 상태 조회
curl http://localhost:8000/v1/jobs/{job_id} -H "Authorization: Bearer dev-service-token-change-me"
```

### 내부 검증 대시보드

`http://localhost:8000/ui` — 별도 서버 없이 llm-api가 그대로 서빙하는 단일 HTML 페이지.
4개 탭(지출 심사 / 회칙·예산 초안 / 정산 리포트 / 골든셋 평가)에서 실제 API를 호출해
결과를 눈으로 확인할 수 있다. 팀 내부 개발·디버깅용이며 최종 사용자 화면이 아니다
(사용자 화면은 풀스택 팀의 Next.js).

## 테스트·평가

```powershell
uv run pytest -q                                        # 단위 테스트 전체 (가드레일 100% 커버 등)

# 골든셋 v2 — 8유형 799건 (현행 주 평가셋)
uv run python eval/run_eval_v2.py                       # 목 모드
$env:MOCK_LLM="false"; uv run python eval/run_eval_v2_real.py   # 실모드 (실키·과금 ~$17.6)

# 골든셋 v1 — 97건 (회귀 감시용으로 유지)
uv run python eval/run_eval.py                          # 목 모드 — 정확도·오승인율·Trajectory
$env:MOCK_LLM="false"; uv run python eval/run_eval_real.py      # 실모드 (~$0.3)

# LangSmith
uv run python eval/upload_langsmith_dataset.py          # 골든셋 → Dataset (멱등)
$env:MOCK_LLM="false"; $env:LANGSMITH_TRACING="true"; uv run python eval/run_eval_langsmith.py

# 스모크·시드
uv run python scripts/smoke_review.py                   # 심사 그래프 E2E (DB 불필요)
uv run python scripts/smoke_mcp.py                      # MCP 서버 접속 확인 (API 필요)
uv run python scripts/seed_reference_corpus.py          # PolicyDrafter RAG 참고 문서 인덱싱 (DB 필요)
uv run python scripts/seed_demo.py                      # 판례 학습 데모 4주 시뮬레이션 (DB 필요)
uv run python scripts/verify_realmode_proposals.py      # B-8 실모드 검증 하네스 (실키·DB 필요, CI 밖)
```

**오승인율 0% 하드 게이트**: 골든셋 중 승인되면 안 되는 건이 하나라도 승인되면
평가 스크립트가 exit 1로 실패한다 — CI 게이트로 그대로 사용 가능.

`eval/run_eval.py` 실행 시 `eval/results/golden_run.csv`(엑셀 호환)가 매번 갱신된다.
분석·시각화는 `eval/analysis.ipynb` 참고.

### 실측 결과

| 평가셋 | 목 모드 | 실모드 |
|---|---|---|
| v2 (8유형 799건) | 83.6% | **96.0%** (767/799) · 오승인 1건 · 건당 $0.0220 |
| v1 (97건) | 100% · 오승인 0 · Trajectory 66/66 · 분류 90.7% | 100% |

**목 모드로는 검증할 수 없는 유형이 있다**는 것이 v2 확장의 핵심 발견이다 —
`circumvention`(회피 시도)은 목 0% → 실 100%, `notation_variant`(표기 변형) 분류는
목 10% → 실 77%. 목 응답이 결정적이라 이 축들을 원리적으로 흉내 낼 수 없기 때문이다.
상세는 [`eval/results/golden_v2_report.md`](eval/results/golden_v2_report.md).

## 목(mock) 모드

풀스택 팀과의 연동 방식(필드명·엔드포인트)이 확정되기 전까지 두 스위치로 독립 개발한다 (.env):

| 변수 | true일 때 |
|---|---|
| `MOCK_LLM` | OpenAI 호출 없이 결정적 응답 (비용 0). 키가 비어 있어도 자동으로 이 모드 |
| `MOCK_BACKEND` | 백엔드 API 대신 고정값 반환 + 콜백은 로그로만 출력 |

실연동 시 `.env`만 바꾸면 됨 — 노드 코드는 불변 (`app/tools/backend_client.py`가 경계).
필요한 키는 `OPENAI_API_KEY` 하나다 (모델 라우팅이 전부 OpenAI — `models.yaml`. ANTHROPIC
키는 쓰지 않는다). LangSmith 트레이싱은 선택이며 `LANGSMITH_API_KEY`로 켠다.

## API 계약 (OpenAPI)

풀스택 팀 공유용 — 우리 API의 엔드포인트·요청/응답 스키마 전체가
[`docs/openapi.json`](docs/openapi.json)에 고정돼 있다(코드 실행 없이 확인 가능).
API를 바꾸면 스펙도 갱신해야 하며, 배포 전 점검(`scripts/predeploy_check.py`)이 불일치를 잡는다:

```powershell
uv run python scripts/dump_openapi.py            # API 변경 후 스펙 갱신·커밋
uv run python scripts/dump_openapi.py --check    # 최신성 검사 (predeploy_check 1번 항목)
```

서버 기동 시 대화형 문서도 제공된다: `/docs`(Swagger UI) · `/redoc`.

## MCP 서버

`http://localhost:8000/mcp` — 읽기 전용 툴 4종(`search_rules`, `search_precedents`,
`get_budget_status`, `get_expense_history`)을 Streamable HTTP로 노출. 심사 그래프
내부에서 쓰는 것과 동일한 구현이며, Claude Desktop이나 MCP Inspector로 접속해
디버깅·시연에 사용할 수 있다. **승인/반려 같은 쓰기 툴은 노출하지 않는다**(가드레일
우회 방지). 접속 확인: `uv run --active python scripts/smoke_mcp.py`

`/mcp`도 다른 엔드포인트와 동일하게 서비스 토큰이 필요하다. Claude Desktop·MCP
Inspector로 붙을 때는 `Authorization: Bearer <SERVICE_TOKEN>` 헤더를 설정해야 하며,
없으면 `401 invalid service token`이 돌아온다.

## 구조

```
app/
├── main.py                # FastAPI 조립 (라우터·미들웨어·MCP 마운트·/ui, LLM 호출 없음)
├── worker.py              # 잡 폴링 → 그래프 실행 (FOR UPDATE SKIP LOCKED)
├── eval_support.py        # 골든셋 평가 로직 (CLI·GET /v1/eval/golden 공유)
├── mcp_server.py          # FastMCP — 읽기 툴 4종 노출
├── api/                   # 라우터 15개 — analyze, jobs, context, drafts, reports, briefings,
│                          #   proposals, digests, dashboards, precedents, categories,
│                          #   policy, reviews_stream(SSE), eval, health
├── graphs/
│   ├── review/            # 심사 그래프 — state.py + nodes/ (분류→OCR→3심사관→가드레일→판정→실행→콜백→판례저장)
│   ├── indexing/          # 회칙 인덱싱 파이프라인 (fetch→chunk→embed→upsert, 원자적 버전전환)
│   └── writers/           # policy_draft · report · briefing · budget_planner ·
│                          #   rule_amendment · digest · dashboard
├── llm/
│   ├── client.py          # models.yaml 라우팅 + 목 모드 (chat_structured, embed_texts)
│   └── prompts.py         # DEFAULT_VERSIONS — 프롬프트 승격 근거를 실측치와 함께 주석으로 기록
├── tools/                 # search_rules/precedents/references(pgvector), budget_calculator(순수),
│                          #   category_catalog, backend_client(백엔드 경계)
├── middleware/            # 서비스 토큰 인증, 구조화 로깅, PIIMasker
├── schemas/               # Pydantic 계약 (콜백 스키마 = 풀스택 팀과의 계약)
├── static/dashboard.html  # 내부 검증 대시보드 (/ui)
└── db/                    # psycopg 풀, schema.sql (jobs·context_chunks·precedents)

prompts/{agent}/{version}.yaml   # 에이전트 15종 × 버전별 프롬프트
templates/                       # policy_templates.yaml(유형별 회칙 템플릿),
                                 #   category_catalog.yaml(전역 카테고리 9종)
reference_docs/                  # PolicyDrafter RAG 참고 문서 5종 (재구성 자료 — 아래 참고)
eval/golden/golden_v2/           # 골든셋 v2 — 8유형 799건 (유형별 파일)
eval/golden/golden_v1.json       # 골든셋 v1 97건 (회귀 감시용) + writers·rule_axis 골든셋
```

## 샘플 데이터 출처

평가·시연에 쓰는 데이터는 전부 팀이 자체 제작했으며 외부 저작물을 포함하지 않는다.

- `eval/golden/golden_v2/*.json`(799건)·`eval/golden/golden_v1.json`(97건)·
  `eval/golden/writers_golden_v1.json`·`eval/golden/golden_rule_axis.json` —
  심사·문서생성 골든셋. v2는 `scripts/golden_v2/`의 유형별 생성기로 만들었고,
  시나리오와 기대 판정은 직접 설계했다.
- `eval/fixtures/mock_backend.json` — 목 모드용 백엔드 응답 픽스처(가상 조직·지출).
- `eval/golden/receipts/*.png` — `scripts/generate_golden_receipts.py`가 PIL로 렌더한
  **합성 영수증 이미지**다(실제 영수증이 아니라 `mock_backend.json`의 금액·날짜에 맞춰 그린 것).
- `reference_docs/*.txt` — 아래 「참고 문서(RAG)에 대한 정직한 안내」 참고.

## 참고 문서(RAG)에 대한 정직한 안내

`reference_docs/*.txt`는 실제 기관의 공식 회칙 원문이 아니다. 대학 동아리연합회
재정운용세칙, 국세청 경조사비 예규 등 **실제 자료의 일반적인 관행을 조사한 뒤
저작권 문제 없이 직접 재구성해 작성한 예시 자료**다. PolicyDrafter가 생성하는
회칙은 "AI가 제안하는 초안"이며, 실제 모임 정책으로 확정되기 전 관리자 검토를
거치는 것을 전제로 한다. 코드가 보장하는 것은 조항 문구의 법적 완결성이 아니라
회칙에 담긴 숫자·구조(승인 한도 순서, 필수 항목 존재 여부 등)가 심사 로직과
안전하게 맞물린다는 점이다 — 검증은 `verify_draft_pure()`가 담당한다.

## 실모드 수동 체크리스트 (비용 문제로 CI 밖)

<details>
<summary>실키로만 검증 가능한 항목 — 2026-07-20/22 수행, 전 항목 통과 (펼치기)</summary>

`.env`에 `OPENAI_API_KEY` 설정 후, **`.env`의 `MOCK_LLM=true`는 유지**하고
검증 프로세스에만 `MOCK_LLM=false` 환경변수를 주입한다 (전체 pytest는 목 모드에
의존 — .env를 통째로 바꾸면 테스트가 실과금을 시도한다).

**A-9 몫 (2026-07-20)**

- [x] 회칙 인덱싱(실임베딩) 후 receipt_text 경로 심사 → 3심사관 pass →
      **approve, confidence 0.95, 건당 $0.008** (목표 <$0.05). rule 소견에
      실제 조항 인용 확인
- [x] llm_meta 실측: model/prompt_version/tokens/cost가 콜백·잡 결과에 기록
- [x] Vision: 실제 영수증 이미지 → 합계 32,000원(품목 합산 아님)·날짜·상호·품목 추출 /
      노이즈 이미지 → parse_ok=false → escalate 경로
- [x] Digest 실모드: gpt-4o-mini 생성 → 수치 대조 검증 verified=true
      (검증기가 환각 수치를 실제로 1회 차단 — Generator-Evaluator 실증)
- [x] 실판례 루프: escalate 판례 저장 → 동일 청구 재심사에서 의미 검색으로
      인용(warn) 확인 — 실임베딩에서만 가능한 검증
- [x] 마스킹 실전송·LangSmith 트레이스: 실명 포함 청구 심사 → LangSmith API로
      트레이스 역조회 — `run_name=review:{job_id}`, `tags=[team_id]` 확인,
      **LLM 전송 프롬프트에 실명 부재·역할 치환 확인**

**B-8 몫 (2026-07-22)** — `scripts/verify_realmode_proposals.py` 실행(exit 0)

- [x] ① BudgetPlanner 실모드(cost $0.00019, tokens 781/119, proposal_id 발급)
- [x] ② rule_amendment 실모드(cost $0.00252, tokens 616/98, 제안 1건) +
      `detect_repeated_overrides` 의미 유사 군집 실키 확인(count=4 — 실 임베딩 거리
      0.236~0.355 vs 목 해시 거리 0.669~1.151, **목으론 불가함을 실측으로 증명**)
- [x] ③ jobs 테이블 cost/tokens 실기록 확인
- [x] ④ LangSmith API 역조회로 `proposal_budget:{job_id}`·
      `proposal_rule_amendment:{job_id}` 둘 다 `tags=[b8-verify]` 확인
- 총 실측 비용 $0.002710

**실측에서 나온 수정 3건** (전부 이 리포에 반영됨)

1. `with_structured_output`은 `method="function_calling"` 필수 — 기본 strict 모드가
   `Opinion.figures`(자유 dict)를 400으로 거부
2. `RELEVANCE_MAX_DISTANCE` 0.5 → 0.65 (실거리 실측: 관련 0.42-0.51 / 무관 0.71+).
   이후 조항 라벨 82건 실측을 근거로 **0.75로 재조정** — 현행값은
   `app/graphs/review/nodes/rule_auditor.py:57`
3. `digest_writer` 프롬프트에 필수 표기 형식 명시 (검증기 정합)

</details>

## 알려진 한계·다음 작업

- [x] 실 OpenAI 키 연결 + 프롬프트 튜닝 — 골든셋 v1 실모드 100%, v2 실모드 96.0%
- [x] LangSmith 트레이싱 연동
- [ ] **오승인 1건(`v2-rule_conflict-091`)** — `temperature=0`에서도 남는 LLM 비결정성이
      원인으로 확인됐다. 재실행하면 기대값을 재현하므로 프롬프트 수정으로는 못 막는다.
      다수결 투표나 재시도 전략이 필요한 자리.
- [ ] **`notation_variant` 분류 정확도 77%** — 8유형 중 유일하게 낮다. 표기 변형
      (단위·띄어쓰기·약어)에서 카테고리를 놓친다.
- [ ] 백엔드 API 계약 확정 반영 (필드명·엔드포인트) — 데모 필수 경로 아님
- [ ] LangSmith CI 게이트 연동
- [ ] 참고 문서 코퍼스 확장 (유형당 2~3개, 실키로 검색 품질 실측 후 판단)
- 코드 내 `TODO` 주석이 세부 작업 지점 표시
