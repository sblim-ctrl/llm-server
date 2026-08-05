# 팀별 논리적 AI 에이전트 연동 제안

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-30 |
| 상태 | 풀스택팀 협의 요청 |
| 대상 | 모임 생성(API-009) · AI 마법사(API-029·031·044) · 회칙 인덱싱 연동 |
| 관련 문서 | `풀스택_연동_계약.md` · `백엔드_요구_내부API_명세.md` · `풀스택_회신요청.md` |

> ⚠️ **2026-08-06 — §4-1·§4-2의 `/v1/policy-draft` 예시가 낡았습니다.** 작성 이후
> (8/4 회의·8/5 화면 개편으로) LLM-005가 전면 개정되어 요청·응답 형태가 아래 예시와
> 다릅니다. 최신 계약은 `마법사_API_명세.md`를 참고해 주세요. 이 문서의 나머지 설계
> (공용 프로세스·API-009/031 흐름·동기화 경계)는 이 개정과 무관하게 유효합니다.

## 1. 제안 결론

모임마다 별도의 AI 서버 프로세스나 컨테이너를 생성하지 않습니다.

LLM API 서버와 워커 프로세스는 모든 팀이 공유하고, 각 팀의 AI 에이전트는 아래 데이터를
`teamId`로 분리해 표현합니다.

```text
공용 LLM API / 공용 워커
          │
          ├─ teamId=A → A팀 설정·회칙·예산·판례·인덱스
          ├─ teamId=B → B팀 설정·회칙·예산·판례·인덱스
          └─ teamId=C → C팀 설정·회칙·예산·판례·인덱스
```

따라서 이 문서에서 말하는 **에이전트 생성**은 프로세스 기동이 아니라 다음 리소스를 준비하는
과정입니다.

1. 팀·관리자·예산·안전한 기본 설정 생성
2. 기본 또는 사용자 정책 저장
3. 정책 원문을 팀별로 인덱싱
4. 정책 동기화 상태를 준비 완료로 변경

## 2. 책임 분리

| 구분 | 풀스택 백엔드 | LLM 서버 |
|---|---|---|
| 진실 원천 | 팀·멤버·예산·설정·정책 원문·정책 버전 | 정책 청크·임베딩·판례 인덱스·심사 잡 |
| 모임 생성 | API-009 트랜잭션 처리 | 호출하지 않음 |
| AI 추천 | API-044에서 팀 데이터를 조회·변환 | `/v1/policy-draft`로 초안·추천값 반환 |
| 정책 저장 | API-031로 원문·버전 저장 | 저장 완료 이벤트 수신 후 인덱싱 |
| 심사 실행 | 지출을 `SUBMITTED`로 저장하고 잡 요청 | 공용 워커가 `teamId` 컨텍스트로 심사 |
| 최종 반영 | 콜백을 멱등 처리하고 상태·예산·감사로그 갱신 | 판정·소견 콜백 발신 |

LLM 서버는 팀별 설정을 자체 DB에 복제해 진실 원천으로 삼지 않습니다. 심사할 때 백엔드 내부
API에서 설정·예산·프로필을 읽고, 회칙과 판례 인덱스만 `teamId`와 버전으로 격리합니다.

## 3. API-009 권장 계약

### 3-1. 일반 모임 생성 요청

마법사 진입 전에 `teamId`가 필요하므로 API-009는 기본 모임을 먼저 만드는 API로 고정하는 것을
제안합니다.

```http
POST /api/teams
Content-Type: application/json
Authorization: Bearer <USER_TOKEN>
```

```json
{
  "name": "알고리즘 스터디",
  "description": "주 1회 알고리즘 문제 풀이",
  "teamType": "STUDY",
  "initialBudget": 1000000
}
```

한 DB 트랜잭션에서 다음을 생성합니다.

1. `teams`
2. `team_members` — 인증 사용자를 `ADMIN`·가입 완료 상태로 저장
3. `budgets`
4. `team_settings` — 안전한 기본 설정

권장 기본 설정:

```json
{
  "membershipFee": 0,
  "autoApprove": false,
  "autoApproveLimit": null,
  "escalationThreshold": 200000
}
```

`settings`를 생략했을 때 행 자체를 만들지 않고 `null`로 두는 방식보다, 기본 행을 항상 만드는
방식을 권장합니다. 그래야 LLM의 팀 설정 조회가 404로 실패하지 않고, 마법사 중단 상태에서도
`autoApprove=false`라는 안전한 기본 동작이 보장됩니다.

권장 응답:

```json
{
  "teamId": 17,
  "setupStatus": "DRAFT",
  "policyMode": null,
  "policySyncStatus": "NOT_STARTED",
  "settings": {
    "membershipFee": 0,
    "autoApprove": false,
    "autoApproveLimit": null,
    "escalationThreshold": 200000
  }
}
```

### 3-2. `adminId` 처리

`adminId`를 요청 본문으로 받지 않고 인증 토큰의 사용자 ID를 사용합니다.

- 생성자는 `team_members.role=ADMIN`
- 현재 관리자는 `team_members`에서 조회
- `teams.admin_id` 같은 중복 컬럼은 추가하지 않음

한 팀에 관리자가 여러 명이 될 수 있으므로 관리자 관계의 진실 원천은 `team_members`가 적합합니다.

### 3-3. API-009에서 정책 파일을 받지 않는 이유

일반 마법사 흐름에서는 API-009의 `policy`·`settings`·`file` 입력을 제외하는 것을 권장합니다.

- 정책과 설정은 마법사에서 아직 결정되지 않은 값입니다.
- 파일 업로드를 포함하면 API-009 전체가 `multipart/form-data`가 되어 기본 생성 계약이 복잡해집니다.
- DB 트랜잭션은 외부 파일 저장소와 LLM 네트워크 호출까지 원자적으로 묶을 수 없습니다.

정책 파일은 API-031만 `multipart/form-data`로 처리합니다. 기존 API-009의 선택적
`policy/settings`를 호환 목적으로 유지해야 한다면 관리자용 일괄 등록 경로로만 남기고, 일반
마법사 프론트에서는 사용하지 않는 것을 제안합니다.

## 4. AI 마법사 권장 흐름

### 4-1. 1단계 — 회비·추천

1. API-029로 `membershipFee` 저장
2. API-044 호출
3. 백엔드는 `teamId`로 팀·예산·설정을 조회
4. 아래처럼 LLM `/v1/policy-draft` 요청으로 변환

> ⚠️ 낡음 — 아래 요청에는 LLM-005 개정으로 추가된 `team_id`·`force_escalation_amount`·
> `rule_source`(+조건부 `rule_text`/`rule_file_ref`)가 없고, 아래 응답의
> `recommendedSettings`(AI 추천 정책)는 개정으로 완전히 제거됐습니다. 최신 요청·응답
> 형태는 `마법사_API_명세.md`의 `POST /v1/policy-draft` 절을 참고해 주세요.

```json
{
  "team_type": "스터디",
  "team_name": "알고리즘 스터디",
  "initial_budget": 1000000,
  "description": "주 1회 알고리즘 문제 풀이",
  "dues": 30000
}
```

API-044 권장 응답:

```json
{
  "recommendedPolicies": [
    {
      "title": "기본 회칙 초안",
      "policyType": "AI_DRAFT",
      "content": "..."
    }
  ],
  "recommendedSettings": {
    "autoApproveLimit": 50000,
    "escalationThreshold": 200000
  },
  "recommendedCategories": [
    "교재/자료비",
    "대관비"
  ],
  "notes": "..."
}
```

LLM 응답의 `confidence_threshold`는 현재 LLM 내부 판정 파라미터이므로 사용자가 직접 조정하는
팀 설정에는 넣지 않는 것을 제안합니다.

### 4-2. 2단계 — 승인 정책

> ⚠️ 낡음 — 2026-08-05 화면 개편으로 금액 칸이 `autoApproveLimit`/`escalationThreshold`
> 2개에서 `force_escalation_amount` 단일 값으로 바뀌었고, 아래 3구간 표도 소액·고액
> 2구간으로 단순화됐습니다. 최신 저장 규약은 `마법사_API_명세.md`의 "백엔드 저장 규약"
> 절을 참고해 주세요.

API-029 조회·수정 계약에 다음 필드를 모두 포함해 주세요.

```json
{
  "membershipFee": 30000,
  "autoApprove": true,
  "autoApproveLimit": 50000,
  "escalationThreshold": 200000
}
```

금액 경계는 다음처럼 고정할 것을 제안합니다.

| 구간 | 조건 | 동작 |
|---|---|---|
| 소액 | `amount < autoApproveLimit` | 모든 검사 통과 시 AI 자동 처리 가능 |
| 중간 | `autoApproveLimit <= amount < escalationThreshold` | 검사 결과와 AI 확신도에 따라 자동 또는 관리자 검토 |
| 고액 | `amount >= escalationThreshold` | 무조건 관리자 검토 |

`autoApprove=false`이면 금액과 관계없이 AI는 소견만 생성하고 최종 처리는 관리자에게 넘깁니다.

### 4-3. 3단계 — 정책 등록

API-031에서 직접 입력·파일 업로드·AI 초안 확정을 처리합니다.

정책 저장과 함께 다음 값을 관리하는 것을 제안합니다.

- `version`
- `isCurrent`
- `policyMode`: `DEFAULT` 또는 `CUSTOM`
- `sourceType`: `FILE` · `DIRECT` · `AI_DRAFT` · `SYSTEM_DEFAULT`

정책 원문과 버전을 저장한 뒤 `/v1/context/refresh`를 호출해야 합니다.

```json
{
  "team_id": "17",
  "change_type": "rule",
  "version": 1
}
```

## 5. “건너뛰기”와 단순 누락을 구분

API-009 요청에 정책이 없는 것은 아직 마법사를 완료하지 않은 `DRAFT` 상태입니다. 사용자가
3단계에서 명시적으로 “건너뛰기”를 누른 것과 같은 의미로 처리하면 안 됩니다.

권장 동작:

- API-009 직후: `policyMode=null`, `setupStatus=DRAFT`
- 사용자가 직접·파일·AI 초안을 확정: `policyMode=CUSTOM`
- 사용자가 건너뛰기 선택: 유형별 기본 조항을 버전 1 정책으로 저장하고
  `policyMode=DEFAULT`

기본 정책도 실제 정책 원문과 버전으로 저장하고 인덱싱해야, 회칙 심사 근거와 감사 이력이
남습니다.

## 6. 정책 동기화와 트랜잭션 경계

외부 LLM 호출을 API-009나 API-031의 DB 트랜잭션 안에서 실행하지 않습니다.

권장 순서:

```text
정책 원문·버전 저장
  → 같은 DB 트랜잭션에서 Outbox 이벤트 저장
  → DB 커밋
  → Outbox 워커가 /v1/context/refresh 호출
  → LLM 인덱싱 잡 완료 확인
  → policySyncStatus=READY
```

권장 상태:

| 필드 | 값 |
|---|---|
| `setupStatus` | `DRAFT` · `READY` |
| `policyMode` | `DEFAULT` · `CUSTOM` · `null` |
| `policySyncStatus` | `NOT_STARTED` · `PENDING` · `READY` · `FAILED` |

`policySyncStatus != READY`이면 자동 승인을 허용하지 않습니다. 사용자가
`autoApprove=true`로 저장했더라도 내부 Agent API가 LLM에 전달하는 유효값은
`auto_approve=false`로 내려 안전하게 관리자 검토로 전환하는 것을 제안합니다.

## 7. 지출 심사와의 연결

API-016 지출 등록 시점에는 금액만 보고 승인하지 않고 항상 `SUBMITTED`로 저장한 뒤, DB 커밋
이후 `/v1/analyze` 잡을 등록합니다.

```text
지출 SUBMITTED 저장
  → 심사 Outbox 저장
  → 커밋
  → /v1/analyze
  → /agent-callback
  → 결과·예산·감사로그를 한 트랜잭션으로 반영
```

콜백은 재시도로 중복 도착할 수 있으므로 `jobId` 또는 `(expenseId, jobId)`를 멱등 키로 사용해야
합니다.

## 8. 풀스택팀 확인 요청

| # | 확인할 내용 | LLM팀 제안 |
|---|---|---|
| 1 | 팀별 AI 프로세스를 생성하는가 | 생성하지 않음. 공용 프로세스 + `teamId` 데이터 격리 |
| 2 | API-009 범위 | `teams + team_members + budgets + 기본 team_settings` |
| 3 | `adminId` 출처 | 요청값이 아니라 인증 사용자 |
| 4 | 설정 생략 시 동작 | 기본 `team_settings` 행 생성, `autoApprove=false` |
| 5 | 정책 파일 위치 | API-031만 multipart |
| 6 | API-044 응답 | 정책 + 추천 설정 + 추천 카테고리 |
| 7 | 건너뛰기 의미 | 버전이 있는 유형별 기본 정책 생성 |
| 8 | 동기화 방식 | DB Outbox → `/v1/context/refresh` |
| 9 | 준비 상태 | `setupStatus`·`policyMode`·`policySyncStatus` |
| 10 | 준비 전 자동 승인 | 금지, 관리자 검토로 fail-safe |
| 11 | 금액 경계 | `< 자동한도`, `자동한도 이상~고액 기준 미만`, `고액 기준 이상` |
| 12 | 지출 등록 초기 상태 | 항상 `SUBMITTED`, 콜백 후 최종 반영 |

위 항목이 합의되면 각 팀은 별도 프로세스 없이도 독립된 정책과 컨텍스트를 사용하는 논리적
AI 에이전트를 갖게 됩니다. 이후 전용 SLA나 보안 격리가 필요한 고객만 별도 워커 풀 또는 전용
컨테이너로 확장할 수 있습니다.
