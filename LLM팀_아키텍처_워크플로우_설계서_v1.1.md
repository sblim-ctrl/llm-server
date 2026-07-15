# BudgetOps — LLM 에이전트 아키텍처·워크플로우 설계서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.1 (2026-07-09) |
| 작성 | LLM 에이전트 개발팀 |
| 근거 문서 | `요구사항정의서_LLM제안.xlsx`, `풀스택_협의_회의자료_LLM팀.md`, 화면목업 v2, `BudgetOps_차별화전략_vs_AssoAI.md`(v2) + 차별화 목업 3종 |
| 대상 독자 | LLM 팀(구현 기준), 풀스택 팀(인터페이스 계약 확인) |

> **v1.1 변경 요약 (AssoAI 차별화 전략 반영, 2026-07-09)**
> ① **BudgetPlanner**(예산 조정 제안)·**DigestWriter**(대시보드 AI 총무 브리핑) 그래프 추가 ② **PolicyDrafter에 '회칙 개정 제안' 모드** 추가 (판례 기반) ③ 심사 그래프 **dry-run 모드**(사전 문의, P2) ④ 카테고리 분류는 별도 Classifier 노드 없이 **Intake에 통합** (REQ-012 기반영, 지출 폼 카테고리 선택사항화) ⑤ UI 용어 규칙: override → **'AI와 다른 결정'** ⑥ `proposals` 테이블, 엔드포인트 4종, 콜백 필드(`category_assigned`·`dry_run`) 추가.
> **기존 병렬 3심사관·가드레일·판례 루프는 무변경** — 차별화의 본체이므로 유지. 변경 표시는 [v1.1], 상세 근거는 ADR-7~9.

---

## 1. 개요와 설계 목표

BudgetOps는 모임(동아리·스터디·회사 등)의 지출 요청을 **AI가 회칙·예산·과거 판례 컨텍스트에 근거해 1차 심사**하고, 확신이 없는 건만 관리자에게 에스컬레이션하는 서비스다. LLM 에이전트는 "의견을 다는 참고인"이 아니라 **승인/반려의 실행 주체**이며, 그만큼 안전장치(금액 가드레일, fail-safe 에스컬레이션, 전 판정 감사로그)를 아키텍처 수준에서 보장한다.

### 1.1 에이전트가 담당하는 기능 (요구사항 매핑)

| 기능 | 관련 REQ | 에이전트 역할 |
|---|---|---|
| 지출 자동 심사 | REQ-012·014·015·016·028·038·039 | 영수증 OCR → 병렬 심사 → 승인/반려/에스컬레이션 |
| 예산안 기획·에이전트 설정 | REQ-004·036 | 온보딩 마법사에서 유형별 예산 템플릿·회칙 초안 생성 |
| 컨텍스트 관리 | REQ-035·041 | 회칙·정책 버전별 재인덱싱 (RAG 인덱스) |
| 판례 학습 루프 | REQ-042 | 관리자 결정을 임베딩 저장 → 유사 사례 검색에 재사용 |
| 문서 생성 | REQ-019·020·043 | 정산 리포트 AI 요약, 인수인계 브리핑 |
| 대시보드 AI 브리핑 [v1.1] | REQ-009, REQ-045(안) | DigestWriter — 자동 처리 현황·예산 소진 예측·이상 징후 주간 요약 |
| 예산 조정 제안 [v1.1] | REQ-022·041, REQ-044(안) | BudgetPlanner — 소진 예측(코드)+조정안(LLM), 수락 실행은 백엔드 CRUD 경유 |
| 회칙 개정 제안 [v1.1] | REQ-035·041·042 | PolicyDrafter 개정 모드 — 판례 기반 회칙-실운영 갭 개정안 |
| 사전 문의 심사 [v1.1] | REQ-046(안) | 심사 그래프 dry-run — 실행·판례 저장 없이 소견만 반환 |

### 1.2 평가요소 ↔ 설계 매핑

| 평가요소 | 이 문서의 대응 |
|---|---|
| 1. 주제 선정 — 목적성·필요성 | §1: 승인 주체로서의 에이전트, 안전장치 전제 |
| 2. 멀티 에이전트·병렬 시스템 / 성능 평가 | §3 병렬 심사 패널, §9 LangSmith 골든셋 평가 |
| 3. 하네스 — 스킬·툴(MCP), 단일책임 노드·미들웨어 | §4 LangGraph 노드 설계, §5 툴·MCP·프롬프트 버전 관리 |
| 4. 모델 배포 — FastAPI 안정성, Docker | §10 배포 설계 |
| 5. 협업·문서화 | §7 API 계약, §11 GitHub·Jira·ADR |
| 6. 유지보수·확장성 | §12 확장 포인트, 부록 A ADR |

### 1.3 확정된 기술 결정 (ADR 요약 — 상세는 부록 A)

| # | 결정 | 선택 | 핵심 근거 |
|---|---|---|---|
| ADR-1 | LLM 제공자 | OpenAI GPT-4o 계열 | Vision(영수증 OCR)까지 단일 API, 심사는 gpt-4o / 분류·요약은 gpt-4o-mini 라우팅 |
| ADR-2 | 벡터 저장소·checkpointer | Postgres + pgvector 단일 | 컨테이너 1개로 checkpointer·벡터·판례·잡 테이블 통합, 운영 부담 최소 |
| ADR-3 | 성능 평가 | LangSmith + 골든셋 | LangGraph 네이티브 트레이싱, 데이터셋 회귀 평가, LLM-as-Judge |
| ADR-4 | 비동기 잡 처리 | Postgres 잡 테이블 + 전용 워커 프로세스 | Redis/Celery 없이 재시도·상태 추적 가능, 확장 시 교체 경로 명시(§12) |
| ADR-5 | 문서화 | Markdown + Mermaid, 리포 커밋 | PR 리뷰로 계약 변경 추적 |

---

## 2. 시스템 아키텍처

### 2.1 컨테이너 구성도

```mermaid
flowchart LR
    subgraph Client
        FE[Next.js 프론트엔드]
    end

    subgraph FullStack["풀스택 팀 영역"]
        BE[Spring 백엔드<br/>인증·RBAC·트랜잭션]
        MainDB[(메인 DB<br/>지출·예산·회칙 원문·감사로그)]
        GCS[(GCS<br/>영수증 파일)]
    end

    subgraph LLMTeam["LLM 팀 영역 (FastAPI)"]
        API[llm-api<br/>FastAPI 게이트웨이]
        Worker[llm-worker<br/>LangGraph 실행기]
        LLMDB[(llm-postgres + pgvector<br/>잡·checkpointer·임베딩·판례)]
    end

    OpenAI[OpenAI API<br/>gpt-4o / gpt-4o-mini / embeddings]
    LS[LangSmith<br/>트레이싱·평가]

    FE --> BE
    BE -- "POST /analyze (job 생성)" --> API
    BE -- "컨텍스트 갱신 이벤트" --> API
    API --> LLMDB
    Worker --> LLMDB
    Worker -- "영수증 Signed URL" --> GCS
    Worker -- "예산·지출 조회 (읽기 API)" --> BE
    Worker -- "콜백 + Agent 승인 API" --> BE
    Worker --> OpenAI
    Worker -.-> LS
    API -.-> LS
```

### 2.2 컴포넌트 책임

| 컴포넌트 | 책임 | 하지 않는 것 |
|---|---|---|
| **llm-api** (FastAPI) | 요청 수신·검증·인증(서비스 토큰), 잡 등록, 잡 상태 조회, 헬스체크, MCP 서버 마운트 | LLM 호출 (그래프 실행은 워커에 위임) |
| **llm-worker** | 잡 폴링, LangGraph 그래프 실행, 콜백 발송, 재시도·타임아웃 관리 | HTTP 요청 수신 |
| **llm-postgres** | `jobs`, LangGraph checkpointer, `context_chunks`(pgvector), `precedents`, `prompt_versions` | 지출·예산 원본 (소유권은 메인 DB) |
| **Spring 백엔드** | 인증·RBAC, 지출 상태 머신, 예산 차감 트랜잭션(REQ-015·023), 감사로그, 알림 | LLM 호출 |

API 서버와 워커는 **같은 Docker 이미지, 다른 entrypoint**로 실행한다. 코드 중복 없이 수평 확장 시 워커만 늘릴 수 있다.

### 2.3 데이터 경계 (회의 합의 사항 반영)

| 데이터 | 소유 | 비고 |
|---|---|---|
| 지출·예산·멤버·역할 | 메인 DB (풀스택) | LLM 팀은 읽기 API로만 접근 |
| 회칙·정책 **원문 + 버전** | 메인 DB (풀스택) | 변경 시 REQ-041 이벤트 발행 |
| 회칙 **임베딩 인덱스** | llm-postgres (LLM) | `rule_version`으로 원문과 동기화 |
| 판례(결정 로그) | llm-postgres (LLM) | REQ-042. 백엔드 감사로그에는 판정 요약만 중복 기록 |
| AI 판정 결과 스냅샷 | 메인 DB `expenses.agent_result` | 화면 표시용. 원본 트레이스는 LangSmith |
| 영수증 파일 | GCS (풀스택) | LLM 팀은 Signed URL로 시한부 접근 (REQ-025) |

**원칙: LLM 서버는 메인 DB에 직접 접속하지 않는다.** 모든 상태 변경은 백엔드 API(Agent 서비스 계정)를 경유해 트랜잭션·동시성 제어·감사로그를 재사용한다(REQ-038). 이 경계 덕분에 양팀은 API 계약(§7)만 지키면 독립 배포·독립 스케일이 가능하다.

---

## 3. 멀티 에이전트 설계

### 3.1 에이전트 카탈로그

역할이 다른 에이전트를 그래프 노드로 분리하고, 심사 계열은 **병렬(fan-out) 실행**한다.

| 에이전트 | 유형 | 모델 | 책임 (단일) |
|---|---|---|---|
| **Intake** | 전처리 | gpt-4o (Vision) | 영수증 OCR: 금액·날짜·상호·품목 추출 + **카테고리 자동 분류(REQ-012)** [v1.1], 청구 내용과 대조(REQ-028) |
| **RuleAuditor** (회칙 심사관) | 병렬 심사 | gpt-4o | 회칙 RAG 검색 → 위반 여부·근거 조항 판정 |
| **BudgetAuditor** (예산 심사관) | 병렬 심사 | gpt-4o-mini + 결정적 계산 | 카테고리 한도·잔액·기간 사용률 검사. 수치 계산은 툴(코드)로, LLM은 해석만 |
| **PrecedentAuditor** (판례·이상탐지 심사관) | 병렬 심사 | gpt-4o | 유사 판례 검색(pgvector), 중복 청구·패턴 이상 탐지 |
| **Adjudicator** (판정 합성) | 합류 | gpt-4o + 결정적 가드레일 | 3개 소견 종합 → verdict·confidence·사유(요청자용/관리자용) 생성 |
| **PolicyDrafter** | 독립 그래프 | gpt-4o | ①마법사 "AI 초안" — 모임 유형 기반 회칙·예산 템플릿(REQ-036) ②[v1.1] 개정 모드 — 판례 기반 회칙 개정 제안(§4.4-e) |
| **ReportWriter** | 독립 그래프 | gpt-4o-mini | 정산 리포트 AI 요약(REQ-019), 집계 수치는 백엔드 API 결과를 그대로 사용 |
| **BriefingWriter** | 독립 그래프 | gpt-4o | 인수인계 브리핑 — 판례 로그 기반, 회칙 vs 실운영 갭 분석, 익명화(REQ-043) |
| **BudgetPlanner** [v1.1] | 독립 그래프 | gpt-4o-mini + 결정적 계산 | 예산 소진 예측(코드)·카테고리 조정 제안 — 대시보드 예측, 예산 탭 제안 카드, 리포트 "다음 달 예산 제안" 공용(§4.4-d) |
| **DigestWriter** [v1.1] | 독립 그래프 | gpt-4o-mini | 대시보드 "AI 총무 브리핑" 주간 생성 — 자동 처리 현황·소진 예측·이상 징후 요약(§4.4-c) |
| **Indexer** | 파이프라인(비 LLM) | embeddings | REQ-041 이벤트 수신 → 청크·임베딩·버전 태깅 |

> 모델 라우팅 원칙: **판단이 필요한 곳은 gpt-4o, 요약·분류·해석은 gpt-4o-mini.** 라우팅은 설정 파일(`models.yaml`)로 관리해 코드 수정 없이 교체 가능(§12).

> [v1.1] 카테고리 분류용 **별도 Classifier 노드는 두지 않는다** — REQ-012 정책("제출 시 LLM이 금액/카테고리 자동 추출")을 Intake가 이미 수행. 지출 폼의 카테고리는 선택사항(미선택 시 AI 분류)이며, 최종 분류는 콜백 `category_assigned`로 반환한다(ADR-7).

### 3.2 왜 병렬 3-심사관 구조인가

- **관심사 분리**: 회칙 해석(비정형 텍스트 추론), 예산 검사(수치·결정적), 이상 탐지(유사도 검색)는 요구하는 컨텍스트·프롬프트·툴이 서로 다르다. 단일 프롬프트에 합치면 컨텍스트가 비대해지고 실패 원인 추적이 불가능해진다.
- **지연시간**: 3개 심사를 순차 실행하면 p95가 3배로 늘어난다. LangGraph의 fan-out으로 동시 실행해 전체 지연을 가장 느린 심사관 1개 수준으로 유지한다.
- **부분 실패 격리**: 심사관 1개가 실패해도 나머지 소견은 보존되고, Adjudicator가 "소견 불충분 → ESCALATED"로 안전하게 수렴한다(§8).
- **평가 용이성**: 심사관별 골든셋을 분리해 성능을 독립 측정·개선할 수 있다(§9).

### 3.3 판정 합성 규칙 (Adjudicator)

합성은 2단계다. **1단계는 코드(결정적), 2단계만 LLM.**

```
1단계 — 가드레일 (코드, LLM 개입 불가):
  IF 심사관 중 하나라도 실패/타임아웃        → ESCALATED
  IF 영수증-청구 불일치 (REQ-028)            → ESCALATED (불일치 항목 첨부)
  IF 회칙 위반 판정 OR 중복 의심             → ESCALATED (금액 무관)
  IF 금액 > auto_approve_limit (팀 설정)     → ESCALATED
  IF 금액 > force_escalation_amount          → ESCALATED
  IF 예산 잔액 부족                          → AI_REJECTED 후보 (2단계로)

2단계 — LLM 합성 (1단계 통과 건만):
  3개 소견 + 유사 판례를 근거로 verdict(approve/reject) + confidence 산출
  confidence < threshold (기본 0.8)          → ESCALATED
  사유 2종 생성: 요청자용(정중·간결) / 관리자용(근거 조항·수치 포함)
```

즉 **AI가 자동 승인할 수 있는 건 "모든 가드레일 통과 + 고신뢰" 건뿐**이며, 관리자가 `auto_approve_limit=0`으로 설정하면 전건 수동 모드가 된다(협의 시 합의된 안전장치).

---

## 4. LangGraph 워크플로우

### 4.1 지출 심사 그래프 (메인 워크플로우)

```mermaid
flowchart TD
    START([START]) --> LC[load_context<br/>팀 정책·회칙 버전·파라미터 로드]
    LC --> IN[intake_receipt<br/>영수증 OCR·정규화]
    IN --> MM{mismatch_gate<br/>영수증-청구 대조}
    MM -- "불일치" --> ESC[escalate<br/>불일치 항목 정리]
    MM -- "일치" --> FAN((fan-out))
    FAN --> RA[rule_auditor<br/>회칙 심사]
    FAN --> BA[budget_auditor<br/>예산 심사]
    FAN --> PA[precedent_auditor<br/>판례·이상탐지]
    RA --> JOIN((fan-in))
    BA --> JOIN
    PA --> JOIN
    JOIN --> GR[guardrail_gate<br/>결정적 가드레일 §3.3-1단계]
    GR -- "차단 조건 해당" --> ESC
    GR -- "통과" --> AD[adjudicate<br/>LLM 판정 합성 §3.3-2단계]
    AD -- "confidence < θ" --> ESC
    AD -- "approve/reject" --> EX[execute_decision<br/>Agent 승인 API 호출]
    ESC --> CB[callback<br/>백엔드 결과 통보]
    EX --> CB
    CB --> PS[persist_precedent<br/>판정 로그 저장]
    PS --> END([END])
```

> [v1.1] **Dry-run 모드 (사전 문의, REQ-046안)**: `dry_run=true` 잡은 동일 그래프를 타되 `execute_decision`·`persist_precedent`를 건너뛰고 소견·예상 판정만 콜백한다. 상태 변경·판례 오염 없음. 지출 폼의 "쓰기 전에 물어보기"가 사용 (우선순위 P2).

### 4.2 노드 단일책임 정의

각 노드는 **입력 상태의 일부만 읽고, 자신 몫의 키만 쓴다.** 노드 간 결합은 상태 스키마로만 존재한다.

| 노드 | 읽는 키 | 쓰는 키 | 부수효과 |
|---|---|---|---|
| `load_context` | team_id | policy_params, rule_version | 없음 (읽기 전용) |
| `intake_receipt` | receipt_url | receipt_data | GCS 읽기, Vision 호출 |
| `mismatch_gate` | receipt_data, claim | mismatch[] | 없음 (순수 비교) |
| `rule_auditor` | claim, rule_version | opinions.rule | pgvector 검색, LLM 호출 |
| `budget_auditor` | claim, policy_params | opinions.budget | 백엔드 예산 조회 API |
| `precedent_auditor` | claim | opinions.precedent | pgvector 검색, LLM 호출 |
| `guardrail_gate` | opinions, policy_params, mismatch | gate_result | 없음 (순수 함수 — 단위 테스트 100% 커버 대상) |
| `adjudicate` | opinions, gate_result | verdict, confidence, reasons | LLM 호출 |
| `execute_decision` | verdict, expense_id | execution_result | 백엔드 Agent 승인 API (멱등성 키) |
| `callback` | 전체 결과 | callback_status | 백엔드 웹훅 |
| `persist_precedent` | 전체 결과 | - | llm-postgres INSERT |

상태 스키마(요약):

```python
class ReviewState(TypedDict):
    # 입력
    job_id: str; expense_id: str; team_id: str
    dry_run: bool                    # [v1.1] 사전 문의 모드 — 실행·판례 저장 스킵
    claim: ExpenseClaim              # 제목·금액·카테고리(선택)·날짜·설명
    receipt_url: str | None
    # 컨텍스트
    policy_params: PolicyParams      # auto_approve_limit, force_escalation_amount, θ
    rule_version: int
    # 진행 산출물
    receipt_data: ReceiptData | None
    category_assigned: str | None    # [v1.1] Intake 카테고리 분류 결과 (REQ-012)
    mismatch: list[Mismatch]
    opinions: Annotated[dict[str, Opinion], merge_opinions]  # 병렬 reducer
    gate_result: GateResult | None
    # 최종
    verdict: Literal["approve", "reject", "escalate"] | None
    confidence: float | None
    reasons: Reasons | None          # requester용 / admin용 분리
```

병렬 심사관은 `opinions` 딕셔너리에 자기 키로만 쓰고, LangGraph reducer(`merge_opinions`)가 fan-in 시 병합한다 — 쓰기 충돌이 구조적으로 불가능하다. checkpointer(PostgresSaver)로 각 노드 완료 시점의 상태가 저장되므로, 워커가 중간에 죽어도 **완료된 노드부터 재개**된다(비용·시간 이중 지출 방지).

### 4.3 미들웨어 계층 (횡단 관심사)

노드는 비즈니스 로직만 갖고, 횡단 관심사는 미들웨어로 분리한다.

| 계층 | 미들웨어 | 책임 |
|---|---|---|
| FastAPI | `AuthMiddleware` | 서비스 토큰 검증 (백엔드 ↔ LLM 서버 상호 인증) |
| FastAPI | `RequestLogMiddleware` | 구조화 로깅(JSON) — request_id 전파 |
| FastAPI | `RateLimitMiddleware` | 팀별 요청 속도 제한 |
| 그래프 래퍼 | `TracingWrapper` | LangSmith 트레이스에 job_id·팀·프롬프트 버전 태깅 |
| 그래프 래퍼 | `CostTracker` | 노드별 토큰·비용 집계 → jobs 테이블 기록 |
| LLM 클라이언트 | `RetryPolicy` | 지수 백오프 재시도(3회), 타임아웃(노드별 30s), OpenAI 429/5xx 대응 |
| LLM 클라이언트 | `PIIMasker` | 프롬프트 투입 전 멤버 실명→역할 치환 (REQ-042·043 익명화) |

### 4.4 보조 그래프

메인 심사 그래프와 별개의 독립 그래프로 두어 상호 영향을 차단한다.

**(a) 컨텍스트 갱신 (REQ-035·041)** — LLM 미사용 파이프라인

```mermaid
flowchart LR
    EV[백엔드 이벤트<br/>team_id·변경유형·버전] --> F[fetch: 원문 조회] --> C[chunk: 조항 단위 분할] --> E[embed] --> U[upsert: 신규 버전 활성화<br/>구버전 비활성화]
```

버전 전략: 재인덱싱 중에도 구버전 인덱스로 심사가 계속되고, 완료 시 원자적으로 전환. 진행 중이던 심사는 시작 시점에 고정한 `rule_version`을 끝까지 사용한다(판정 일관성).

**(b) 판례 학습 루프 (REQ-042)** — 시스템이 시간이 지날수록 똑똑해지는 핵심 메커니즘

```mermaid
flowchart LR
    D[관리자 결정<br/>결정·사유·override 여부] --> N[정규화·익명화] --> EM[임베딩] --> P[(precedents)]
    P --> PA[precedent_auditor<br/>다음 심사에서 유사 사례 인용]
    P --> BW[briefing_writer<br/>인수인계 브리핑 근거]
```

에스컬레이션된 건을 관리자가 결정하면(특히 AI 추천을 뒤집은 override 건) 그 결정·사유가 판례로 저장되고, 이후 유사 지출 심사 시 PrecedentAuditor가 인용한다. **데모 핵심 그래프: 판례 축적 → 에스컬레이션 비율 감소.**

> [v1.1] **override 정의·용어 규칙 (ADR-9)**: AI가 명시적 추천(승인/반려)을 낸 에스컬레이션 건에서 관리자가 **반대로 결정한 경우만** `is_override=true`. 추천 채택, 추천 없이 넘어온 건(판독 불능·심사 실패·강제 에스컬레이션 금액), AI 자동 처리 건은 미해당 — 이 경우 신규 판례로만 저장. override 건은 사유 입력 필수(REQ-015)이며 골든셋 편입 1순위. UI 표기는 **'AI와 다른 결정'**(뱃지 '다른 결정'), DB·API 필드명 `is_override`는 유지.

**(c) 문서 생성 그래프** — PolicyDrafter(마법사 회칙 초안), ReportWriter(정산 요약), BriefingWriter(인수인계), [v1.1] **DigestWriter**(대시보드 "AI 총무 브리핑" — 주간 스케줄 잡 또는 수동 트리거, 자동 처리 현황·소진 예측·이상 징후 요약). 공통 패턴: `데이터 수집(백엔드 API·판례 조회) → 구조화 → 생성 → 검증(수치 대조) → 반환`. 수치가 들어가는 문서는 **생성 후 원본 수치와 프로그램적으로 대조**하는 검증 노드를 필수로 둔다(환각 수치 차단).

**(d) 예산 조정 제안 그래프 (BudgetPlanner) [v1.1]** — `지출 이력·예산 조회(백엔드 API) → 소진 예측(순수 코드: burn-rate·이관 여력) → 조정안 생성(LLM) → 검증(수치 대조) → proposals 저장·반환`. 관리자가 예산 탭에서 수락하면 **백엔드가 기존 REQ-022 CRUD로 예산을 갱신**하고 REQ-041 이벤트가 발행된다 — **LLM 서버는 예산을 직접 변경하지 않는다** (쓰기 경계 §2.3 유지, ADR-8). 대시보드 소진 예측·예산 탭 제안 카드·정산 리포트 "다음 달 예산 제안"이 산출물을 공용한다.

**(e) 회칙 개정 제안 (PolicyDrafter 개정 모드) [v1.1]** — BriefingWriter의 회칙 vs 실운영 갭 분석을 상시화한 그래프: `판례 조회(동일 사유 반복 탐지, 기본 임계치 3회) → 갭 요약 → 개정 조항 초안(LLM) → proposals 저장·반환`. 관리자가 "개정안 보기 → 반영"하면 백엔드가 회칙 버전업(REQ-035) → REQ-041 재인덱싱. 판례 루프(b)의 출력을 정책 개선 입력으로 되돌리는 두 번째 학습 회로다.

---

## 5. 하네스 구성 — 툴·스킬·MCP

### 5.1 툴 카탈로그

모든 툴은 Pydantic 스키마로 입출력을 강제하고, 호출 결과는 트레이스에 기록된다.

| 툴 | 사용 노드 | 구현 | 비고 |
|---|---|---|---|
| `search_rules(team_id, query, version)` | RuleAuditor | pgvector 유사도 검색 | 조항 단위 청크, 버전 고정 |
| `search_precedents(team_id, claim_embedding)` | PrecedentAuditor | pgvector | 비활성 판례 제외 |
| `get_budget_status(team_id, category)` | BudgetAuditor | 백엔드 읽기 API | 잔액·한도·사용률 |
| `get_expense_history(team_id, filters)` | PrecedentAuditor | 백엔드 읽기 API | 중복 청구 탐지용 |
| `parse_receipt(signed_url)` | Intake | GPT-4o Vision | 구조화 출력(JSON 스키마 강제) |
| `budget_calculator(amounts)` | BudgetAuditor | 순수 Python | 수치 계산은 LLM에 맡기지 않음 |
| `approve_expense(expense_id, idempotency_key)` | execute_decision | 백엔드 Agent API | 서비스 계정, 멱등성 키 |
| `reject_expense(expense_id, reason, idempotency_key)` | execute_decision | 백엔드 Agent API | 〃 |
| `burn_rate_forecast(budgets, expenses)` [v1.1] | BudgetPlanner | 순수 Python | 소진 시점·이관 여력 계산 — LLM은 해석·문안만 |
| `detect_repeated_overrides(team_id, threshold)` [v1.1] | PolicyDrafter 개정 모드 | pgvector + SQL | 동일 사유 반복 판례 탐지 (기본 3회) |

### 5.2 MCP 서버

읽기 계열 툴 4종(`search_rules`, `search_precedents`, `get_budget_status`, `get_expense_history`)을 **FastMCP 서버로 llm-api에 마운트**해 이중으로 노출한다.

- **내부**: LangGraph 노드가 동일 툴 구현을 직접 호출 (프로세스 내, 오버헤드 없음)
- **외부(MCP)**: 운영자·개발자가 Claude Desktop / MCP Inspector로 "이 팀 회칙에서 회식 한도 찾아줘" 같은 질의를 에이전트와 동일한 툴로 실행 — 디버깅·데모·심사위원 시연에 사용

쓰기 툴(`approve/reject_expense`)은 MCP로 노출하지 않는다(그래프의 가드레일을 우회한 상태 변경 차단).

### 5.3 프롬프트·스킬 버전 관리

- 프롬프트는 코드와 분리해 `prompts/{agent}/{version}.yaml`로 관리, 시스템 프롬프트·few-shot·출력 스키마 포함
- 모든 판정 결과에 `model_version`·`prompt_version`을 태깅해 콜백·판례·감사로그에 저장(REQ-030·042) — "그때 왜 그렇게 판정했나"를 언제든 재현 가능
- 프롬프트 변경은 PR로만: CI가 골든셋 회귀 평가(§9)를 통과해야 머지

---

## 6. 데이터 설계 (llm-postgres)

```sql
-- 비동기 잡 (ADR-4)
jobs(id, expense_id, team_id, type, status,            -- queued|running|succeeded|failed|dead
     attempts, max_attempts, payload jsonb, result jsonb,
     cost_usd, tokens_in, tokens_out, created_at, updated_at)

-- 회칙·정책 임베딩 (REQ-041)
context_chunks(id, team_id, doc_type,                  -- rule|policy|category
     version int, chunk_text, embedding vector(1536),
     active boolean, created_at)

-- 판례 (REQ-042)
precedents(id, team_id, expense_summary,               -- 익명화된 요약
     decision, decided_by,                             -- AGENT|ADMIN
     reason, is_override boolean, confidence,          -- is_override: AI 명시적 추천에 반대한 결정만 (UI 'AI와 다른 결정', §4.4-b)
     rule_version int, model_version, prompt_version,
     embedding vector(1536), active boolean,           -- 삭제 대신 비활성화
     created_at)

-- 제안 (v1.1: 예산 조정·회칙 개정 — 수락 '실행'은 백엔드 CRUD 경유, 여기엔 제안·결정 상태만)
proposals(id, team_id, type,                           -- budget|rule_amendment
     payload jsonb,                                    -- 제안 본문·근거 수치·근거 판례 id
     status,                                           -- proposed|accepted|dismissed
     decided_by, created_at, decided_at)               -- 수락률 = 제안 품질 지표(§9)

-- LangGraph checkpointer: langgraph-checkpoint-postgres 기본 스키마 사용
```

인덱스: `context_chunks`·`precedents`에 HNSW(vector_cosine_ops), `(team_id, active)` 부분 인덱스. 모든 쿼리는 `team_id` 필터를 강제해 팀 간 데이터 격리(멀티테넌시)를 애플리케이션 계층에서 보장한다.

---

## 7. API 계약 (백엔드 ↔ LLM 서버)

### 7.1 지출 심사 시퀀스

```mermaid
sequenceDiagram
    participant FE as 프론트
    participant BE as Spring 백엔드
    participant API as llm-api
    participant WK as llm-worker
    participant AI as OpenAI

    FE->>BE: 지출 제출 (영수증 첨부)
    BE->>BE: status=PENDING, actor=AGENT 설정
    BE->>API: POST /v1/analyze
    API->>API: jobs INSERT (queued)
    API-->>BE: 202 { job_id }
    BE-->>FE: 제출 완료 (심사 중 표시)

    WK->>WK: 잡 폴링 → 심사 그래프 실행
    WK->>AI: OCR·심사·판정 (병렬)
    alt 자동 승인/반려
        WK->>BE: POST /internal/agent/approve|reject (멱등성 키)
        BE->>BE: 예산 차감 트랜잭션 (REQ-015·023 재사용)
    else 에스컬레이션
        Note over WK: 상태 변경 없음 (콜백만)
    end
    WK->>BE: POST /agent-callback (결과 전문)
    BE->>BE: 상태 갱신 + agent_result 저장 + 알림
    alt 콜백 3회 실패 or 타임아웃(120s)
        BE->>API: GET /v1/jobs/{job_id} (폴링 fallback)
    end
```

### 7.2 엔드포인트 명세

**LLM 서버 제공:**

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/v1/analyze` | 심사 잡 생성 → 202 + job_id. 페이로드: expense_id, team_id, 제목·금액·카테고리(선택 [v1.1])·날짜·설명, receipt_signed_url, dry_run(기본 false [v1.1]) |
| GET | `/v1/jobs/{job_id}` | 잡 상태·결과 조회 (폴링 fallback) |
| POST | `/v1/context/refresh` | REQ-041 이벤트 수신: team_id, change_type(rule\|category\|params), version |
| POST | `/v1/policy-draft` | 마법사 회칙·예산 초안 생성 (동기, 스트리밍 가능) |
| POST | `/v1/reports/summary` | 정산 리포트 AI 요약 잡 생성 |
| POST | `/v1/briefings` | 인수인계 브리핑 잡 생성 |
| POST | `/v1/digests` [v1.1] | 대시보드 "AI 총무 브리핑" 잡 생성 (DigestWriter — 주간 스케줄·수동 트리거) |
| POST | `/v1/proposals/budget` [v1.1] | 예산 조정 제안 잡 생성 (BudgetPlanner) |
| POST | `/v1/proposals/rule-amendment` [v1.1] | 판례 기반 회칙 개정 제안 잡 생성 (PolicyDrafter 개정 모드) |
| PATCH | `/v1/proposals/{id}` [v1.1] | 제안 상태 통보 (accepted/dismissed — 수락 실행 후 백엔드가 호출, 수락률 지표용) |
| GET | `/healthz`, `/readyz` | liveness / readiness (DB·OpenAI 연결 점검) |

**백엔드 제공 (LLM 서버가 호출):**

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `{BE}/agent-callback` | 심사 결과 콜백 (아래 스키마) |
| POST | `{BE}/internal/agent/expenses/{id}/approve` | Agent 승인 — 서비스 토큰 + Idempotency-Key 헤더 |
| POST | `{BE}/internal/agent/expenses/{id}/reject` | Agent 반려 |
| GET | `{BE}/internal/agent/teams/{id}/budget` | 예산·잔액·한도 조회 |
| GET | `{BE}/internal/agent/teams/{id}/expenses` | 지출 이력 조회 (중복 탐지용) |
| POST | `{BE}/internal/agent/decisions` | 관리자 결정 수신 → 판례 저장 트리거 (백엔드가 결정 시 LLM 서버 `/v1/precedents`로 push하는 방향도 협의 가능) |

**콜백 스키마 (회의 합의 필드):**

```json
{
  "job_id": "…", "expense_id": "…", "team_id": "…",
  "verdict": "approve | reject | escalate",
  "confidence": 0.93,
  "opinions": [
    {"auditor": "rule",      "verdict": "pass", "summary": "…", "evidence": ["회칙 제4조 …"]},
    {"auditor": "budget",    "verdict": "pass", "summary": "…", "figures": {"remaining": 182000}},
    {"auditor": "precedent", "verdict": "warn", "summary": "…", "similar_cases": ["…"]}
  ],
  "mismatch": [],
  "category_assigned": "회의비",
  "dry_run": false,
  "reasons": { "requester": "요청자용 한 줄 사유", "admin": "근거 조항·수치 포함 상세 사유" },
  "model_version": "gpt-4o-2024-11-20",
  "prompt_version": "review/v3",
  "cost_usd": 0.021, "latency_ms": 8400
}
```

### 7.3 지출 상태 모델 (REQ-037·038 — 양팀 공유 계약, 2026-07-06 합의 확정)

**합의 결과: 상태 1컬럼 × 주체 1컬럼의 2축 모델.** 상태를 6종으로 나열하는 대신 두 컬럼의 조합으로 표현한다.

- `status` ∈ `PENDING`(심사중) · `APPROVED`(승인) · `REJECTED`(반려)
- `actor_type` ∈ `AGENT`(AI) · `HUMAN`(사람) — **PENDING에서는 "지금 누가 처리할 차례인가", 종결 상태에서는 "누가 결정했는가"**를 의미

| status | actor_type | 의미 (기존 표기) |
|---|---|---|
| PENDING | AGENT | AI 심사 중 (구 PENDING_AI) |
| PENDING | HUMAN | **관리자 확인 필요 = 에스컬레이션** (구 ESCALATED) |
| APPROVED | AGENT | AI 자동 승인 (구 AI_APPROVED) |
| APPROVED | HUMAN | 관리자 승인 |
| REJECTED | AGENT | AI 자동 반려 (구 AI_REJECTED) |
| REJECTED | HUMAN | 관리자 반려 |

```mermaid
stateDiagram-v2
    [*] --> P_AI: 제출(REQ-012) → PENDING·AGENT
    P_AI: PENDING · AGENT (AI 심사 중)
    P_H: PENDING · HUMAN (관리자 확인 필요)
    A_AI: APPROVED · AGENT
    R_AI: REJECTED · AGENT
    A_H: APPROVED · HUMAN
    R_H: REJECTED · HUMAN
    P_AI --> A_AI: Agent 승인 (가드레일 전부 통과)
    P_AI --> R_AI: Agent 반려 (예: 잔액 부족)
    P_AI --> P_H: 보류·불일치·호출 실패(fail-safe)
    P_H --> A_H: 관리자 승인 (override 시 사유 필수)
    P_H --> R_H: 관리자 반려
    A_AI --> [*]
    R_AI --> [*]
    A_H --> [*]
    R_H --> [*]
```

이 모델의 장점: 정산 리포트(REQ-018)는 `status=APPROVED`만 집계하면 주체 무관 단일 쿼리, 지출 목록의 AI 뱃지·필터(REQ-010)는 `actor_type`으로 처리, 상태 enum 추가 없이 REQ-037 원문("처리 주체 필드 추가")과 일치. 전이 이력에는 사유·`model/prompt_version`(AGENT 결정 시)이 함께 기록된다. DRAFT(임시저장, REQ-011·우선순위 하)는 제출 전 단계로 `status` 앞단에 두되 심사 모델과 무관.

> 본 문서의 다른 절에서 쓰는 `ESCALATED`는 `(PENDING, HUMAN)` 조합의 약칭이다.
> [v1.1] UI 용어: override는 화면에서 **'AI와 다른 결정'**(뱃지 '다른 결정')으로 표기한다. 판정 기준·미해당 케이스는 §4.4(b), 채택 근거는 ADR-9. dry-run 잡은 이 상태 머신에 진입하지 않는다(상태 변경 없음).

---

## 8. 안전장치 (Fail-safe 매트릭스)

**대원칙: 어떤 실패도 자동 승인으로 이어지지 않는다.** 실패의 기본 수렴처는 항상 ESCALATED.

| 실패 시나리오 | 감지 | 처리 |
|---|---|---|
| OpenAI 타임아웃·5xx | 노드별 타임아웃 30s + 재시도 3회(지수 백오프) | 재시도 소진 → ESCALATED + 사유 "AI 분석 실패" |
| 워커 프로세스 다운 | 잡 heartbeat / visibility timeout | 재기동 후 checkpointer에서 재개, max_attempts 초과 → dead + ESCALATED |
| LLM 서버 전체 다운 | 백엔드 측 제출 후 N분 무응답 감시 | 백엔드가 자체적으로 ESCALATED 전환 (REQ-012 fail-safe, 백엔드 책임 구간) |
| 콜백 전달 실패 | 콜백 3회 재시도 | 백엔드 폴링 fallback (GET /v1/jobs) |
| 심사관 1개 실패 | fan-in 시 opinions 누락 감지 | guardrail_gate가 ESCALATED (부분 소견으로 판정하지 않음) |
| 영수증 판독 불능 | Vision 출력 스키마 검증 실패 | ESCALATED + "영수증 확인 필요" |
| 중복 승인 시도 | 백엔드 멱등성 키 + row lock (REQ-023) | 409 수신 → 잡 succeeded 처리 (이중 차감 없음) |
| 프롬프트 인젝션 (지출 설명란에 지시문 삽입) | 사용자 입력은 명시적 구분자로 격리, 판정은 가드레일이 최종 통제 | 가드레일은 코드라서 프롬프트로 우회 불가. 골든셋에 인젝션 케이스 포함(§9) |
| 개인정보 유출 | PIIMasker 미들웨어 | 프롬프트·판례·브리핑에서 실명→역할 치환 |

---

## 9. 에이전트 성능 평가 체계

### 9.1 평가 대상과 메트릭

| 대상 | 메트릭 | 목표 (초기) | 방법 |
|---|---|---|---|
| **최종 판정** | verdict 정확도 (골든 라벨 대비) | ≥ 90% | 골든셋 회귀 |
| **최종 판정** | **오승인율 (false-approve)** — 승인하면 안 되는 건을 자동 승인 | **0% (하드 게이트)** | 골든셋 내 must-not-approve 케이스 |
| **최종 판정** | 에스컬레이션 precision/recall | 균형 관찰 | 과소 에스컬레이션(위험) vs 과다(무용성) 트레이드오프 추적 |
| RuleAuditor | 근거 조항 인용 정확도 | ≥ 85% | 조항 라벨 매칭 + LLM-as-Judge |
| BudgetAuditor | 수치 판단 정확도 | 100% (계산은 코드) | 단위 테스트 |
| Intake (OCR) | 금액·날짜 추출 정확도 | ≥ 95% | 라벨된 영수증 세트 |
| 사유 텍스트 | 근거 충실성·톤 적절성 | 5점 척도 ≥ 4 | LLM-as-Judge (gpt-4o, 별도 프롬프트) |
| 시스템 | p95 지연 / 건당 비용 | < 15s / < $0.05 | LangSmith 트레이스 집계 |
| BudgetPlanner [v1.1] | 소진 예측·이관 수치 정확도 | 100% (계산은 코드) | 단위 테스트 |
| 제안 품질 [v1.1] | 예산·회칙 제안 수락률 | 관찰 지표 | `proposals` 상태 집계 — 낮으면 프롬프트·임계치 조정 |

### 9.2 골든셋 구성

`eval/golden/` 에 JSON으로 버전 관리. 팀 유형별(동아리·스터디·회사) × 시나리오별 최소 60건으로 시작해 매주 확장:

- 명백 승인 (한도 내, 회칙 적합, 영수증 일치)
- 명백 반려 (잔액 부족, 금지 항목)
- 경계 케이스 (한도 근접, 회칙 해석 애매 → 정답은 escalate)
- 영수증 불일치 (금액/날짜/품목 각각)
- 중복 청구, 분할 청구(한도 우회 시도)
- **적대 케이스**: 설명란 프롬프트 인젝션, 극단 금액, 빈 회칙 팀
- 판례 반영 검증: 동일 사안에 대해 판례 저장 전/후 판정 변화

### 9.3 평가 파이프라인

```mermaid
flowchart LR
    G[골든셋 JSON] --> DS[LangSmith Dataset 업로드]
    PR[프롬프트/그래프 변경 PR] --> CI[GitHub Actions]
    CI --> RUN[langsmith evaluate<br/>심사 그래프 실행]
    DS --> RUN
    RUN --> M{메트릭 게이트}
    M -- "오승인 > 0 or 정확도 하락" --> FAIL[머지 차단]
    M -- 통과 --> PASS[머지 허용 + 리포트 코멘트]
```

- 모든 운영 트래픽은 LangSmith에 트레이싱 → 실패·override 건은 주간 리뷰에서 골든셋으로 편입 (**운영 데이터 → 평가 데이터 순환**)
- 프롬프트 A/B: `prompt_version` 태깅 덕분에 LangSmith에서 버전 간 메트릭 비교 가능
- 데모 지표: 주차별 에스컬레이션 비율 감소 그래프 (판례 학습 루프 효과 입증)

---

## 10. 배포 설계

### 10.1 컨테이너 구성 (docker-compose)

```yaml
services:
  llm-api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
    env_file: .env
    depends_on: { llm-postgres: { condition: service_healthy } }
    healthcheck: { test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"] }
    restart: unless-stopped

  llm-worker:
    build: .                      # 동일 이미지, entrypoint만 다름
    command: python -m app.worker
    env_file: .env
    depends_on: { llm-postgres: { condition: service_healthy } }
    deploy: { replicas: 1 }       # 수평 확장 지점
    restart: unless-stopped

  llm-postgres:
    image: pgvector/pgvector:pg16
    volumes: [ "pgdata:/var/lib/postgresql/data" ]
    healthcheck: { test: ["CMD-SHELL", "pg_isready"] }
```

스테이징은 풀스택 팀 compose(Spring·메인 DB·프론트)와 **네트워크만 공유하는 별도 compose 파일**로 결합(`docker compose -f fullstack.yml -f llm.yml up`). Dockerfile은 multi-stage build(uv 기반 의존성 캐시)로 이미지 경량화.

### 10.2 FastAPI 안정성 체크리스트

- **수명주기**: lifespan에서 DB 풀·httpx 클라이언트 생성/정리, graceful shutdown(처리 중 잡은 checkpointer 덕분에 유실 없음)
- **검증**: 전 요청/응답 Pydantic v2 스키마, 422 표준화
- **관측**: `/healthz`(liveness) · `/readyz`(DB·OpenAI 도달성), 구조화 JSON 로그(request_id·job_id 상관관계), `/metrics`는 여유 시 Prometheus 노출
- **격리**: LLM 호출은 워커에만 존재 → API는 밀리초 응답 유지, 장애 반경 분리
- **시크릿**: `.env`는 리포 제외, `.env.example` 커밋, 키는 부트캠프 발급 계정 사용

---

## 11. 협업·문서화

### 11.1 리포지토리 구조 (LLM 서버)

```
llm-server/
├── app/
│   ├── main.py               # FastAPI 앱 (라우터·미들웨어 조립만)
│   ├── api/                  # 라우터 (analyze, context, jobs, drafts…)
│   ├── graphs/               # LangGraph 그래프 정의
│   │   ├── review/           #   심사 그래프 (nodes/ 하위 노드 1파일 1책임)
│   │   ├── indexing/
│   │   └── writers/          #   report·briefing·policy_draft
│   ├── agents/               # 심사관별 프롬프트 조립·출력 파서
│   ├── tools/                # §5.1 툴 (LangGraph·MCP 공용)
│   ├── mcp/                  # FastMCP 서버 마운트
│   ├── middleware/
│   ├── schemas/              # Pydantic 계약 (콜백·잡·상태)
│   ├── db/                   # 세션·마이그레이션(alembic)
│   └── worker.py
├── prompts/{agent}/{version}.yaml
├── eval/golden/*.json  ·  eval/run_eval.py
├── tests/                    # guardrail_gate 100% 커버 목표
├── docs/                     # 본 설계서·ADR·API 계약(OpenAPI)
├── docker-compose.yml  ·  Dockerfile  ·  .env.example
```

### 11.2 협업 규칙

- **GitHub**: trunk 기반, 기능 브랜치 + PR 필수 리뷰 1인, CI(lint→unit→골든셋 회귀) 통과 필수. API 계약 변경은 OpenAPI 스펙 diff를 PR에 포함하고 풀스택 팀 리뷰어 지정
- **Jira**: 본 문서 §4·§7 단위로 에픽 분해(심사 그래프 / 컨텍스트 파이프라인 / 문서 생성 / 평가 / 배포), REQ-ID를 티켓에 라벨링해 요구사항 추적성 확보
- **문서화**: 설계 결정은 ADR(`docs/adr/NNN-*.md`) 누적, 주간 회의록·API 변경 이력 리포 커밋. 콜백 스키마 등 계약은 코드(Pydantic)가 단일 진실 원천이고 문서는 자동 생성(OpenAPI)

### 11.3 6주 로드맵 (양팀 합의 일정과 정렬)

| 주차 | LLM 팀 산출물 | 통합 지점 |
|---|---|---|
| 1 | 본 설계서 확정, API 계약(OpenAPI) 커밋, FastAPI 스켈레톤 + 스텁 응답, compose 기동 | 상태 머신·계약 필드 동결 |
| 2 | 심사 그래프 v1 (단일 심사관, 가드레일, 콜백), 컨텍스트 인덱싱 파이프라인 | 제출→콜백 E2E (스테이징) |
| 3 | 병렬 3-심사관 + Adjudicator, Intake OCR·불일치 게이트, 골든셋 v1 30건 | 마법사·정책 화면 연동 |
| 4 | 판례 저장·검색 루프, Agent 승인 API 연동(멱등성), LangSmith CI 게이트 | 에스컬레이션 E2E |
| 5 | ReportWriter·BriefingWriter·PolicyDrafter, [v1.1] DigestWriter·BudgetPlanner·회칙 개정 제안, MCP 서버, 골든셋 60건+ | 통합 테스트·시드 데이터 데모 |
| 6 | 버퍼: 성능 튜닝(비용·지연), [v1.1] dry-run 사전 문의(여유 시, P2), 데모 시나리오, 문서 마감 | 리허설 |

---

## 12. 유지보수·확장성

| 확장 시나리오 | 설계상 대응 지점 |
|---|---|
| 심사관 추가 (예: 세금 심사관) | 노드 1개 + `opinions` 키 등록만으로 fan-out에 편입 — 기존 노드 무수정 |
| 모델 교체·비용 최적화 | `models.yaml` 라우팅 설정 변경, 골든셋 회귀로 안전 확인 |
| 트래픽 증가 | llm-worker replicas 증가 (잡 테이블이 자연스러운 큐) → 그 이상은 ADR-4 명시대로 Redis 큐로 교체 (워커 인터페이스 유지) |
| 모임 유형 추가 | 정책 템플릿(yaml) 추가 — PolicyDrafter 코드 무수정 |
| 회칙 형식 다양화 (PDF·이미지) | Indexer 앞단에 파서만 추가 (파이프라인 단계 분리 덕분) |
| 알림 채널 확장 (카카오 등) | LLM 서버 무관 — 콜백 계약 뒤편은 백엔드 소관 (경계 설계 §2.3의 효과) |
| 타사 연동·자동화 | MCP 서버가 이미 표준 인터페이스 제공 |
| 제안 유형 추가 (예: 회비 조정 제안) [v1.1] | `proposals.type` 확장 + writers 공통 패턴 재사용 — 수락 실행은 항상 백엔드 CRUD 경유(ADR-8) |

유지보수성 핵심: ① 노드 단일책임 + 순수함수 가드레일(테스트 용이) ② 프롬프트·모델·정책의 코드 외부화 ③ 계약 기반 팀 경계 ④ 전 판정의 버전 태깅(재현 가능성).

---

## 부록 A. ADR 상세

**ADR-1 — LLM: OpenAI GPT-4o 계열.** Vision·임베딩·채팅을 단일 벤더로 통일해 인증·에러 처리·비용 추적 단순화. 심사(gpt-4o)와 요약·분류(gpt-4o-mini) 라우팅으로 비용 통제. 대안 Claude는 심사 품질 이점이 있으나 부트캠프 키 지원·단일 벤더 운영 단순성에서 열세. 라우팅이 설정화되어 있어 후일 혼합 전환 비용 낮음.

**ADR-2 — 저장소: Postgres+pgvector 단일.** 6주 프로젝트에서 컨테이너 수·운영 지식 부담 최소화가 우선. checkpointer(langgraph-checkpoint-postgres)·벡터·잡·판례를 한 DB로. 벡터 규모(팀당 회칙 수십 청크 + 판례 수백 건)는 pgvector HNSW로 충분. 대안 Chroma/Qdrant는 규모가 커질 때 재검토.

**ADR-3 — 평가: LangSmith+골든셋.** LangGraph 네이티브 트레이싱으로 노드 단위 디버깅, Dataset/Experiment로 회귀 평가, 무료 티어로 충분. 오승인율 0%를 CI 하드 게이트로 설정. 대안 DeepEval/RAGAS는 트레이싱 통합이 약함.

**ADR-4 — 잡 큐: Postgres 테이블 + 전용 워커.** `FOR UPDATE SKIP LOCKED` 폴링으로 경합 없는 잡 분배, 상태·재시도·비용이 한 테이블에서 관측 가능. Celery+Redis는 컨테이너·개념 추가 대비 이득 없음(현 트래픽). 워커 인터페이스를 추상화해 추후 Redis 큐 교체 가능.

**ADR-5 — 문서화: Markdown+Mermaid 리포 커밋.** 계약·설계의 변경이 PR 리뷰를 거치게 하여 협업 평가 요소(문서화 체계)와 직결. 제출용 포맷 필요 시 md에서 변환.

**ADR-6 — 지출 상태: 2컬럼 모델 (2026-07-06, 풀스택 공동 결정).** 상태 6종 enum 대신 `status`(PENDING/APPROVED/REJECTED) × `actor_type`(AGENT/HUMAN) 조합으로 표현. PENDING의 actor_type은 "현재 처리 차례", 종결 상태에서는 "결정 주체"로 해석. 근거: 정산 집계·필터 쿼리 단순화, REQ-037 원문과 일치, 상태 추가 없이 에스컬레이션 표현 가능. 대안(ESCALATED 별도 상태, boolean 플래그)은 컬럼 의미 중복 또는 enum 비대화로 기각. 상세는 §7.3.

**ADR-7 — 카테고리 분류: 전용 노드 없이 Intake 통합 (2026-07-09, v1.1).** REQ-012 정책("제출 시 LLM이 금액/카테고리 자동 추출")이 분류를 이미 규정하므로 별도 Classifier 노드는 중복. 지출 폼의 카테고리는 선택사항화하고 Intake 산출 `category_assigned`를 콜백으로 반환. 근거: AssoAI 차별화 전략 v2 — 경쟁사에도 있는 '자동 분류'는 심사의 입력으로만 포지셔닝하고 노드·비용을 늘리지 않는다.

**ADR-8 — 제안(proposal) 기능의 실행 경계 (2026-07-09, v1.1).** BudgetPlanner(예산 조정)·PolicyDrafter 개정 모드(회칙 개정)는 LLM 서버가 **제안 생성까지만** 담당하고, 수락 시 실행(예산 CRUD·회칙 버전업)은 백엔드 기존 API(REQ-022·035)를 경유한다. §2.3 쓰기 경계 원칙 유지 — 에이전트의 직접 쓰기 권한은 지출 승인/반려 2종에 한정. 제안·결정 상태는 `proposals` 테이블로 추적해 수락률을 품질 지표로 사용(§9).

**ADR-9 — UI 용어: override → 'AI와 다른 결정' (2026-07-09, v1.1).** 사용자 대면 화면에서 override는 'AI와 다른 결정'(뱃지 '다른 결정')으로 표기. 판정 기준: AI가 명시적 추천을 낸 에스컬레이션 건에서 관리자가 반대로 결정한 경우만(§4.4-b). DB 필드 `is_override`·API 필드는 유지해 코드 영향 없음. 대안 '추천 번복'(뉘앙스 단호), 'AI 교정'(AI 오류 전제) 대비 중립성·자기설명성 우위로 채택.

