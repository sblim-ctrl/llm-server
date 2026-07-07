# BudgetOps LLM 서버

모임 지출 요청을 AI가 회칙·예산·판례에 근거해 1차 심사하는 에이전트 서버.
FastAPI(llm-api) + LangGraph 워커(llm-worker) + Postgres/pgvector(llm-postgres).
설계 근거: `../기획/LLM팀_아키텍처_워크플로우_설계서.md`

## 빠른 시작 (로컬 개발)

```powershell
# 1. 의존성 설치 (uv가 .venv 자동 생성)
uv sync

# 2. 환경 파일
copy .env.example .env      # 기본값 = MOCK_LLM/MOCK_BACKEND 켜짐 (키·백엔드 없이 동작)

# 3. DB 기동 (Docker)
docker compose up -d llm-postgres

# 4. API 서버 (터미널 1) — Windows는 반드시 run_api 사용 (이벤트 루프 보정)
uv run python -m app.run_api

# 5. 워커 (터미널 2)
uv run python -m app.worker
```

동작 확인:

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

## 테스트

```powershell
uv run pytest                                    # 가드레일·예산계산 단위 테스트
uv run python scripts/smoke_review.py            # 심사 그래프 E2E 스모크 (DB 불필요)
```

## 목(mock) 모드

풀스택 팀과의 연동 방식이 확정되기 전까지 두 스위치로 독립 개발한다 (.env):

| 변수 | true일 때 |
|---|---|
| `MOCK_LLM` | OpenAI 호출 없이 결정적 응답 (비용 0) |
| `MOCK_BACKEND` | 백엔드 API 대신 고정값 반환 + 콜백은 로그로만 출력 |

실연동 시 `.env`만 바꾸면 됨 — 노드 코드는 불변 (`app/tools/backend_client.py`가 경계).

## 구조 (설계서 §11.1)

```
app/
├── main.py            # FastAPI 조립 (라우터·미들웨어만, LLM 호출 없음)
├── worker.py          # 잡 폴링 → 그래프 실행 (FOR UPDATE SKIP LOCKED)
├── api/               # /v1/analyze, /v1/jobs, /v1/context/refresh, /healthz
├── graphs/review/     # 심사 그래프 — state.py + nodes/ (1파일 1책임)
├── llm/client.py      # models.yaml 라우팅 + 목 모드
├── tools/             # budget_calculator(순수), backend_client(백엔드 경계)
├── middleware/        # 서비스 토큰 인증, 구조화 로깅
├── schemas/           # Pydantic 계약 (콜백 스키마 = 풀스택 팀과의 계약)
└── db/                # psycopg 풀, schema.sql (jobs·context_chunks·precedents)
```

## 다음 작업 (로드맵 §11.3 기준)

- [ ] 2주차: PostgresSaver checkpointer, 컨텍스트 인덱싱 파이프라인, alembic
- [ ] 3주차: Intake Vision OCR 실구현, rule_auditor RAG(search_rules), 골든셋 30건
- [ ] 4주차: 판례 검색(search_precedents)·저장 루프, LangSmith CI 게이트
- [ ] 5주차: PolicyDrafter·ReportWriter·BriefingWriter, FastMCP 서버
- 코드 내 `TODO(n주차)` 주석이 작업 지점 표시
