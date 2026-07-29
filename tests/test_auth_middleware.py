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
