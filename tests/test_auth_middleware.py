"""AuthMiddleware — 서비스 토큰 경계 (§4.3).

보안 경계인데 테스트가 없었다. 특히 /mcp는 "읽기 전용이라 안전"이라는 이유로
토큰이 면제돼 있었는데, 노출 툴 4종이 전부 team_id를 인자로 받아 team_id만
바꾸면 임의 팀의 회칙·판례·예산·지출이력을 읽을 수 있었다. 그 회귀를 막는다.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware import auth as auth_mod
from app.middleware.auth import PUBLIC_PATHS, AuthMiddleware

TOKEN = "test-service-token"


def _app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """미들웨어만 단독으로 태운 앱 — 실제 라우트·DB와 무관하게 경계만 본다."""
    settings = auth_mod.get_settings().model_copy(update={"service_token": TOKEN})
    monkeypatch.setattr(auth_mod, "get_settings", lambda: settings)

    async def ok(request):
        return PlainTextResponse("ok")

    routes = [Route(p, ok, methods=["GET", "POST"])
              for p in ("/healthz", "/ui", "/mcp", "/v1/analyze")]
    app = Starlette(routes=routes)
    app.add_middleware(AuthMiddleware)
    return TestClient(app)


def test_public_paths_need_no_token(monkeypatch):
    """헬스체크·문서·데모 UI는 토큰 없이 열린다."""
    client = _app(monkeypatch)
    assert client.get("/healthz").status_code == 200
    assert client.get("/ui").status_code == 200


def test_protected_path_rejects_missing_token(monkeypatch):
    assert _app(monkeypatch).post("/v1/analyze").status_code == 401


def test_protected_path_accepts_valid_token(monkeypatch):
    client = _app(monkeypatch)
    r = client.post("/v1/analyze", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_mcp_requires_token(monkeypatch):
    """/mcp 무인증 회귀 방지.

    노출 툴은 읽기 전용이지만 team_id를 인자로 받는다 — 읽기 전용이라는 것과
    '남의 팀 데이터를 못 읽는다'는 다른 이야기다. 지출 이력에는 신청자명이 들어가
    PII 경로이기도 하다(그래프 경로는 마스킹하지만 MCP는 원문을 준다).
    """
    client = _app(monkeypatch)
    assert client.get("/mcp").status_code == 401, "/mcp가 토큰 없이 열리면 안 된다"
    r = client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_wrong_token_rejected(monkeypatch):
    client = _app(monkeypatch)
    r = client.post("/v1/analyze", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_token_compared_in_constant_time():
    """타이밍 공격 방어 — 문자열 ==가 아니라 hmac.compare_digest를 쓴다."""
    assert "compare_digest" in AuthMiddleware.dispatch.__code__.co_names


def test_mcp_not_in_public_paths():
    """면제 목록에 /mcp가 다시 들어가는 것을 막는다."""
    assert not any(p.startswith("/mcp") for p in PUBLIC_PATHS)
"""AuthMiddleware 경로별 인증 계약 테스트 (§4.3).

`/mcp`(마운트된 MCP 읽기 툴 4종)는 개발·시연 편의로 토큰이 면제돼 있었다.
읽기 전용이라도 회칙·판례·예산을 인증 없이 조회할 수 있어 면제를 제거했고,
이 테스트가 그 회귀를 막는다. 면제 경로(PUBLIC_PATHS)는 그대로 유지돼야 한다.

lifespan(DB 풀·MCP 세션)을 띄우지 않는다 — 인증은 라우팅 전 미들웨어 단계에서
끝나므로 `with` 없이 호출해도 검증되고, DB 없이 돌아간다.
"""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_public_path_needs_no_token():
    """면제 경로 회귀 방지 — /healthz는 토큰 없이 열려야 한다."""
    assert client.get("/healthz").status_code == 200


def test_mcp_requires_service_token():
    """/mcp는 더 이상 면제가 아니다 — 토큰 없이는 401."""
    res = client.get("/mcp")
    assert res.status_code == 401
    assert res.json() == {"detail": "invalid service token"}


def test_protected_path_rejects_missing_token():
    assert client.get("/v1/does-not-exist").status_code == 401


def test_protected_path_passes_with_valid_token():
    """토큰이 맞으면 미들웨어를 통과해 라우터까지 간다(없는 경로라 404)."""
    token = get_settings().service_token
    res = client.get("/v1/does-not-exist", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404
