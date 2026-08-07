# Agent Server 호출 내부 API 명세

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-29 (팀장 리뷰 반영 갱신) · 2026-08-05 (⑪ 지출 이력 조회 누락 복원) · 2026-08-06 (풀스택 회신 반영 — ① `category` 정책 · ② `escalation_threshold` 반영 완료 · ⑤ 회칙 파일 응답 판별 규칙 신설 · ⑪ 신설 확정) · **2026-08-06 T11 (8/6 저녁 회신 반영 — ② 컬럼 부재 정정 · ④ 경로·인증 확정 · ⑤ 팀당 1개 · ⑥ 언더바 표기 · ⑧ `auditor` 4종 · §6 23경로)** |
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
토큰 값은 배포 시(8/7) 보안 채널로 전달한다.

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
  { "title": "스터디 교재 구입", "amount": 32000, "category": null,
    "date": "2026-07-01", "description": "알고리즘 교재 2권" }
  ```
- **`category`는 비워서 주세요** (2026-08-06 회신 반영). 8/4 회의로 사용자 직접 입력이
  삭제됐고, 백엔드도 `expenses.category`를 nullable로 바꿔 등록 시 `null`로 저장한 뒤
  콜백의 `suggestedCategory`로 채우기로 했습니다. 저희는 이제 **값이 있든 없든 항상 AI
  분류를 실행**합니다
  - 값이 채워져 오면 **정상 경로가 아니라 계약 위반**으로 보고, 존중하지 않고 AI 분류로
    덮되 **경고 로그**를 남깁니다. 조용히 덮으면 계약이 어긋난 사실 자체가 묻힙니다
  - ~~값이 있으면 그대로 존중하되 AI 분류와 확신 있게 다르면 ESCALATED로 보류~~ (구 정책,
    2026-07-10 팀 확정 → 8/6 회신으로 폐기)
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
- ✅ **`escalation_threshold` 컬럼은 존재하지 않는다** (2026-08-06 백엔드 정정 — "컬럼도
  있다"던 이전 회신을 뒤집어, `team_settings`에는 처음부터 `auto_approve_limit`만 있었다).
  2026-08-05 합의(화면 금액 칸 1개화로 실효 소멸 → 삭제)는 삭제할 대상이 애초에 없던
  것으로 종결. 저희 매핑은 이 키가 없으면 `auto_approve_limit`과 같은 값으로 읽으므로
  (PR #12) 그대로 정상 동작하고, 두 값이 어긋날 여지도 없다 — 한때 이 문서에 있던
  "컬럼 삭제 배포 순서"·"두 컬럼 같은 값 유지" 조건도 함께 소멸했다
  - 참고: 이 컬럼(구 설계)은 원래 금액이었고 확신도 θ(0~1 실수)가 아니었다. 2026-07-31에
    θ에 대입하던 버그를 고쳤고, 당시 목이 `0.8`을 반환해 목 모드에서는 드러나지 않았다
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
- ✅ **형식 확정 (2026-08-06 회신, 구 FQ4)**: 기존 `GET /api/files/{fileName}` 경로를 그대로
  쓴다 — 지출 상세(API-017)의 `receiptFileUrl`이 이 형태다. `receiptPath`에 이 경로를 담아
  주시면 된다
- **인증: Agent 서비스 토큰을 요구하도록 막는 것을 권장합니다** (영수증은 개인정보인데 현재
  무인증 공개). 저희는 모든 백엔드 호출에 토큰을 이미 싣고 있어 막아도 저희 쪽 수정은
  없습니다. 다만 프론트가 같은 경로로 영수증을 띄운다면 사용자 인증 경로는 별도로 열어
  두셔야 합니다 — 그 판단은 백엔드·프론트 몫
- 실패 시 동작: 판독 불능이면 `parse_ok=False`로 에스컬레이션한다. 자동 승인은 하지 않는다

### ⑤ 회칙 원문 조회 (파일 응답 확장 반영 — 2026-08-06)
```
GET /internal/agent/teams/{teamId}/policy-document?doc_type=rule
```
- 용도: 회칙을 청킹·임베딩해 벡터 인덱스를 만든다(RAG). 회칙 심사관이 이 인덱스를 검색한다
- 호출 시점: `POST /v1/context/refresh` 이벤트를 받은 직후. 회칙 등록·수정 시 백엔드가
  우리에게 알려주면 우리가 이 API로 원문을 가져와 인덱싱한다

**응답은 두 가지입니다** — 관리자가 마법사 3단계에서 회칙을 직접 입력했는지(`manual`)
파일로 올렸는지(`file`)에 따라 갈립니다. 어느 쪽인지는 백엔드만 아는 사실이라, refresh
이벤트에 필드를 늘려 프론트·백엔드 계약을 흔드는 대신 **같은 경로가 형식만 달리 답하는**
방식으로 정했습니다(2026-08-06 회신 반영). 덕분에 LLM-006 계약도 워커도 바뀌지 않습니다.

| 회칙 형태 | `Content-Type` | 본문 | 파일명 |
|---|---|---|---|
| 텍스트 (`rule_source=manual`) | `application/json` | `{ "text": "제1조 (목적) ...\n\n제2조 ..." }` (원문 전체, 무수정) | — |
| 파일 (`rule_source=file`) | `application/pdf` 또는<br>`application/vnd.openxmlformats-officedocument.wordprocessingml.document` | 파일 원본 바이트 | `Content-Disposition: attachment; filename="회칙.pdf"` |

🔴 **판별 규칙을 이렇게 정한 이유 — 이 부분만은 꼭 맞춰 주세요.**
저희는 **응답의 `Content-Type`에 `json`이 들어 있으면 텍스트**, 아니면 파일 원본으로 읽습니다.
파일을 JSON으로 감싸(예: `{"file": "<base64>"}` 또는 `{"file_url": "..."}`) 보내시면 저희 코드가
텍스트 경로로 빠져 `text` 키를 찾다가 실패합니다. **연동 당일에야 드러나는 유형**이라 미리
적어 둡니다. 다른 형태가 편하시면 알려 주세요 — `backend_client.py` 한 곳만 고치면 됩니다.

✅ **백엔드 확정 (2026-08-06 회신)**: 위 방식 그대로 구현 — URL·base64로 감싸지 않는다.
회칙은 **팀당 1개(덮어쓰기)** 구조로 확정되어 `version` 파라미터는 사실상 항상 최신 1건이다
(무시하셔도 된다).

- **파일명은 `Content-Disposition`의 `filename=`으로 주세요.** 확장자만으로 형식을 정하지는
  않습니다(매직 넘버 우선). `회칙.pdf`인데 실제 내용이 docx인 경우가 실재해서, 파일명이
  없거나 틀려도 파싱은 됩니다. 다만 에러 메시지에 파일명이 들어가면 관리자가 어떤 파일이
  문제인지 바로 압니다
- **지원 형식은 PDF와 Word(docx) 두 가지**입니다. 그 외(hwp·구형 doc·txt·이미지·zip)는
  저희가 명시적으로 에러를 돌려드립니다. 스캔한 이미지 PDF도 글자 레이어가 없어 에러입니다
- **파싱은 저희가 합니다.** 빈 문자열을 반환하지 않고 전부 예외로 처리합니다 — 빈 값을
  돌려주면 인덱싱이 청크 0개로 '성공'해서 **관리자는 회칙을 등록했다고 믿는데 심사는
  회칙 없는 팀으로 도는** 조용한 실패가 됩니다
- 파싱 실패 사유는 `GET /v1/jobs/{job_id}`의 `result`에 담깁니다. 잡이 `dead`(재시도 소진
  최종 실패)이면 `result`는 `{"error": "<예외 클래스명>", "message": "<실패 사유>"}` 구조이고,
  **화면에 띄우실 것은 `message`**입니다 — 관리자에게 그대로 보여드려도 되는 문장입니다.
  예: *"스캔한 이미지 PDF는 글자를 인식할 수 없으니, 텍스트가 들어 있는
  PDF나 Word 파일로 다시 올려 주세요."*
- LLM-005 요청의 `rule_file_ref`에는 **저장된 파일명**(예: `bd345b5a-….pdf`)을 넣습니다
  (2026-08-06 확정). 조회 자체는 teamId로 하므로(팀당 1개) 이 값은 어떤 파일 기준의
  초안인지 남기는 기록·추적용입니다
- 🟡 **저희 구현 상태**: 위 계약대로 구현·머지 완료(2026-08-06)이나 **목 모드에서만 검증**된
  상태입니다. 실제 응답으로 확인하는 것은 배포일 첫 연동 때입니다

### ⑥ 팀 프로필 조회
```
GET /internal/agent/teams/{teamId}/profile
```
- 용도: 모임 유형별 카테고리 카탈로그 선택 (유형당 고정 6개)
- 기대 응답: `{ "team_type": "스터디" }`
- ✅ **표기 확정 (2026-08-06 회신, 구 FQ9)**: 백엔드 ENUM **언더바 표기 그대로** 보내면 된다 —
  `동아리_학생회` · `스터디` · `친목` · `동호회` · `회사`. 언더바는 저희가 받는 쪽에서 내부
  표기(`동아리/학생회`)로 접는다(마법사 요청과 이 응답 모두). 첫 값의 정확한 문자열
  (`동아리_학생회`인지)은 재확인 중

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
    "suggestedCategory": "교육", "processedBy": "AI | ADMIN",
    "confidence": 0.95,
    "opinions": [{"auditor":"rule|budget|precedent|evidence","verdict":"pass|warn|fail|error",
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
3. `auditor` 값은 **4종**이다 — `evidence`(증빙 심사관, 2026-08-04 협의로 추가)는 영수증-청구
   대조 결과를 지출 상세 'AI 심사결과'에 보여주기 위한 소견이며 **판정 권한은 없다**.
   `suggestedCategory`는 전역 9종 값으로 온다.

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
- ✅ **신설 확정 (2026-08-06 회신)** — "가능합니다. 내부 조회 API로 신설하겠습니다.
  경로는 제안하신 것 그대로 쓰거나, 조율 필요하면 알려주세요."
  → **위 경로 그대로 부탁드립니다.** 저희 `backend_client.py`가 이미 이 URL로 호출하고
  있어 조율할 것이 없습니다. 쿼리는 `period`(선택, `YYYY-MM`) 하나이고, 응답 필드는
  `title` · `amount` · `category` · `date` · `status` 다섯 개입니다(snake_case)
- **심사 전 건은 `category`가 `null`일 수 있습니다** (2026-08-06 회신 — 등록 시 `null` 저장,
  콜백 `suggestedCategory`로 채움). `null`은 저희가 `기타`로 접어 집계합니다
- **`category` 값 — 구 값이 섞여 와도 됩니다.** 마이그레이션 전 데이터에 구 값이 남아
  있어도 **저희가 받는 쪽에서 9종으로 접습니다**(`normalize_expense_category`). 이관 시점을
  기다리지 않아도 리포트·대시보드 집계는 항상 9종 기준으로 나옵니다.
  - 접는 규칙: 우리가 2026-08-04 전까지 쓰던 유형별 28종 + 백엔드 구 ENUM의 `행사`·`디자인`을
    아래 표대로 옮기고, **목록에 없는 값은 `기타`로 접되 경고 로그**를 남깁니다

    | 9종 | 접히는 구 값 |
    |---|---|
    | 식비 | 식대/회식비 · 식비/간식비 · 식비/다과비 · 식비/모임비 |
    | 교통 | 교통비 · 교통/출장비 |
    | IT_인프라 | 온라인/구독비 · 업무도구/소프트웨어비 |
    | 교육 | 교육/강연비 · 교육/도서비 · 교재/자료비 |
    | 회의 | 회의/운영비 · 회의/워크숍비 |
    | 장소_대관 | 공간/대관비 · 장소/예약비 · 장소/시설비 · 숙박/여행비 |
    | 행사_활동 | 행사/프로그램비 · 활동/프로그램비 · 대회/참가비 · 레저/액티비티비 · 실습/프로젝트비 · 홍보/콘텐츠비 · **행사**(구 ENUM) |
    | 비품 | 물품/소모품비 · 비품/소모품비 · 장비/용품비 · 인쇄/문구비 |
    | 기타 | 선물/기념비 · **디자인**(구 ENUM) |

  - 유지되는 5종(`회의`·`IT_인프라`·`교육`·`식비`·`기타`)은 이름이 같아 손댈 것이 없습니다
  - 🟡 **다만 저희 집계와 백엔드 집계가 갈릴 수 있습니다.** 같은 지출을 저희는 `행사_활동`으로,
    백엔드는 `행사`로 세게 됩니다. 마이그레이션 때 위 표대로 옮겨 주시면 양쪽이 맞습니다
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
| ⑤ | `GET /internal/agent/teams/{teamId}/policy-document` | 회칙 원문 (텍스트 JSON **또는 파일 바이트**) | 필수 |
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

## 6. openapi.json 경로 수

우리가 제공하는 API 스펙은 `docs/openapi.json` 하나이며, 현재 **23경로**다(2026-08-06).
과거 이 절에 있던 "sblim 14경로 vs cowbro 17경로" 구분은 브랜치 통합(PR #9, 2026-08-05)으로
소멸했고, 당시 "MVP 제외"로 적혀 있던 `POST /v1/proposals/budget`도 T4(PR #20)로 구현·머지되어
스펙에 실려 있다.

`POST /v1/reviews/stream` · `POST /v1/reviews/{job_id}/decision` 두 경로는 LLM팀 내부
데모·관측 전용이라(대시보드 실시간 진행 표시, 관리자 개입 시연) 풀스택 연동 대상이 아니다.
