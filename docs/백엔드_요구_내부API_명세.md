# LLM팀 → 백엔드팀: Agent Server가 호출하는 내부 API 명세

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-29 (팀장 리뷰 반영 갱신) |
| 작성 | LLM팀 (개발자 A) |
| 근거 | `app/tools/backend_client.py` 현행 구현 (경로·파라미터·기대 응답을 코드에서 그대로 추출) |
| **위치** | **`풀스택_회신요청.md` 1번(내부 조회 API 8종 요청)의 구체안** — 그 문서가 "8종이 명세에 없으니 열어달라"고 요청했다면, 이 문서는 **각 API의 경로·파라미터·응답 예시를 제안**한다. |
| 함께 볼 것 | `README.md`(문서 안내) · `풀스택_연동_계약.md`(기술 계약) · `풀스택_회신요청.md`(회신 필요 14건) |

## 0. 왜 이 문서가 필요한가

`full stack api 명세서`(API-001~050)는 **프론트 ↔ 백엔드** 구간을 규정한다.
Agent Server(LLM)는 그 API를 쓰지 않고, **백엔드가 별도로 열어주는 내부 API**를 쓴다
(bravo 설계서 표16·18·19의 "2차 호출" 구간). 그 목록이 지금까지 문서로 정리된 적이
없어 이 문서로 확정 요청한다.

**동작 원리(pull 모델)**: 백엔드는 심사 요청 시 `jobId·expenseId·organizationId·
심사목표·영수증 경로` 5개만 보낸다. 지출 상세·예산·회칙·설정은 **Agent Server가
아래 API로 되물어** 가져온다. 따라서 아래 API가 없으면 심사가 시작되지 않는다.

**현재 상태**: 전부 `MOCK_BACKEND=true` 목 구현으로 동작 중이며, 실제 경로가
확정되면 `backend_client.py`의 URL 한 줄씩만 교체하면 된다(로직 변경 없음).

**인증**: 전 요청에 Agent 전용 토큰(현재 `Authorization: Bearer {service_token}`)을
싣는다. 실제 방식 확정 필요(FQ4와 연동).

---

## 1. 심사 파이프라인 필수 (이게 없으면 심사 불가) 🔴

### ① 지출 상세 조회
```
GET /internal/agent/organizations/{organizationId}/expenses/{expenseId}
```
- **용도**: pull 모델의 핵심 — 심사할 지출의 내용을 가져온다 (`load_context` 노드)
- **기대 응답**
  ```json
  { "title": "스터디 교재 구입", "amount": 32000, "category": "교재/자료비",
    "date": "2026-07-01", "description": "알고리즘 교재 2권" }
  ```
- **참고**: `category`가 빈 문자열이면 AI가 자동 분류한다(팀 확정 2026-07-10).
  값이 있으면 그대로 존중하되, AI 분류와 확신 있게 다르면 ESCALATED로 보류한다(FQ9).
- **실패 시 동작**: 조회 실패 = 예외 → 재시도 → 최종 실패 시 fail-safe 에스컬레이션
  (자동 승인으로 이어지지 않음)

### ② 팀 설정 조회
```
GET /internal/agent/organizations/{organizationId}/team-settings
```
- **용도**: 자동승인 권한·한도 — 가드레일 **0번 규칙**(최상위 게이트)
- **기대 응답**
  ```json
  { "auto_approve": false, "auto_approve_limit": 50000, "escalation_threshold": 300000 }
  ```
- ✅ **`escalation_threshold`는 금액으로 확정**(2026-07-27 DB 스키마 `team_settings` 근거) —
  우리 `force_escalation_amount`와 1:1이다("이 금액 초과 시 무조건 관리자 검토"). 코드 반영 완료이며
  확신도 임계값 θ(0~1 실수)와는 분리했다. 명칭은 `escalationThreshold`로 통일한다.
  → 목 구현이 아직 `0.8`을 반환하는 것은 우리 쪽 잔여 정리 사항이며, 회신이 필요한 항목이 아니다.
- ⚠️ **회신 필요**: 이 값의 **기본값**을 확정해 주세요. AI 마법사 2단계 화면이 200,000원 기준으로
  그려져 있어 우리도 그에 맞출 예정인데, 현재 우리 코드 기본값은 300,000원이다
  (`풀스택_회신요청.md` 15번 ④). 조회·수정 API에 이 필드가 없는 문제는 같은 문서 5번.
- **실패 시 동작**: `auto_approve=False`로 fail-safe (안전 방향)

### ③ 예산 현황 조회
```
GET /internal/agent/teams/{teamId}/budget?category={optional}
```
- **용도**: 예산 심사관 — 잔액 = `total_budget − spent`
- **기대 응답**: `{ "total_budget": 300000, "spent": 118000 }`
- **참고**: 예산은 **모임 전체 총액 하나**(팀 확인 2026-07-09). 카테고리별 한도 없음 —
  `category` 파라미터는 내역 조회용 선택값이지 한도 검사 기준이 아니다.

### ④ 영수증 이미지 조회
```
GET {receiptPath}   ← 심사 요청에 담겨 온 '조회 경로'를 그대로 재요청
```
- **용도**: Vision OCR로 금액·날짜 추출 → 신청 금액과 불일치 시 **무조건 보류**
- **기대 응답**: 이미지 바이너리 (`image/*`)
- ⚠️ **확인 필요(FQ4)**: 값 형식이 미확정이다 — 내부 조회 경로인가, 서명 URL인가,
  파일 ID인가? Agent 전용 토큰의 발급·갱신 방식은?
- **실패 시 동작**: 판독 불능 → `parse_ok=False` → 에스컬레이션(자동 승인 아님)

### ⑤ 회칙 원문 조회
```
GET /internal/agent/teams/{teamId}/policy-document?doc_type=rule&version={n}
```
- **용도**: 회칙을 청킹·임베딩해 벡터 인덱스 구축(RAG) → 회칙 심사관이 검색
- **기대 응답**: `{ "text": "제1조 (목적) ...\n\n제2조 ..." }` (원문 전체, 무수정)
- **호출 시점**: `POST /v1/context/refresh` 이벤트 수신 시 (회칙 등록·수정 직후
  백엔드가 우리에게 알려주면 우리가 이 API로 원문을 가져와 인덱싱)

### ⑥ 팀 프로필 조회
```
GET /internal/agent/teams/{teamId}/profile
```
- **용도**: 모임 유형별 카테고리 카탈로그 선택 (유형당 고정 6개)
- **기대 응답**: `{ "team_type": "스터디" }`
- **유형 5종**: `동아리/학생회` · `스터디` · `친목` · `동호회` · `회사`
  (문자열이 정확히 일치해야 한다 — FQ9)

### ⑦ 팀 멤버 명단 조회
```
GET /internal/agent/teams/{teamId}/members
```
- **용도**: **PII 마스킹** — LLM에 보내기 전 실명을 치환한다(개인정보 보호)
- **기대 응답**: `[ { "name": "김철수", "role": "총무" }, ... ]`
- **실패 시 동작**: 빈 배열로 진행(마스킹 없이 심사 — 단, 실패 로그 기록)

---

## 2. 결과 전달 (우리 → 백엔드) 🔴

### ⑧ 심사 결과 콜백
```
POST /agent-callback
```
- **방향**: **Agent Server → 백엔드** (우리가 호출)
- **재시도**: 실패 시 지수 백오프 3회(1s→2s), 최종 실패해도 백엔드 폴링이 안전망
- **전송 payload** — 아래는 `CallbackPayload`를 실제 직렬화해 확인한 출력이다
  (⚠️ 최상위는 camelCase지만 **중첩 객체 안에 예외 1건**이 있다. 아래 주의 참조):
  ```json
  { "jobId": "백엔드가 발급한 값 그대로 echo", "expenseId": 4821, "teamId": 17,
    "verdict": "approve | reject | escalate",
    "suggestedCategory": "교재/자료비", "processedBy": "AI | ADMIN",
    "confidence": 0.95,
    "opinions": [{"auditor":"rule|budget|precedent","verdict":"pass|warn|fail|error",
                  "summary":"...","evidence":[],"figures":{},"similar_cases":[]}],
    "reasons": {"requester":"요청자용(수치 비노출)","admin":"관리자용(조항·수치 인용)"},
    "mismatch": [{"field":"amount","claimed":"40000","receipt":"25000"}],
    "modelVersion":"gpt-4o", "promptVersion":"adjudicator/v3",
    "costUsd":0.0061, "latencyMs":3300, "dryRun": false }
  ```
- ⚠️ **파서 작성 시 주의 2건**(현행 출력 기준 — `풀스택_회신요청.md` 14번으로 회신 요청 중):
  1. **`opinions[].similar_cases`만 snake_case**다. 최상위 필드는 camelCase 변환
     설정이 걸려 있지만, 중첩된 `Opinion` 모델은 그 설정을 상속받지 않는다
     (`evidence`·`figures`처럼 한 단어 필드는 차이가 안 드러나 눈에 띄지 않았다).
  2. **`mismatch[].claimed`·`receipt`는 문자열**이다 (`"40000"`, 정수 아님) —
     모델 선언이 `str`이다.
  → **회신이 오면 코드를 camelCase·타입으로 통일**할 수 있다(`Opinion`·`Mismatch`에
     같은 alias 설정을 붙이면 됨). 계약 변경이라 확인 후 진행한다. 그전까지는
     **위 실제 출력 기준으로 파서를 작성**해 주세요.
- ⚠️ **확인 필요(FQ2)**: 키 이름이 `verdict`인데 명세서 응답 필드는 `finalVerdict`다.
  바꿔야 하는가? 값은 소문자(`approve`)인가 대문자(`APPROVED`)인가?
- ⚠️ **확인 필요(FQ6)**: 명세서의 `detail`은 단일 필드인데 우리는 `reasons`+`opinions`로
  나눠 보낸다. 백엔드가 조합하는가? **`detail`이 요청자에게도 보이는 화면이 있는가?**
  (있다면 `reasons.admin`의 수치가 요청자에게 노출되지 않도록 분리 전달 필요)
- ⚠️ **확인 필요(FQ7)**: bravo 설계서에는 "콜백 주소를 요청에 함께 전달"이라 돼 있으나
  현재 우리 요청 스키마에 `callbackUrl` 필드가 없다. 실제로 보내는가?

---

## 3. 조건부 — 계약 확정 시에만 사용 🟡

### ⑨⑩ 승인 / 반려 실행
```
POST /internal/agent/expenses/{expenseId}/approve
POST /internal/agent/expenses/{expenseId}/reject
Header: Idempotency-Key: {키}      Body: { "reason": "..." }
응답: 200 정상 / 409 이미 처리됨(중복 — 이중 차감 없음)
```
- ⚠️ **현재 미사용 예정**: LLM팀 원칙은 **"AI는 추천만, 실행·예산 차감은 백엔드"**다.
  콜백 단일화(FQ3)가 확정되면 이 두 API는 **삭제**하고 콜백만 남긴다.
- **FQ3 회신 전까지는 코드에 유지**하되 호출하지 않는다. 백엔드팀에서 "이 API는
  만들지 않겠다"고 하면 그대로 확정하면 된다.

---

## 4. 요약표

| # | 메서드·경로 | 용도 | 우선순위 |
|---|---|---|---|
| ① | `GET /internal/agent/organizations/{orgId}/expenses/{expenseId}` | 지출 상세 | 🔴 필수 |
| ② | `GET /internal/agent/organizations/{orgId}/team-settings` | 자동승인 설정 | 🔴 필수 |
| ③ | `GET /internal/agent/teams/{teamId}/budget` | 예산 현황 | 🔴 필수 |
| ④ | `GET {receiptPath}` | 영수증 이미지 | 🔴 필수 |
| ⑤ | `GET /internal/agent/teams/{teamId}/policy-document` | 회칙 원문 | 🔴 필수 |
| ⑥ | `GET /internal/agent/teams/{teamId}/profile` | 모임 유형 | 🔴 필수 |
| ⑦ | `GET /internal/agent/teams/{teamId}/members` | 멤버 명단(마스킹용) | 🟡 권장 |
| ⑧ | `POST /agent-callback` | 심사 결과 수신 | 🔴 필수 |
| ⑨⑩ | `POST .../expenses/{id}/approve` · `/reject` | 승인·반려 실행 | ⚪ 미사용 예정(FQ3) |

> 경로·필드명은 **우리 쪽 제안**이며 백엔드팀 편의에 맞춰 바꿔도 된다 —
> 우리는 `backend_client.py` 한 파일에서 URL만 교체하면 되므로 부담이 없다.
> **⑦은 없으면 마스킹 없이 진행**하므로 후순위로 미뤄도 심사는 동작한다.

---

## 5. 참고 — 함께 전달되는 `docs/openapi.json` 기준

우리가 **제공하는** API 스펙은 `docs/openapi.json`이며, 전달본은 **팀 브랜치(sblim)
기준 14경로**를 사용한다. 개발자 A 브랜치(cowbro)판은 17경로로 아래 차이가 있다:

| 차이 | 사유 |
|---|---|
| `POST /v1/proposals/budget` | 팀 결정으로 **MVP 제외**(sblim `9e89525`)됐으나 cowbro에 아직 미머지 — **전달본에서는 빠지는 것이 맞다** |
| `POST /v1/reviews/stream`<br>`POST /v1/reviews/{job_id}/decision` | LLM팀 **내부 데모·관측 전용**(대시보드 실시간 진행 표시·관리자 개입 시연)이며 풀스택 연동 대상이 아니다 |

→ 브랜치 머지 후 `scripts/dump_openapi.py`를 한 번 돌리면 정리된다.
