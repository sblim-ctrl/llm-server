# Agent Server 호출 내부 API 명세

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-29 (팀장 리뷰 반영 갱신) · 2026-08-05 (⑪ 지출 이력 조회 누락 복원) |
| 작성 | LLM팀 (개발자 A) |
| 근거 | `app/tools/backend_client.py` 현행 구현. 경로·파라미터·기대 응답을 코드에서 그대로 추출 |
| 위치 | `풀스택_회신요청.md` 1번(내부 조회 API 8종 요청)의 구체안. 그 문서가 여덟 종이 명세에 없으니 열어달라고 요청했다면, 이 문서는 각 API의 경로·파라미터·응답 예시를 제안한다. 조회 API 수록분은 ①~⑦(회신요청 8종 중 7종)과 ⑪ 지출 이력(설계서 v1.1 §7.2 합의분 복원)이다. 회신요청 8종 중 '관리자 결정 내역'은 협의 미완으로 미수록(확정 시 추가) |
| 함께 볼 것 | `README.md`(문서 안내) · `풀스택_연동_계약.md`(기술 계약) · `풀스택_팀별_AI에이전트_연동제안.md`(모임 생성) · `풀스택_회신요청.md`(회신 필요 17건) |

## 0. 배경

`full stack api 명세서`(API-001~050)는 프론트와 백엔드 사이 구간을 규정한다. Agent
Server(LLM)는 그 API를 쓰지 않고, 백엔드가 별도로 열어주는 내부 API를 쓴다(bravo 설계서
표16·18·19의 2차 호출 구간). 그 목록이 지금까지 문서로 정리된 적이 없어 이 문서로 확정을
요청한다.

동작 원리는 pull 모델이다. 백엔드는 심사 요청 시 `jobId`·`expenseId`·`organizationId`·
심사목표·영수증 경로 다섯 개만 보낸다. 지출 상세·예산·회칙·설정은 Agent Server가 아래
API로 되물어 가져온다. 따라서 아래 API가 없으면 심사가 시작되지 않는다.

현재는 전부 `MOCK_BACKEND=true` 목 구현으로 동작 중이며, 실제 경로가 확정되면
`backend_client.py`의 URL을 한 줄씩 교체하면 된다. 로직 변경은 없다.

인증은 전 요청에 Agent 전용 토큰(현재 `Authorization: Bearer {service_token}`)을 싣는다.
실제 방식은 확정이 필요하다(FQ4와 연동).

---

## 1. 심사 파이프라인 필수

이 구간이 없으면 심사를 시작할 수 없다.

### ① 지출 상세 조회
```
GET /internal/agent/organizations/{organizationId}/expenses/{expenseId}
```
- 용도: pull 모델의 핵심. 심사할 지출의 내용을 가져온다 (`load_context` 노드)
- 기대 응답
  ```json
  { "title": "스터디 교재 구입", "amount": 32000, "category": "교재/자료비",
    "date": "2026-07-01", "description": "알고리즘 교재 2권" }
  ```
- 참고: `category`가 빈 문자열이면 AI가 자동 분류한다(팀 확정 2026-07-10). 값이 있으면
  그대로 존중하되, AI 분류와 확신 있게 다르면 ESCALATED로 보류한다(FQ9)
- 실패 시 동작: 조회 실패는 예외로 처리해 재시도하고, 최종 실패 시 fail-safe
  에스컬레이션으로 넘긴다. 자동 승인으로 이어지지 않는다

### ② 팀 설정 조회
```
GET /internal/agent/organizations/{organizationId}/team-settings
```
- 용도: 자동승인 권한과 한도. 가드레일 0번 규칙(최상위 게이트)에 쓴다
- 기대 응답
  ```json
  {
    "auto_approve": false,
    "auto_approve_limit": 50000,
    "policy_sync_status": "READY",
    "policy_version": 1
  }
  ```
- `auto_approve_limit`은 마법사 2단계 화면의 '관리자 승인 필수 금액' 한 칸이다. 화면 최소
  제약은 50,000원이다
- **경계는 '이상'이다** (2026-08-05 화면 개편으로 확정). 한도가 50,000원이면 49,999원까지
  자동 판정이고 50,000원부터 관리자 확인이다. 화면 표의 "N원 미만 / N원 이상"과 같은
  기준이다. 백엔드 쪽에도 같은 금액으로 분기하는 로직이 있다면 맞춰 주세요
- **`escalation_threshold` 컬럼은 삭제한다** (2026-08-05 합의). 화면 금액 칸이 2개에서
  1개로 줄면서 이 컬럼은 실효가 없어졌다 — 두 규칙 모두 '관리자 확인'으로 귀결돼 판정을
  가르는 것은 항상 `min(두 값)` 하나였고, 칸이 하나가 되면 두 값이 갈릴 경로 자체가 사라진다.
  - **배포 순서 주의.** 우리 매핑 수정(키가 없으면 `auto_approve_limit`과 같은 값으로 읽기)이
    먼저 배포돼야 한다. 순서가 반대면 모델 기본값 200,000이 채워져 `min(관리자 설정값,
    200,000)`이 되고, **관리자가 50만을 설정해도 20만부터 관리자 확인**이 된다. 화면에는
    드러나지 않는 조용한 축소라 2026-07-31 사고와 같은 유형이다
  - 우리 쪽 반영이 끝나면 별도로 알려드립니다. 그 뒤에는 컬럼이 있든 없든 양쪽 다 정상
    동작하므로 편한 시점에 지우시면 됩니다
  - 참고: 이 컬럼은 원래 금액이었고 확신도 θ(0~1 실수)가 아니었다. 2026-07-31에 θ에
    대입하던 버그를 고쳤고, 당시 목이 `0.8`을 반환해 목 모드에서는 드러나지 않았다
- `auto_approve_limit`이 `null`이면 0으로 간주한다. 한도 0이면 모든 금액이 관리자 검토로 가므로
  안전 방향이다(설계서 §8). DB상 NULL 허용이고 `auto_approve=FALSE`가 실서비스 기본이라 NULL이
  정상 케이스다
- 회신 필요: 저장 시점에도 화면과 같은 최소 50,000원 검증이 있는지 알려주세요. 화면에서만
  막고 API가 열려 있으면 다른 경로로 그보다 작은 값이 들어올 수 있습니다. 조회·수정 API에
  이 필드가 없는 문제는 `풀스택_회신요청.md` 5번
- 실패 시 동작: `auto_approve=False`로 fail-safe 처리
- `policy_sync_status`·`policy_version`은 팀별 논리적 에이전트 준비 상태 확인을 위한 권장 필드다.
  `policy_sync_status != "READY"`이면 저장된 관리자 설정이 `true`여도 이 내부 API의
  `auto_approve`는 유효값 `false`로 내려 자동 승인을 막는 방식을 제안한다.
- **실패 시 동작**: `auto_approve=False`로 fail-safe (안전 방향)

### ③ 예산 현황 조회
```
GET /internal/agent/teams/{teamId}/budget?category={optional}
```
- 용도: 예산 심사관. 잔액은 `total_budget − spent`로 계산한다
- 기대 응답: `{ "total_budget": 300000, "spent": 118000 }`
- 참고: 예산은 모임 전체 총액 하나다(팀 확인 2026-07-09). 카테고리별 한도는 없으며
  `category` 파라미터는 내역 조회용 선택값이지 한도 검사 기준이 아니다
- 키 표기는 세 가지를 모두 받는다. 지출 합계는 `spent`·`used_budget`(DB 컬럼)·
  `usedBudget`(프론트 API 표기), 총액은 `total_budget`·`totalBudget`. 어느 표기를 쓰실지 회신을
  기다리지 않아도 되도록 우리 쪽 경계에서 흡수했다(2026-07-31). 편한 쪽으로 주시면 된다

### ④ 영수증 이미지 조회
```
GET {receiptPath}   ← 심사 요청에 담겨 온 조회 경로를 그대로 재요청
```
- 용도: Vision OCR로 금액·날짜를 추출해 신청 금액과 대조한다. 불일치하면 무조건 보류
- 기대 응답: 이미지 바이너리 (`image/*`)
- 확인 필요(FQ4): 값 형식이 미확정이다. 내부 조회 경로인가, 서명 URL인가, 파일 ID인가.
  Agent 전용 토큰의 발급·갱신 방식도 함께 알려주세요
- 실패 시 동작: 판독 불능이면 `parse_ok=False`로 에스컬레이션한다. 자동 승인은 하지 않는다

### ⑤ 회칙 원문 조회
```
GET /internal/agent/teams/{teamId}/policy-document?doc_type=rule&version={n}
```
- 용도: 회칙을 청킹·임베딩해 벡터 인덱스를 만든다(RAG). 회칙 심사관이 이 인덱스를 검색한다
- 기대 응답: `{ "text": "제1조 (목적) ...\n\n제2조 ..." }` (원문 전체, 무수정)
- 호출 시점: `POST /v1/context/refresh` 이벤트를 받은 직후. 회칙 등록·수정 시 백엔드가
  우리에게 알려주면 우리가 이 API로 원문을 가져와 인덱싱한다

### ⑥ 팀 프로필 조회
```
GET /internal/agent/teams/{teamId}/profile
```
- 용도: 모임 유형별 카테고리 카탈로그 선택 (유형당 고정 6개)
- 기대 응답: `{ "team_type": "스터디" }`
- 유형 5종: `동아리/학생회` · `스터디` · `친목` · `동호회` · `회사`. 문자열이 정확히
  일치해야 한다(FQ9)

### ⑦ 팀 멤버 명단 조회
```
GET /internal/agent/teams/{teamId}/members
```
- 용도: PII 마스킹. LLM에 보내기 전 실명을 치환한다
- 기대 응답: `[ { "name": "김철수", "role": "총무" }, ... ]`
- 실패 시 동작: 빈 배열로 진행한다. 마스킹 없이 심사하되 실패 로그를 남긴다

---

## 2. 결과 전달 (Agent Server → 백엔드)

### ⑧ 심사 결과 콜백
```
POST /agent-callback
```
- 방향: Agent Server가 백엔드를 호출한다
- 재시도: 실패 시 지수 백오프로 3회(1s→2s) 재시도한다. 최종 실패해도 백엔드 폴링이
  안전망 역할을 한다
- 전송 payload. 아래는 `CallbackPayload`를 실제 직렬화해 확인한 출력이다. 최상위는
  camelCase지만 중첩 객체 안에 예외가 하나 있다(아래 주의 참조)
  ```json
  { "jobId": "백엔드가 발급한 값 그대로 echo", "expenseId": 4821, "teamId": 17,
    "verdict": "approve | reject | escalate",
    "suggestedCategory": "교재/자료비", "processedBy": "AI | ADMIN",
    "confidence": 0.95,
    "opinions": [{"auditor":"rule|budget|precedent","verdict":"pass|warn|fail|error",
                  "summary":"...","evidence":[],"figures":{},"similar_cases":[]}],
    "reasons": {"requester":"요청자용(수치 비노출)","admin":"관리자용(조항·수치 인용)"},
    "mismatch": [{"field":"amount","claimed":"40000","receipt":"25000"}],
    "dryRun": false }
  ```

**파서 작성 시 주의 2건** (현행 출력 기준. `풀스택_회신요청.md` 14번으로 회신 요청 중)

1. `opinions[].similar_cases`만 snake_case다. 최상위 필드는 camelCase 변환 설정이 걸려
   있지만 중첩된 `Opinion` 모델은 그 설정을 상속받지 않는다. `evidence`·`figures`처럼 한
   단어 필드는 차이가 드러나지 않아 눈에 띄지 않았다.
2. `mismatch[].claimed`·`receipt`는 문자열이다(`"40000"`, 정수 아님). 모델 선언이 `str`이다.

회신이 오면 코드를 camelCase와 타입으로 통일할 수 있다(`Opinion`·`Mismatch`에 같은 alias
설정을 붙이면 된다). 계약 변경이라 확인 후 진행하며, 그전까지는 위 실제 출력 기준으로 파서를
작성해 주세요.

**확인 필요 3건**

- FQ2: 키 이름이 `verdict`인데 명세서 응답 필드는 `finalVerdict`다. 바꿔야 하는가.
  값은 소문자(`approve`)인가 대문자(`APPROVED`)인가
- FQ6: 명세서의 `detail`은 단일 필드인데 우리는 `reasons`와 `opinions`로 나눠 보낸다.
  백엔드가 조합하는가. `detail`이 요청자에게도 보이는 화면이 있는가. 있다면
  `reasons.admin`의 수치가 요청자에게 노출되지 않도록 분리 전달이 필요하다
- FQ7: bravo 설계서에는 콜백 주소를 요청에 함께 전달한다고 돼 있으나 현재 우리 요청
  스키마에 `callbackUrl` 필드가 없다. 실제로 보내는가
- **최상위 키는 11개다.** 이전 버전의 `modelVersion`·`promptVersion`·`costUsd`·`latencyMs`
  4개는 지출 상세 화면에서 쓰이지 않아 제거했다. 값은 LLM 서버에 남아
  `GET /v1/jobs/{job_id}`의 `result`로 조회된다. 전환 중에는 4개가 더 실려 올 수 있으니
  **모르는 필드는 무시하는 파서**로 만들어 달라 — 위 11키는 두 버전 모두에서 항상 온다.

---

## 3. 조건부 (계약 확정 시에만 사용)

### ⑨⑩ 승인 / 반려 실행
```
POST /internal/agent/expenses/{expenseId}/approve
POST /internal/agent/expenses/{expenseId}/reject
Header: Idempotency-Key: {키}      Body: { "reason": "..." }
응답: 200 정상 / 409 이미 처리됨(중복 — 이중 차감 없음)
```
- 현재 미사용 예정이다. LLM팀 원칙은 AI가 추천만 하고 실행과 예산 차감은 백엔드가
  맡는 것이다. 콜백 단일화(FQ3)가 확정되면 이 두 API는 삭제하고 콜백만 남긴다
- FQ3 회신 전까지는 코드에 유지하되 호출하지 않는다. 백엔드팀에서 이 API는 만들지
  않겠다고 하면 그대로 확정하면 된다

---

## 4. 생성 기능 필수 (이게 없으면 리포트·브리핑·대시보드 불가)

### ⑪ 지출 이력 조회 (Notion 표 기준 BE-009)
```
GET /internal/agent/teams/{teamId}/expenses?period={YYYY-MM}   ← period는 선택
```
- **용도**: 정산 리포트(LLM-008)·주간 브리핑(LLM-009)·예산 관리 AI 메시지(LLM-016)·
  대시보드 AI 요약(LLM-017)의 기간 지출 집계. 추후 판례·이상탐지 심사관
  (`precedent_auditor`)의 중복 청구·분할 청구 탐지에도 사용 예정(현재 TODO).
- **기대 응답** (배열)
  ```json
  [ { "title": "정기 회식", "amount": 84000, "category": "식비",
      "date": "2026-06-05", "status": "APPROVED" }, ... ]
  ```
- **경위**: 설계서 v1.1 §7.2 합의분인데 2026-07-29 본 문서 작성 때 누락됐다 —
  **신규 요청이 아니라 누락 복원**이다. `backend_client.py`는 이미 이 경로를
  호출하도록 구현돼 있다.
- **심사는 이 API 없이도 시작된다**(심사 그래프 미사용). 단, 실연동 전환
  (`MOCK_BACKEND=false`) 시 이 API가 없으면 위 생성 기능들이 404로 실패한다.

---

## 5. 요약표

| # | 메서드·경로 | 용도 | 우선순위 |
|---|---|---|---|
| ① | `GET /internal/agent/organizations/{orgId}/expenses/{expenseId}` | 지출 상세 | 필수 |
| ② | `GET /internal/agent/organizations/{orgId}/team-settings` | 자동승인 설정 | 필수 |
| ③ | `GET /internal/agent/teams/{teamId}/budget` | 예산 현황 | 필수 |
| ④ | `GET {receiptPath}` | 영수증 이미지 | 필수 |
| ⑤ | `GET /internal/agent/teams/{teamId}/policy-document` | 회칙 원문 | 필수 |
| ⑥ | `GET /internal/agent/teams/{teamId}/profile` | 모임 유형 | 필수 |
| ⑦ | `GET /internal/agent/teams/{teamId}/members` | 멤버 명단(마스킹용) | 권장 |
| ⑧ | `POST /agent-callback` | 심사 결과 수신 | 필수 |
| ⑨⑩ | `POST .../expenses/{id}/approve` · `/reject` | 승인·반려 실행 | 미사용 예정(FQ3) |
| ⑪ | `GET /internal/agent/teams/{teamId}/expenses` | 지출 이력(리포트·브리핑·대시보드) | 필수(심사 비차단) |

경로와 필드명은 우리 쪽 제안이며 백엔드팀 편의에 맞춰 바꿔도 된다. 우리는
`backend_client.py` 한 파일에서 URL만 교체하면 되므로 부담이 없다. ⑦은 없어도 마스킹
없이 진행하므로 후순위로 미뤄도 심사는 동작한다.

관리자 결정 내역 조회(Notion 표 BE-008)는 원천 테이블·폴링 주기·인증 협의가
끝나면 본 문서에 추가한다(현재 미수록).

---

## 6. openapi.json 경로 수 차이

우리가 제공하는 API 스펙은 `docs/openapi.json`이며, 전달본은 팀 브랜치(sblim) 기준
14경로를 사용한다. 개발자 A 브랜치(cowbro)판은 17경로로 아래 차이가 있다.

| 차이 | 사유 |
|---|---|
| `POST /v1/proposals/budget` | 팀 결정으로 MVP에서 제외했으나(sblim `9e89525`) cowbro에 아직 미머지다. 전달본에서는 빠지는 것이 맞다 |
| `POST /v1/reviews/stream`<br>`POST /v1/reviews/{job_id}/decision` | LLM팀 내부 데모·관측 전용이다(대시보드 실시간 진행 표시, 관리자 개입 시연). 풀스택 연동 대상이 아니다 |

브랜치 머지 후 `scripts/dump_openapi.py`를 한 번 돌리면 정리된다.
