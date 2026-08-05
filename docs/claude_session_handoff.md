# Claude Session Handoff — BudgetOps

> 작성 2026-08-04 밤 (같은 날 저녁판 대체). **이 세션에서 실제로 확인한 사실만** 담았다.
> 코드의 최신 진실은 항상 `git log`와 실제 코드다.

---

## 1. 30초 요약

- **서비스**: BudgetOps — 모임 지출을 AI가 회칙·예산·판례로 1차 심사하고, 확신 없는 건만
  관리자에게 넘긴다. 리포 `llm-server`(LLM팀).
- **사용자 = 개발자 A** (브랜치 `cowbro`) / **팀장 = 개발자 B** (브랜치 `sblim`)
- 🔴 **배포가 2026-08-06(모레)이다.** GCP.
- ✅ **브랜치 통합 끝났다.** cowbro가 sblim을 다 품었고 [PR #9](https://github.com/cowbrooo/llm-server/pull/9)로
  main에 올려둔 상태 — **팀장 리뷰 대기**.
- 🔴 **배포 최대 리스크는 백엔드 내부 조회 API 8종이다.** 없으면 배포해도 심사가 시작조차
  안 된다. 아직 못 받았다.
- ✅ `pytest` 369 통과 · 실모드 스모크 6/6 · 배포 전 점검 7건 통과 · 미푸시 0.

---

## 2. 지금 상태

| | |
|---|---|
| `origin/cowbro` | `48edde8` (로컬과 동기화) |
| `origin/sblim` | cowbro에 **전부 머지됨** — 남은 커밋 0 |
| PR #9 | cowbro → main, 100커밋(A 69·B 31), 충돌 0. **리뷰 대기** |
| PR #7 | `fix/openapi-drift` — 내용은 이미 cowbro에 있음. 닫아도 됨 |
| PR #4 | `docs-handover` — 불필요 판단, 머지 안 함 |

**PR #9가 머지되면 main에서 새로 분기해 다음 업무분장을 시작한다** (팀장 권장).

### 🔴 팀장 리뷰에서 확인받아야 하는 것 2건

통합 순서가 엇갈렸다. 팀장은 "cowbro 단독 PR → sblim에서 충돌 해소"를 원했는데, 그
메시지를 받기 전에 이미 머지가 끝나 있었다. 그래서 **팀장이 직접 하려던 판단을 A가
대신한 것이 둘** 있다. PR #9 §2에 적어뒀다.

- **골든셋을 합집합 68건으로 만들었다** (sblim 60 + cowbro 전용 8). cowbro 전용 8건은
  `autoclassify` 2·`mismatch-002` 3·`gate-priority`·`boundary-003`·`budget-edge`.
  의도적으로 뺀 것이면 되돌려야 한다.
- **대외 회신 문서 4종은 양쪽을 다 살렸다.** 중복 문항이 생겼을 수 있다.

---

## 3. 이 세션에서 한 일

### 3-1. 브랜치 통합 (팀장 결정 6항목)

| # | 결정 | 반영 |
|---|---|---|
| 1 | cowbro 기본 정책 모드 | `rule_auditor.py` 호출 지점 3개 유지 |
| 2 | v4 생성 | `adjudicator/v4` — sblim v3 + cowbro v3의 두 문장 |
| 3 | judge 유지 | cowbro 7파일 |
| 4 | sblim 방식 | `digest_writer/v2`·`policy_drafter/v2` |
| 5 | v4의 ②만 | `rule_auditor/v3` few_shot 형식 정합화 |
| 6 | main PR | PR #9 |

### 3-2. 통합이 잡은 회귀 — `intake/v3`

**이번 통합의 가장 큰 소득이다.** 머지로 `intake`가 v2로 바뀌자 실모드 스모크가 6건 중
5건 `receipt_unreadable`로 무너졌다. v2가 **상호·품목 없는 추출 텍스트를
`parse_ok=false`로 판정**하는데, 그게 가드레일의 `receipt_unreadable` → 전건 관리자
확인이 된다. 백엔드가 주는 추출 텍스트에는 상호가 없는 경우가 흔해서 **운영 자동
처리율을 통째로 죽이는 결함**이었다. 통합 안 했으면 배포 후에 발견됐을 것이다.

`intake/v3`으로 `parse_ok`의 정의를 못박고(“읽어냈는가이지 전부 있었는가가 아니다”)
상호 없이 금액만 읽은 예시 2건을 추가 → 6/6 복구.

### 3-3. 풀스택 협의 2026-08-04 반영분

- **카테고리 전역 9종 확정** — 회의·IT/인프라·행사/활동·장소/대관·교육·식비·교통·
  비품·기타. 유형별 30종 체계를 걷어냈다.
- **`classifier` v3→v4→v5** 실측 승격 — 78.6% → 92.9% → **100%** (각 2회 재현).
- **증빙 심사관** — 영수증 대조를 네 번째 심사관 소견으로. OCR 상호명까지 노출.
- **카테고리 직접 입력 삭제 대응** — AI가 유일한 출처가 되므로 저확신(<0.8) 시 키워드
  폴백. 키워드 순서 버그 2건도 실측으로 잡았다(88.2% → 100%).
- **신규 API 3종** — `GET /v1/policy-params/status`(2단계 설정 반영 확인) ·
  `POST /v1/dashboard/summary`(대시보드 요약) · `POST·GET /v1/policy-proposals`(회칙 초안).

### 3-4. 새 도구 (배포·검증용)

```bash
uv run python scripts/predeploy_check.py            # 배포 전 자동 점검 7건
MOCK_LLM=false uv run python scripts/smoke_real_mode.py   # 실모드 심사 6건 (~$0.10)
MOCK_LLM=false uv run python scripts/ab_classifier.py v4 v5  # 분류기 A/B
uv run python scripts/wizard_step2_matrix.py        # 마법사 2단계 구간표
```

`smoke_real_mode.py`는 골든셋이 깨져 있는 동안 실모드를 확인할 유일한 수단이다.
빈 DB(`budgetops_smoke`)를 따로 만들어 스키마를 새로 적용하므로 **BIGINT 마이그레이션이
깨끗한 DB에서 통과하는지**까지 확인된다 — 운영 DB가 바로 그 상태다.

---

## 4. 🔴 배포까지 남은 것 (D-2)

### 4-1. 백엔드 내부 조회 API 8종 — 최대 리스크

우리는 pull 모델이라 `POST /v1/analyze`로 번호 5개만 받고 지출 상세·승인 정책·모임
유형·멤버를 되물어야 심사가 시작된다. **그 API가 없으면 배포해도 첫 호출에서 멈춘다.**
아직 못 받았다. 이게 1순위다.

### 4-2. 마법사 2단계 화면이 코드와 다르다

실측으로 확인했다. 재현: `uv run python scripts/wizard_step2_matrix.py`

- **화면의 금액 입력이 판정에 아무 영향을 안 준다.** 두 금액 규칙이 둘 다 '관리자 확인'
  으로 귀결돼 실제로는 작은 쪽 하나만 작동한다. 10만/20만/30만 어느 걸 골라도 같다.
- **"중간 지출 → 대기/자동"에서 '자동'은 코드에 없다.** 3구간 개념 자체가 없다.
- **경계가 1원 어긋난다.** 코드는 `> 한도`라 50,000원은 자동 승인인데 화면은 "미만".

**제안은 입력을 자동승인 한도 하나로 줄이는 것**이다. 3구간을 지탱하려면 금액 가드레일을
걷어내야 하는데, 그건 이미 측정했고 **오승인 5건**이 나왔다(정확도 100%→88%).

### 4-3. 백엔드에 확인 필요

- **`suggestedCategory`가 '제안'이 아니라 '확정값'이 됐다.** 카테고리 직접 입력이
  없어지면서 AI 분류가 유일한 출처다. 백엔드가 이 값을 `expenses.category`에 그대로
  저장하는지 확인해야 한다. 안 하면 카테고리가 통째로 빈다.
- `expenses.category` ENUM을 확정 9종으로 맞췄는지.

### 4-4. 배포 당일

```bash
uv run python scripts/predeploy_check.py     # 코드 쪽은 이걸로 한 번에
```

배포 후 **`GET /readyz`가 200인지** 확인한다. 환경변수(`SERVICE_TOKEN`·`MOCK_LLM=false`)
누락은 여기서 잡힌다 — 빠뜨리면 인증이 사실상 없거나 가짜 판정이 나가는데 겉보기엔 정상이다.

---

## 5. 아직 못 한 것

### 5-1. 골든셋이 여전히 깨져 있다

`uv run python eval/run_eval.py`는 `apply_schema()`에서 죽는다. 개발 DB에 옛 문자열 ID
행이 1,174개 남아 BIGINT 마이그레이션이 거부된다(`precedents` 1,020 · `jobs` 100 ·
`context_chunks` 47 · `proposals` 7). `eval/` 스크립트 7개가 전부 이걸 부른다.

그 벽을 넘어도 두 번째 벽이 있다 — 목 규약이 ID에 데이터를 싣는 방식이라 68건 전부
`AnalyzeRequest` 검증에 걸린다. `organizationId`에도 단서가 넷 더 있다
(`lowbudget`·`noauto`·`noexpense`/`balanced`·유형 단서).

**대안은 `docs/internal/골든셋_목_규약_재설계안_2026-08-04.md`에 있다** — fixture 파일로
옮기는 안. 이제 브랜치 통합이 끝났으니 착수 가능하다.

카테고리도 9종으로 바꿔야 한다. 지금 골든셋 카테고리는 카탈로그 밖이라
`classify_category.py:56`에서 즉시 반환돼 **분류기가 한 번도 호출되지 않는다.**

### 5-2. 목 모드 100%는 AI 품질이 아니다

`adjudicate.py`의 목 응답은 확신도를 **0.95로 고정**한다. "확신 없으면 사람에게"
안전장치가 목 모드에서는 한 번도 작동하지 않는다. 진짜 숫자는 실모드에서만 나온다.

---

## 6. 규율 (지킬 것)

1. **프롬프트/판정 rubric 변경은 사용자와 함께 결정.** 버전을 지우지 않고 새로 만든다.
   **실측으로 재현된 개선만 승격**(2회 재현이 관례).
2. **머지 게이트**: `pytest` 전체 통과 + 골든셋 **오승인 0건**·정확도 ≥90%.
3. **AI는 승인/반려를 실행하지 않는다.** 추천만 콜백으로 보내고 실행·예산 차감은 백엔드.
4. **`.env`의 `MOCK_LLM=true`는 절대 바꾸지 말 것.** 실모드는 프로세스 주입으로만.
   테스트는 목 모드 계약이라 실모드로 돌리면 12건이 깨진다.
5. 커밋 시 **파일을 하나씩 지정**해 `git add` — `git add .`·`git add -A` 금지.
6. **팀장 브랜치·공유 문서를 임의로 고치지 않는다.** main 반영은 PR로.
7. **결함이라고 주장하기 전에 다른 브랜치를 먼저 본다.** `git log --all -- <파일>`.
8. **작업 전 머지 충돌 영향을 확인한다.** `git merge-tree --write-tree HEAD <ref>`.

### 이 프로젝트에서 반복 확인된 패턴

**규칙보다 예시가 세다.** 오늘 세 번 같은 일이 있었다 — `classifier`(용도 vs 물건 경계),
`dashboard_writer`(수치 과장), `intake`(parse_ok 의미). 세 번 다 system 규칙을 넣어도
안 지켜졌고 **few_shot에 대조 쌍을 넣으니 잡혔다.** 경계는 규칙이 아니라 예시로 가르친다.

**few_shot은 런타임 입력과 바이트 단위로 같아야 한다.** 어긋나도 에러가 아니라 조용한
품질 저하로 나타난다. `tests/test_classify_category.py`에 회귀 테스트가 있다.

---

## 7. 환경

- **Docker**: 실행 중이어야 한다 (`llm-postgres`·`llm-api`·`llm-worker`).
  꺼져 있으면 eval이 **출력 없이 멈춘다** — 타임아웃 나면 `docker compose ps`부터.
- **DB 호스트 포트는 5433**이다 (풀스택 메인 DB와 충돌 방지). 5432 아님.
- **컨테이너는 빌드 시점 코드를 굳힌다.** `git push`나 `.env` 수정으로 안 바뀐다 —
  `docker compose up -d --build llm-api llm-worker`.
- 실모드 스크립트가 `OpenBLAS` 메모리 오류를 내면 `OPENBLAS_NUM_THREADS=1`을 앞에 붙인다.

```bash
cd "C:\Users\user\final project\llm-server"
docker compose up -d llm-postgres
uv run pytest -q                             # 369 통과 기대
uv run python scripts/predeploy_check.py     # 배포 전 점검
```

---

## 8. 다음 세션 시작 프롬프트

```
docs/claude_session_handoff.md 읽고 이어서 작업해줘.
모레 배포인데 PR #9 팀장님 리뷰 대기 중이고 백엔드 내부 API 8종을 아직 못 받았어.
지금 상태에서 뭘 먼저 해야 할지 판단해주고 준비할 수 있는 것부터 해줘.
```

### 처음 확인할 파일
1. `docs/claude_session_handoff.md` — 이 문서
2. `docs/internal/작업리스트_배포전_2026-08-04.md` — 회의록 10항목 대조 + 남은 결정
3. `docs/internal/풀스택_협의_2026-08-04_반영.md` — 반영분과 미결
4. `docs/internal/골든셋_목_규약_재설계안_2026-08-04.md` — 골든셋 되살리는 안
5. `app/llm/prompts.py`의 `DEFAULT_VERSIONS` — 지금 쓰이는 프롬프트 버전
