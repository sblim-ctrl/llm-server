"""AuthMiddleware — 백엔드 ↔ LLM 서버 상호 인증 (서비스 토큰, §4.3).

/healthz·/readyz·/docs·/ui는 제외. /ui는 페이지 껍데기만 공개고, 그 안의 API
호출(fetch)은 서비스 토큰을 실어 보내 다른 엔드포인트와 동일하게 인증된다.
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
