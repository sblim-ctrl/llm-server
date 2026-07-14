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

## 동작 확인

```powershell
# 심사 잡 생성 (202 + job_id)
curl -X POST http://localhost:8000/v1/analyze `
  -H "Authorization: Bearer dev-service-token-change-me" `
  -H "Content-Type: application/json" `
  -d '{\"expense_id\":\"exp-1\",\"team_id\":\"team-1\",\"claim\":{\"title\":\"교재 구입\",\"amount\":32000,\"category\":\"도서\",\"date\":\"2026-07-07\",\"description\":\"스터디 교재\"},\"receipt_signed_url\":\"https://example.com/r1\"}'

# 잡 상태 조회
curl http://localhost:8000/v1/jobs/{job_id} -H "Authorization: Bearer dev-service-token-change-me"
```

전체 컨테이너로 띄우기: `docker compose up --build`

## 테스트·평가

```powershell
uv run pytest -q                                       # 단위 테스트 전체 (가드레일 100% 커버 등)
uv run python eval/run_eval.py                          # 골든셋 30건 회귀 — 정확도·오승인율·Trajectory
uv run python scripts/smoke_review.py                   # 심사 그래프 E2E 스모크 (DB 불필요)
uv run python scripts/smoke_mcp.py                       # MCP 서버 접속 확인 (API 필요)
uv run python scripts/seed_reference_corpus.py           # PolicyDrafter RAG 참고 문서 인덱싱 (DB 필요, 재실행 가능)
uv run python scripts/seed_demo.py                       # 판례 학습 데모 데이터 4주 시뮬레이션 (DB 필요, 재실행 가능)
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

- [ ] 실 OpenAI 키 연결 (`MOCK_LLM=false` + `OPENAI_API_KEY` 설정) — 프롬프트 튜닝
- [ ] 백엔드 API 계약 확정 반영 (필드명·엔드포인트)
- [ ] LangSmith 트레이싱·CI 게이트 연동
- [ ] 참고 문서 코퍼스 확장 (유형당 2~3개, 실키로 검색 품질 실측 후 판단)
- [ ] 카테고리 오선택 시 관리자 참고 메모 추가 여부 (팀 논의 중)
- 코드 내 `TODO` 주석이 세부 작업 지점 표시
