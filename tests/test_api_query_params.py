"""쿼리 파라미터 계약 — **실제 HTTP 계층**을 지나가는 테스트.

이 파일이 있는 이유: 2026-08-07에 `GET /v1/context/status`·`/v1/policy-params/status`·
`/v1/proposals` 세 경로가 **어떤 값을 넣어도 422**인 상태로 있었다. 원인은 요청 본문용
strict 타입(`BigIntId`)을 쿼리 파라미터에 쓴 것 — 쿼리 값은 HTTP상 언제나 문자열이라
strict 검증을 통과할 수 없다. 마법사 2·3단계와 관리자 제안함 화면이 통째로 죽는 상태였다.

오래 안 잡힌 이유가 둘이다.
  · `openapi.json`에는 `WithJsonSchema` 덕에 멀쩡한 `integer/int64`로 나온다.
  · 기존 API 테스트가 핸들러 함수를 **직접** 부른다(`await read_context_status(11)`).
    파이썬 int를 그대로 넘기니 라우팅·쿼리 파싱 계층이 통째로 검증에서 빠졌다.

그래서 여기서는 TestClient로 **URL을 쳐서** 확인한다. 다만 보려는 것은 쿼리 파싱이지
DB가 아니므로, 저장 계층은 목으로 막아 DB 없이 돈다(lifespan을 태우지 않는다 —
`TestClient`를 컨텍스트 매니저로 쓰지 않으면 풀이 열리지 않는다).
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.schemas.ids import BIGINT_MAX

TOKEN = {"Authorization": "Bearer dev-service-token-change-me"}

# 문서(`docs/마법사_API_명세.md`)가 안내하는 호출 형태 그대로
QUERY_ENDPOINTS = [
    ("/v1/context/status", "team_id", "마법사 3단계 — 회칙 반영 확인"),
    ("/v1/policy-params/status", "organization_id", "마법사 2단계 — 설정 확인"),
    ("/v1/proposals", "team_id", "관리자 제안함 (LLM-015)"),
    ("/v1/policy-proposals", "team_id", "회칙 초안 목록 (LLM-019)"),
]

_EMPTY_STATUS = {"chunk_count": 0, "version": None, "indexed_at": None}


@pytest.fixture
def client():
    """DB를 타는 자리만 막고 HTTP 계층을 그대로 태운다."""
    with (
        patch("app.api.context.get_context_status", AsyncMock(return_value=_EMPTY_STATUS)),
        patch("app.api.proposals.list_proposals", AsyncMock(return_value=[])),
        patch("app.api.drafts.list_proposals", AsyncMock(return_value=[])),
        patch("app.api.analyze.insert_job", AsyncMock(return_value="job-1")),
    ):
        yield TestClient(app)   # 컨텍스트 매니저로 쓰지 않는다 = lifespan·DB 풀 없음


@pytest.mark.parametrize("path,param,screen", QUERY_ENDPOINTS)
def test_query_endpoints_accept_a_normal_id(client, path, param, screen):
    """평범한 팀 ID로 부르면 열려야 한다 — 422면 그 화면이 통째로 죽는다."""
    r = client.get(f"{path}?{param}=17", headers=TOKEN)
    assert r.status_code == 200, f"{screen}: {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("path,param,_screen", QUERY_ENDPOINTS)
@pytest.mark.parametrize("bad", ["0", "-1", "abc", ""])
def test_query_endpoints_still_reject_bad_ids(client, path, param, _screen, bad):
    """strict를 뺀 대신 범위 검사는 남아 있어야 한다 — 0·음수·비숫자는 거절."""
    r = client.get(f"{path}?{param}={bad}", headers=TOKEN)
    assert r.status_code == 422, f"{path}?{param}={bad} → {r.status_code}"


def test_request_body_ids_stay_strict(client):
    """**본문**의 strict 계약은 그대로다 — 숫자처럼 보이는 문자열도 422.

    `docs/풀스택_연동_계약.md` §2-1의 타입 표가 약속한 동작이다. 쿼리 쪽을 고치면서
    본문까지 느슨해지면 그 계약이 깨진다.
    """
    r = client.post(
        "/v1/analyze",
        headers=TOKEN,
        json={"jobId": "be-1", "expenseId": "4821", "organizationId": 17},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "int_type"


def test_body_accepts_real_integers(client):
    """반대로 진짜 정수는 통과해야 한다 (202 접수)."""
    r = client.post(
        "/v1/analyze",
        headers=TOKEN,
        json={"jobId": "be-http-test-1", "expenseId": 4821, "organizationId": 17},
    )
    assert r.status_code == 202, r.text[:200]


# ── 상한(BIGINT_MAX) 경계 (2026-08-09 리뷰 지적 — 하한만 덮여 있었다) ─────────
#
# 위 테스트들은 `gt=0`(0·음수 거절)만 확인한다. `le=BIGINT_MAX` 쪽은 아무도 안 봤다.
# 이 경계가 중요한 건, 백엔드 PK가 BIGINT라 **상한값 자체는 실제로 올 수 있는 ID**이기
# 때문이다 — 여기서 잘못 막으면 멀쩡한 지출이 422가 되고, 반대로 상한을 놓치면
# 범위를 넘는 값이 그대로 DB 질의까지 내려간다.


@pytest.mark.parametrize("path,param,_screen", QUERY_ENDPOINTS)
def test_query_accepts_bigint_upper_bound(client, path, param, _screen):
    """상한값 자체는 유효한 ID다 — `le`는 포함 경계여야 한다."""
    r = client.get(f"{path}?{param}={BIGINT_MAX}", headers=TOKEN)
    assert r.status_code == 200, f"{path}?{param}={BIGINT_MAX} → {r.status_code}"


@pytest.mark.parametrize("path,param,_screen", QUERY_ENDPOINTS)
def test_query_rejects_over_bigint_max(client, path, param, _screen):
    """상한을 1 넘으면 422 — BIGINT 범위를 벗어난 값은 DB까지 가면 안 된다."""
    r = client.get(f"{path}?{param}={BIGINT_MAX + 1}", headers=TOKEN)
    assert r.status_code == 422, f"{path}?{param}={BIGINT_MAX + 1} → {r.status_code}"


def test_body_ids_respect_bigint_bounds(client):
    """본문(strict) 쪽도 같은 경계 — 상한값은 접수, 초과는 422."""
    ok = client.post(
        "/v1/analyze",
        headers=TOKEN,
        json={"jobId": "be-max", "expenseId": BIGINT_MAX, "organizationId": BIGINT_MAX},
    )
    assert ok.status_code == 202, ok.text[:200]

    over = client.post(
        "/v1/analyze",
        headers=TOKEN,
        json={"jobId": "be-over", "expenseId": BIGINT_MAX + 1, "organizationId": 17},
    )
    assert over.status_code == 422, over.text[:200]
