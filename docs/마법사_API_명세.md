# AI 마법사 API 명세

| 화면 | LLM 서버 API |
|---|---|
| 모임 생성 | 없음 (백엔드) |
| 1단계 회비 설정 | `GET /v1/categories` — 카테고리 추천 목록 |
| 2단계 승인 정책 (초기값) | `POST /v1/policy-draft` 응답의 `policy_params` — AI 추천값 |
| 2단계 승인 정책 (저장) | 없음 (백엔드 `team-settings`) |
| 2단계 설정 확인 | `GET /v1/policy-params/status` — 저장한 값이 심사에 어떻게 적용되는지 |
| 3단계 회칙·규정 | `POST /v1/policy-draft` — AI 초안 |
| 3단계 등록 후 | `POST /v1/context/refresh` — 회칙 반영 알림 |
| 3단계 등록 확인 | `GET /v1/context/status` — 반영됐는지 조회 |

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

## 2단계 승인 정책 — 저장은 백엔드, 사용은 LLM 서버

이 화면에는 LLM 서버 API가 없다. 값을 저장하는 것은 백엔드 `team-settings`다. 다만
**저장된 값이 매 심사마다 우리 쪽으로 흘러 들어와 판정을 가른다.** 그래서 저장 형식이
어긋나면 화면에서 설정한 대로 심사가 안 되고, 그 사실이 화면에는 드러나지 않는다.
실제로 2026-07-31에 그 상태였다(내부 `화면_대조_2026-07-29.md` §7).

### 입력·출력 한눈에

2단계는 **저장 API만 없을 뿐 입출력이 양쪽으로 다 있다.**

| 방향 | API | 값 |
|---|---|---|
| 출력 (우리 → 화면) | `POST /v1/policy-draft` → `policy_params` | `auto_approve`, `auto_approve_limit`, `force_escalation_amount`, `confidence_threshold` — 화면 초기값 추천 |
| 저장 (화면 → 백엔드) | 백엔드 `team-settings` | `auto_approve`, `auto_approve_limit` |
| 입력 (백엔드 → 우리) | `GET /internal/agent/organizations/{id}/team-settings` (우리가 호출) | `auto_approve`, `auto_approve_limit` |
| 확인 (우리 → 화면) | `GET /v1/policy-params/status` | 저장값 + 실효 한도 + 한 줄 설명 |

> **2026-08-05 화면 개편.** 금액 입력칸이 2개("소액 자동 승인 한도" + "고액 직접 확인
> 기준")에서 1개("관리자 승인 필수 금액")로 줄었다. 이에 맞춰 백엔드가 `team_settings`의
> `escalation_threshold` 컬럼을 삭제하기로 했고, 화면의 한 칸은 `auto_approve_limit`에
> 저장한다. 우리 `POST /v1/policy-draft`는 `force_escalation_amount`를 계속 내려주지만
> 화면이 쓰지 않으며, 회칙 초안의 금액 검증에만 쓰인다.

`confidence_threshold`(θ)는 저장·조회 대상이 아니다. LLM 내부 파라미터라 백엔드가
모르고, 추천값으로 내려주기만 한다.

### 값이 흐르는 경로

```
POST /v1/policy-draft  ──추천값──▶  2단계 화면
                                      │ 관리자가 조정
                                      ▼
                            백엔드 team_settings 저장
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼ 매 심사마다 조회                                ▼ 저장 직후 확인
   GET .../team-settings                        GET /v1/policy-params/status
              │ load_context.py 매핑                            │ 같은 매핑 규칙
              ▼                                                 ▼
     PolicyParams → guardrail_gate 판정              화면에 "N원까지 자동 승인"
```

### 필드 계약 (백엔드 → LLM 서버)

| 백엔드 응답 키 | 타입 | 화면 항목 | 우리 내부 이름 | 없을 때 |
|---|---|---|---|---|
| `auto_approve` | boolean | "모든 지출을 직접 확인할래요" 토글 | `auto_approve` | `false` (안전 방향) |
| `auto_approve_limit` | integer \| null | 관리자 승인 필수 금액 (최소 50,000) | `auto_approve_limit` | `null` → **0** (전건 관리자 확인) |

주의할 점 세 가지다.

**① 토글과 `auto_approve`는 반대 방향이다.** 화면 문구가 "모든 지출을 직접 확인할래요"라
토글을 **켜면** `auto_approve = false`로 저장해야 한다. 문구와 값이 반대라 통합 시 뒤집히기
쉽다.

**② `auto_approve_limit`이 `null`이면 0으로 읽는다.** DB상 "자동 승인 사용 시에만 값 존재"라
`null`이 정상 케이스다. 0으로 읽으면 모든 금액이 한도에 걸려 관리자 확인으로 간다 — 어느
쪽으로도 해석 가능할 때 자동 승인이 되지 않는 쪽을 고른다.

**③ 삭제된 `escalation_threshold`는 한도를 축소하지 않는다.** 이 키가 응답에 없으면 우리는
`auto_approve_limit`과 같은 값으로 읽는다. 모델 기본값 200,000을 채워 넣으면
`min(관리자 설정값, 200,000)`이 되어 **관리자가 50만을 설정해도 20만부터 관리자 확인**이
되기 때문이다. 이 컬럼은 원래 금액이었고 확신도 θ가 아니었다 — 둘을 섞어 `θ = 200000.0`이
되어 전건 에스컬레이션이 될 뻔한 사고가 2026-07-31에 있었다. θ는 지금도 LLM 내부
파라미터로 분리돼 있고 백엔드에서 받지 않는다(기본 0.8).

### 경계는 "이상"이다

`amount >= limit`일 때 걸린다. 한도가 정확히 50,000원이면 **49,999원까지 자동 판정이고
50,000원부터 관리자 확인**이다.

화면 표의 "N원 미만 → 자동 승인/검토 요청", "N원 이상 → 관리자 승인 항상"과 같은 기준이다.
2026-08-05 화면 개편 전에는 코드가 "초과"라 한도와 같은 금액이 자동 판정으로 갈라져 화면과
1원 어긋났고, 이 항목은 "회의에서 확정할 것"으로 남아 있었다. 화면이 "이상"으로 확정하면서
코드를 맞췄다.

### 실측 구간표

`scripts/wizard_step2_matrix.py` 실행 결과다. 소견 3종을 전부 pass로 고정해 금액 규칙만
분리했다.

화면 최소값(관리자 승인 필수 금액 5만 / 자동 심사 켬):

| 청구액 | 판정 | 발동 규칙 |
|---|---|---|
| 10,000 | 자동 판정 진행 | — |
| 49,999 | 자동 판정 진행 | — |
| 50,000 | 관리자 확인 | `over_auto_approve_limit` |
| 50,001 | 관리자 확인 | `over_auto_approve_limit` |
| 500,000 | 관리자 확인 | `over_auto_approve_limit` |

관리자가 50만으로 올린 경우:

| 청구액 | 판정 | 발동 규칙 |
|---|---|---|
| 49,999 | 자동 판정 진행 | — |
| 200,000 | 자동 판정 진행 | — |
| 499,999 | 자동 판정 진행 | — |
| 500,000 | 관리자 확인 | `over_auto_approve_limit` |

토글을 켜면(`auto_approve=false`) 금액과 무관하게 전건 관리자 확인이다.

`escalation_threshold` 컬럼이 없으므로 `over_force_escalation_amount`는 항상
`over_auto_approve_limit`과 같은 금액에서 함께 발동한다 — 규칙 이름이 둘로 보여도
기준은 하나다.

### 해소된 항목 — 금액 칸 두 개가 사실상 하나로 동작하던 문제

화면이 소액 한도와 고액 기준을 독립된 두 설정으로 보여주던 시절, 코드에서는 **둘 다
`escalate`(관리자 확인)로 귀결돼** 실제로 자동/대기를 가르는 것은 항상 작은 쪽 하나였다.

실측으로 확인했던 내용이다.

```
고액 기준 20만 → 30만으로 올림:  판정이 달라지는 금액 없음
고액 기준 20만 → 3만으로 내림:   49,999원·50,000원의 판정이 바뀜
```

2026-08-05 화면 개편으로 칸이 하나가 되고 백엔드가 `escalation_threshold` 컬럼을
삭제하면서 이 불일치는 해소됐다. 컬럼 삭제 전에 두 값이 따로 저장된 팀은 여전히
`min(두 값)`이 실효 한도이므로, 코드는 min 계산을 그대로 유지한다.

### GET /v1/policy-params/status (신설)

2단계에서 저장한 값이 실제 심사에 어떤 기준으로 적용되는지 돌려준다. 저장 직후 호출해
`summary`를 그대로 화면에 띄우면 관리자가 "내가 설정한 대로 동작하는가"를 확인할 수 있다.

3단계의 `GET /v1/context/status`와 같은 목적이다. 2단계는 저장이 백엔드 소관이라
값이 어긋나도 화면에 드러나지 않는데, 실제로 2026-07-31에 그 상태였다(§7 참조).

**요청** — `GET /v1/policy-params/status?organization_id=9001`

**응답 200**

```json
{
  "team_id": 9001,
  "available": true,
  "auto_approve": true,
  "auto_approve_limit": 50000,
  "force_escalation_amount": 50000,
  "effective_auto_approve_limit": 50000,
  "auto_approved_up_to": 49999,
  "summary": "49,999원까지는 AI가 자동 판정하고, 50,000원부터 관리자가 확인합니다."
}
```

| 필드 | 뜻 |
|---|---|
| `available` | 백엔드 team-settings 조회 성공 여부. `false`면 아래는 fail-safe 기본값이고 심사는 전건 관리자 확인으로 진행된다 |
| `auto_approve` ~ `force_escalation_amount` | 저장된 값을 우리가 해석한 결과. `escalation_threshold` 컬럼 삭제 후로는 `force_escalation_amount`가 `auto_approve_limit`과 같은 값이다 |
| `effective_auto_approve_limit` | **실제로 자동/대기를 가르는 금액.** 두 값이 따로 저장된 팀(컬럼 삭제 전)은 작은 쪽 |
| `auto_approved_up_to` | 이 금액까지 자동 판정. 경계가 '이상'이라 실효 한도보다 1원 낮다. 자동 심사를 안 쓰거나 한도가 0이면 `null` |
| `summary` | 화면에 그대로 띄울 한 줄 설명 |

**시나리오별 응답** (실행 결과)

| 설정 | `effective_auto_approve_limit` | `auto_approved_up_to` | `summary` |
|---|---|---|---|
| 5만 / 자동 켬 | 50,000 | 49,999 | 49,999원까지는 AI가 자동 판정하고, 50,000원부터… |
| 토글 켬 (`auto_approve=false`) | 50,000 | `null` | 자동 심사를 사용하지 않습니다… |
| **50만** / 자동 켬 | 500,000 | 499,999 | 499,999원까지는 AI가 자동 판정하고, 500,000원부터… |
| 한도 `null` | 0 | `null` | 자동 승인 구간이 없어 모든 지출을 관리자가 확인합니다. |
| 잔존 데이터 15만 / 20만 | 150,000 | 149,999 | 149,999원까지는 AI가 자동 판정하고, 150,000원부터… |

세 번째 줄이 "컬럼 삭제 후에도 관리자 설정값이 축소되지 않는다"는 증거다 — 모델 기본값
200,000을 채워 넣었다면 실효 한도가 200,000으로 줄었을 것이다.

### 해소된 항목 — 필드를 누락하면 자동 승인이 열리던 문제

백엔드 응답에 `auto_approve_limit` **키 자체가 없을 때** 예전 심사 경로는 모델 기본값
50,000원을 써서, 백엔드가 필드를 빠뜨리면 5만원까지 조용히 자동 승인됐다.

2026-08-04 브랜치 통합에서 누락과 `null`을 똑같이 0(전건 관리자 확인)으로 보도록
통일해 해소했고, `tests/test_wizard_step2_mapping.py`가 이 분기를 감시한다. 다만
**백엔드는 이 필드를 항상 보내 주시는 편이 안전하다** — 값이 없으면 `null`을 명시해
주시면 된다.

### 회의에서 확정할 것

1. ~~**경계 문구.**~~ **해소** (2026-08-05) — 화면이 "N원 이상"으로 확정해 코드를 `>=`로
   맞췄다. 한도 50,000이면 49,999원까지 자동, 50,000원부터 관리자 확인이다.
2. ~~**고액 기준 칸의 용도.**~~ **해소** (2026-08-05) — 화면 금액 칸이 하나로 합쳐지고
   백엔드가 `escalation_threshold` 컬럼을 삭제하기로 했다.
3. **토글 저장 방향.** 켬 = `auto_approve: false`. 백엔드 저장 시점에 반전하는지, 화면에서
   반전해 보내는지 어느 쪽인지 정해야 한다.
4. **`auto_approve` 추천값 전달 통로.** 우리 `POST /v1/policy-draft`가 추천값을 내려주는데
   (아래 절 `policy_params.auto_approve`), 2단계 화면이 이 값을 받아 토글 초기 상태로
   쓸지 확정이 필요하다. 현재 추천 기본값은 `true`(자동 심사 사용 = 토글 꺼짐)다.
5. **컬럼 삭제 시점.** 우리 매핑 수정이 배포된 뒤에 백엔드가 `escalation_threshold`를
   지워야 한다. 순서가 반대면 관리자 설정값이 모델 기본값 200,000으로 축소된다.

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
| `policy_params.auto_approve_limit` | integer | 관리자 승인 필수 금액 추천값. `초기예산 × 유형별 비율`, 만원 단위 내림, **최소 50,000** (화면 최소 제약과 같은 값 — 더 낮으면 화면이 거부한다) |
| `policy_params.force_escalation_amount` | integer | `auto_approve_limit × 4`. 화면 금액 칸이 하나로 합쳐진 뒤로는 화면이 쓰지 않으며, 회칙 초안의 금액 검증에만 쓰인다 |
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
    "50,000원 미만의 지출은 AI 자동 심사로 처리하고, 50,000원 이상은 관리자 승인을 받는다.",
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

## POST /v1/context/refresh

관리자가 초안을 확정해 회칙으로 등록하신 뒤에는 LLM 서버에 알려 주셔야 심사에
반영된다. 알림이 없으면 계속 이전 회칙으로 심사한다. 파일 업로드·직접 입력으로
등록하신 경우에도 마찬가지다.

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
비동기로 처리한다. 응답의 `job_id`로 `GET /v1/jobs/{job_id}`를 조회하면 그 건의 처리
결과를 볼 수 있다.

## GET /v1/context/status

회칙이 실제로 심사에 반영될 수 있는 상태인지 알려준다. 인덱싱이 비동기라 `/refresh`가
202를 돌려준 뒤 실패해도 알 방법이 없는데, 그 경우 관리자는 회칙을 등록했다고 알고
있지만 심사는 회칙 없이 진행된다. 등록 직후 이 값을 확인해 주시면 그 상황을 막을 수
있다.

```
GET /v1/context/status?team_id=team-1
Authorization: Bearer {SERVICE_TOKEN}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `indexed` | boolean | `false`면 회칙 기준 심사가 되지 않는다 |
| `chunk_count` | integer | 인덱싱된 조항 수 |
| `version` | integer \| null | 반영된 회칙 버전 |
| `indexed_at` | string \| null | 인덱싱 시각 (ISO8601) |

```json
{
  "team_id": "team-1",
  "indexed": true,
  "chunk_count": 12,
  "version": 2,
  "indexed_at": "2026-08-03T10:30:00"
}
```

`indexed: true`면 "AI가 회칙 12개 조항을 읽었어요"처럼 보여주실 수 있다.

`indexed: false`는 오류가 아니다. 회칙을 등록하지 않았거나 건너뛴 팀의 정상 상태이며,
그 팀은 모임 유형별 기본 정책으로 심사된다. 기본 정책 모드에서는 반려 판정을 내리지
않고 관리자 확인으로만 보내며, 예산·판례 심사는 평소대로 동작한다.
