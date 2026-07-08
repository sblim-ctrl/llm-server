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
        # 목 규약: team_id에 "lowbudget" 포함 → 잔액 부족 예산 (반려 케이스 생성용)
        if "lowbudget" in team_id:
            return {"category": category, "limit": 20_000, "spent": 19_000}
        # 기본 고정값: 한도 30만, 기사용 11.8만
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


async def get_team_members(team_id: str) -> list[dict[str, Any]]:
    """팀 멤버 명단(실명·역할) — PIIMasker 치환용 (§4.3).

    엔드포인트 경로는 풀스택 팀과 미확정. 목: 고정 명단.
    """
    s = get_settings()
    if s.mock_backend:
        return [
            {"name": "김철수", "role": "총무"},
            {"name": "이영희", "role": "회원"},
            {"name": "박민준", "role": "회원"},
        ]
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(f"/internal/agent/teams/{team_id}/members")
        r.raise_for_status()
        return r.json()


async def get_policy_document(team_id: str, doc_type: str, version: int) -> str:
    """회칙·카테고리 원문 조회 — 인덱싱 파이프라인 1단계 (REQ-041, §4.4-a).

    /v1/context/refresh 이벤트에는 원문이 없고 team_id·변경유형·버전만 오므로,
    실제 텍스트는 이 함수로 백엔드에 되물어야 한다. 정확한 엔드포인트 경로는
    풀스택 팀과 아직 미확정(§7.2 목록에 없음) — 확정되면 아래 URL만 교체하면 됨.
    """
    s = get_settings()
    if s.mock_backend:
        if doc_type == "rule":
            return (
                "제1조 (목적) 이 회칙은 동아리 활동비 집행 기준을 정한다.\n\n"
                "제2조 (회식비 한도) 1인당 회식비는 3만원을 초과할 수 없다.\n\n"
                "제3조 (금지 항목) 개인 용도 물품 구입은 지출로 인정하지 않는다.\n\n"
                "제4조 (도서 구입) 스터디 관련 도서는 인당 연 5만원 한도로 인정한다.\n\n"
                f"(mock rule text, team={team_id}, version={version})"
            )
        return f"(mock {doc_type} text, team={team_id}, version={version})"
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(
            f"/internal/agent/teams/{team_id}/policy-document",
            params={"doc_type": doc_type, "version": version},
        )
        r.raise_for_status()
        return r.json()["text"]


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
