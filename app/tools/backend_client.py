"""풀스택 백엔드 API 클라이언트 (§7.2 '백엔드 제공' 계약).

연동 방식이 확정되지 않았으므로 MOCK_BACKEND=true(기본)로 개발한다.
실제 엔드포인트 경로·인증이 확정되면 이 파일의 URL만 바꾸면 된다 — 노드 코드는 불변.
"""
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().service_token}"}


async def get_budget_status(team_id: str, category: str) -> dict[str, Any]:
    """GET {BE}/internal/agent/teams/{id}/budget — 잔액·한도·사용률."""
    s = get_settings()
    if s.mock_backend:
        # 개발용 고정값: 한도 30만, 기사용 11.8만
        return {"category": category, "limit": 300_000, "spent": 118_000}
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(f"/internal/agent/teams/{team_id}/budget",
                             params={"category": category})
        r.raise_for_status()
        return r.json()


async def get_expense_history(team_id: str, **filters: Any) -> list[dict[str, Any]]:
    """GET {BE}/internal/agent/teams/{id}/expenses — 중복 청구 탐지용."""
    s = get_settings()
    if s.mock_backend:
        return []
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(f"/internal/agent/teams/{team_id}/expenses", params=filters)
        r.raise_for_status()
        return r.json()


async def approve_expense(expense_id: str, idempotency_key: str, reason: str) -> dict[str, Any]:
    """POST {BE}/internal/agent/expenses/{id}/approve — 멱등성 키 필수 (REQ-023)."""
    s = get_settings()
    if s.mock_backend:
        logger.info("MOCK approve: expense=%s key=%s", expense_id, idempotency_key)
        return {"status": "AI_APPROVED", "mock": True}
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.post(
            f"/internal/agent/expenses/{expense_id}/approve",
            headers={"Idempotency-Key": idempotency_key},
            json={"reason": reason},
        )
        if r.status_code == 409:  # 이미 처리됨 — 이중 차감 없음 (§8)
            return {"status": "duplicate", "idempotent": True}
        r.raise_for_status()
        return r.json()


async def reject_expense(expense_id: str, idempotency_key: str, reason: str) -> dict[str, Any]:
    """POST {BE}/internal/agent/expenses/{id}/reject."""
    s = get_settings()
    if s.mock_backend:
        logger.info("MOCK reject: expense=%s key=%s", expense_id, idempotency_key)
        return {"status": "AI_REJECTED", "mock": True}
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.post(
            f"/internal/agent/expenses/{expense_id}/reject",
            headers={"Idempotency-Key": idempotency_key},
            json={"reason": reason},
        )
        if r.status_code == 409:
            return {"status": "duplicate", "idempotent": True}
        r.raise_for_status()
        return r.json()


async def send_callback(payload: dict[str, Any]) -> bool:
    """POST {BE}/agent-callback — 실패해도 예외 없이 False (백엔드가 폴링 fallback)."""
    s = get_settings()
    if s.mock_backend:
        logger.info("MOCK callback: verdict=%s expense=%s",
                    payload.get("verdict"), payload.get("expense_id"))
        return True
    try:
        async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
            r = await client.post("/agent-callback", json=payload, timeout=10)
            r.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception("callback failed — 백엔드 폴링 fallback에 위임")
        return False
