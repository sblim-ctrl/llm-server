"""AuthMiddleware — 백엔드 ↔ LLM 서버 상호 인증 (서비스 토큰, §4.3).

면제는 PUBLIC_PATHS 6종뿐이다. /ui는 페이지 껍데기만 공개고, 그 안의 API
호출(fetch)은 서비스 토큰을 실어 보내 다른 엔드포인트와 동일하게 인증된다.
마운트된 /mcp(읽기 툴 4종, §5.2)도 토큰이 필요하다 — 읽기 전용이라도 회칙·판례·
예산이 조회되므로 면제하지 않는다(클라이언트는 Authorization 헤더를 실어야 한다).
TODO: RateLimitMiddleware(팀별 속도 제한).
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

PUBLIC_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json", "/redoc", "/ui"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {get_settings().service_token}"
        if not hmac.compare_digest(auth, expected):
            return JSONResponse(status_code=401, content={"detail": "invalid service token"})
        return await call_next(request)
