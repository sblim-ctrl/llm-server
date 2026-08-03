# AI 마법사 API 명세

| 화면 | LLM 서버 API |
|---|---|
| 모임 생성 | 없음 (백엔드) |
| 1단계 회비·예산 | `GET /v1/categories` — 카테고리 추천 목록 |
| 2단계 승인 정책 | 없음 (백엔드) |
| 3단계 회칙·규정 | `POST /v1/policy-draft` — AI 초안 |
| 3단계 등록 후 | `POST /v1/context/refresh` — 회칙 반영 알림 |

회비 저장, 승인 정책 저장, 회칙 파일 업로드·직접 입력은 백엔드 소관이라 LLM 서버 호출이
없다.

## GET /v1/categories

모임 유형별 지출 카테고리를 돌려준다. 1단계 화면의 "모임 유형 ㅇㅇ에 맞는 지출 카테고리를
AI가 자동으로 추천해 드려요" 안내에 쓰는 목록이다.

목록은 **유형당 6개 고정값**이며 AI가 새로 만들지 않는다. 그럼에도 API로 여는 이유는
심사할 때 지출을 분류하는 카탈로그와 같은 원본이기 때문이다. 백엔드가 별도로 갖고 계시면
두 목록이 어긋날 수 있고, 그러면 관리자가 화면에서 고른 카테고리가 심사 쪽에서는 모르는
값이 된다.

```
GET /v1/categories                    5개 유형 전부
GET /v1/categories?team_type=스터디    해당 유형만
Authorization: Bearer {SERVICE_TOKEN}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `teams[].team_type` | string | 모임 유형 |
| `teams[].categories` | string[] | 카테고리 6개 |
| `teams[].fallback` | string | 분류가 어느 항목에도 안 걸릴 때 쓰는 기본값. 항상 `categories` 안에 있다 |

```json
{
  "teams": [
    {
      "team_type": "스터디",
      "categories": ["교재/자료비", "온라인/구독비", "공간/대관비",
                     "인쇄/문구비", "식비/다과비", "실습/프로젝트비"],
      "fallback": "실습/프로젝트비"
    }
  ]
}
```

| 코드 | 상황 |
|---|---|
| 401 | 서비스 토큰 없음·불일치 |
| 404 | `team_type`이 다섯 값 밖 (응답에 가능한 값 목록을 함께 준다) |

> 현재 이 카테고리는 백엔드 지출 카테고리 7종과 겹치는 항목이 없다. 협의 결과에 따라
> 목록이 바뀔 수 있다(`풀스택_회신요청.md` 3번).

## POST /v1/policy-draft

회칙 초안과 승인 정책 추천값을 만든다. **동기 방식**이라 결과를 그 자리에서 돌려준다
(202 접수 후 콜백이 아니다). `teamId`는 받지 않는다.

```
POST /v1/policy-draft
Authorization: Bearer {SERVICE_TOKEN}
Content-Type: application/json
```

### 요청

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `team_type` | string | O | `동아리/학생회` · `스터디` · `친목` · `동호회` · `회사` 중 하나 (슬래시까지 일치) |
| `team_name` | string | O | 모임 이름 |
| `initial_budget` | integer | O | 원 단위 총액, 0보다 커야 함. 한도 계산 기준 |
| `dues` | integer \| null | X | 1인당 회비 (마법사 1단계 입력). `null`·`0` 둘 다 "없음" |
| `description` | string | X | 모임 소개. 있으면 AI가 맞춤 조항을 추가한다 |
| `member_count` | integer \| null | X | 현재 미사용 |

```json
{
  "team_type": "동아리/학생회",
  "team_name": "산악부",
  "initial_budget": 1000000,
  "dues": 30000,
  "description": "주말 등산과 캠핑을 즐기는 동아리입니다. 3월 신입 모집도 준비 중입니다."
}
```

### 응답 200

| 필드 | 타입 | 설명 |
|---|---|---|
| `rules` | string[] | 회칙 초안. 조항 단위 배열 |
| `policy_params.auto_approve_limit` | integer | 자동승인 한도. `초기예산 × 유형별 비율`, 만원 단위 내림, 최소 10,000 |
| `policy_params.force_escalation_amount` | integer | 관리자 확인 금액. `auto_approve_limit × 4` |
| `policy_params.confidence_threshold` | number | AI 확신도 임계값 (기본 0.8). LLM 내부값 |
| `policy_params.auto_approve` | boolean | 자동 심사 사용 추천 (기본 `true`). 2단계 토글과 **반대 방향** — 토글을 켜면 `false` |
| `recommended_categories` | string[] | 유형별 지출 카테고리 6개 (고정) |
| `notes` | string | 생성 근거 한 줄 |

```json
{
  "rules": [
    "모든 지출은 영수증(현금영수증·카드전표)을 첨부해야 하며, 미첨부 시 지출로 인정하지 않는다.",
    "1인당 식비는 회당 30,000원을 초과할 수 없다.",
    "개인 용도 물품 구입은 회비 지출로 인정하지 않는다.",
    "행사비는 행사 계획을 사전 공유한 건에 한해 집행한다.",
    "50,000원 이하의 지출은 AI 자동 심사로 처리하고, 초과 건은 관리자 승인을 받는다.",
    "회비는 1인당 30,000원으로 하며, 회비 수입 범위 내에서 지출을 집행한다.",
    "야외·활동성 행사에 필요한 안전장비(구급용품 등) 구입은 활동 안전을 위한 지출로 우선 인정한다.",
    "신입 모집 관련 홍보물 제작비는 모집 기간 내 집행 건에 한해 인정한다."
  ],
  "policy_params": {
    "auto_approve_limit": 50000,
    "force_escalation_amount": 200000,
    "confidence_threshold": 0.8,
    "auto_approve": true
  },
  "recommended_categories": [
    "행사/프로그램비", "홍보/콘텐츠비", "교육/강연비",
    "식비/간식비", "회의/운영비", "물품/소모품비"
  ],
  "notes": "'산악부' (동아리/학생회) 초기예산 1,000,000원 · 회비 30,000원 기준 자동 생성 초안 — 관리자 검토 후 확정"
}
```

조항 개수는 유형별 기본 4~5개 + 회비 1개(`dues` 있을 때) + AI 추가 0~7개(`description`
있을 때)로 정해진다. 위 예시는 5 + 1 + 2 = 8개다.

### 오류

| 코드 | 상황 |
|---|---|
| 401 | 서비스 토큰 없음·불일치 |
| 422 | 필수 필드 누락, `initial_budget` 0 이하, `team_type`이 다섯 값 밖 |
| 500 | 생성된 초안이 내부 검증 불통과 (`{"detail": "초안 검증 실패: ..."}`) |

```json
{
  "detail": [
    {"loc": ["body", "team_name"], "msg": "Field required"},
    {"loc": ["body", "initial_budget"], "msg": "Input should be greater than 0"}
  ]
}
```

## 회칙 등록 후 알림 필요

관리자가 초안을 확정해 회칙으로 등록하신 뒤에는 LLM 서버에 알려 주셔야 심사에
반영된다. 알림이 없으면 계속 이전 회칙으로 심사한다.

```
POST /v1/context/refresh
Authorization: Bearer {SERVICE_TOKEN}

{ "team_id": "team-1", "change_type": "rule", "version": 2 }
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `team_id` | string | O | 백엔드 organizationId |
| `change_type` | string | O | `rule` · `category` · `params` 중 하나. 회칙 등록·수정은 `rule` |
| `version` | integer | O | 회칙 버전 (`policies.version`) |

원문은 저희가 다시 조회하므로 위 세 값만 보내시면 된다. 202로 접수하고 인덱싱은
비동기로 처리한다.
