"""/healthz (liveness) · /readyz (readiness — DB 도달성) (§10.2)."""
from fastapi import APIRouter, Response

from app.db.pool import get_pool

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response):
    try:
        async with get_pool().connection() as conn:
            await conn.execute("SELECT 1")
    except Exception:
        response.status_code = 503
        return {"status": "not_ready", "db": "unreachable"}
    return {"status": "ready", "db": "ok"}
