"""RequestLogMiddleware — 구조화 로깅(JSON), request_id 전파 (§4.3)."""
import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(json.dumps({
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
        }, ensure_ascii=False))
        response.headers["X-Request-Id"] = request_id
        return response
