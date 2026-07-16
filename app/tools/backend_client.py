"""풀스택 백엔드 API 클라이언트 (§7.2 '백엔드 제공' 계약).

연동 방식이 확정되지 않았으므로 MOCK_BACKEND=true(기본)로 개발한다.
실제 엔드포인트 경로·인증이 확정되면 이 파일의 URL만 바꾸면 된다 — 노드 코드는 불변.
"""
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().service_token}"}


async def get_budget_status(team_id: str, category: str | None = None) -> dict[str, Any]:
    """GET {BE}/internal/agent/teams/{id}/budget — 총예산·승인 지출 합계.

    [팀 확인 2026-07-09] 예산 = 모임 전체 총액. 잔액 = total_budget − spent(승인 합계).
    category는 내역 조회용 선택 파라미터 (한도 검사 기준 아님).
    """
    s = get_settings()
    if s.mock_backend:
        # 목 규약: team_id에 "lowbudget" 포함 → 잔액 부족 (반려 케이스 생성용, 잔액 1,000원)
        if "lowbudget" in team_id:
            return {"total_budget": 20_000, "spent": 19_000}
        # 기본 고정값: 총예산 30만, 승인 지출 11.8만
        return {"total_budget": 300_000, "spent": 118_000}
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(f"/internal/agent/teams/{team_id}/budget",
                             params={"category": category} if category else None)
        r.raise_for_status()
        return r.json()


async def get_expense_history(team_id: str, **filters: Any) -> list[dict[str, Any]]:
    """GET {BE}/internal/agent/teams/{id}/expenses — 중복 탐지·리포트 집계용."""
    s = get_settings()
    if s.mock_backend:
        # 목 규약 (골든셋·데모와 공유하는 team_id 단서 — §7 '규약을 깨지 말 것'):
        #   "noexpense" 포함 → 지출 없음 (빈 기간 리포트 시나리오)
        #   "balanced"  포함 → 편중·저활용 없는 균형 지출 (추천이 top 건 안내만 나와야 함)
        if "noexpense" in team_id:
            return []
        if "balanced" in team_id:
            return [
                {"title": "분기 회식", "amount": 90000, "category": "식비", "date": "2026-06-06", "status": "APPROVED"},
                {"title": "세미나실 대관", "amount": 75000, "category": "대관", "date": "2026-06-13", "status": "APPROVED"},
                {"title": "공용 교재", "amount": 75000, "category": "도서", "date": "2026-06-20", "status": "APPROVED"},
                {"title": "모임 다과", "amount": 60000, "category": "다과", "date": "2026-06-27", "status": "APPROVED"},
            ]
        # 결정적 샘플 이력 (리포트 개발용) — 계약 확정 시 실 API로 교체
        return [
            {"title": "정기 회식", "amount": 84000, "category": "식비", "date": "2026-06-05", "status": "APPROVED"},
            {"title": "스터디룸 대관", "amount": 40000, "category": "대관", "date": "2026-06-08", "status": "APPROVED"},
            {"title": "교재 3권", "amount": 54000, "category": "도서", "date": "2026-06-12", "status": "APPROVED"},
            {"title": "간식", "amount": 18000, "category": "다과", "date": "2026-06-14", "status": "APPROVED"},
            {"title": "번개 모임 식사", "amount": 62000, "category": "식비", "date": "2026-06-19", "status": "APPROVED"},
            {"title": "온라인 강의", "amount": 33000, "category": "교육", "date": "2026-06-21", "status": "APPROVED"},
            {"title": "프린트·제본", "amount": 12000, "category": "비품", "date": "2026-06-25", "status": "APPROVED"},
            {"title": "월말 회식", "amount": 96000, "category": "식비", "date": "2026-06-28", "status": "APPROVED"},
        ]
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


async def get_expense_detail(organization_id: str, expense_id: str) -> dict[str, Any]:
    """지출 상세 조회 — pull 모델의 핵심 (bravo 설계서 TABLE 18).

    백엔드 심사 요청에는 jobId·expenseId·organizationId·심사목표·영수증 경로만 오고
    제목·금액·카테고리는 없다 — 이 함수로 되물어 가져온다. 정확한 엔드포인트 경로는
    풀스택 질의요청서 회신 대기 중 — 확정되면 아래 URL만 교체.

    목 규약 (골든셋·대시보드와 공유 — §7 '규약을 깨지 말 것'):
      expense_id에 "?"가 있으면 query로 상세를 오버라이드 —
      "exp-1?title=교재&amount=32000&category=도서&date=2026-07-01&description=..."
      (in-memory 시딩은 api/worker가 별도 프로세스라 전달 불가 — ID에 인코딩하는
      방식만이 두 프로세스에서 동일하게 동작한다). 없는 키는 기본값.
    """
    s = get_settings()
    if s.mock_backend:
        detail = {"title": "모의 지출", "amount": 30_000, "category": "",
                  "date": "2026-07-01", "description": ""}
        if "?" in expense_id:
            params = parse_qs(urlsplit(expense_id).query)
            for key in ("title", "category", "date", "description"):
                if key in params:
                    detail[key] = params[key][0]
            if "amount" in params:
                detail["amount"] = int(params["amount"][0])
        return detail
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(
            f"/internal/agent/organizations/{organization_id}/expenses/{expense_id}")
        r.raise_for_status()
        return r.json()


async def get_team_settings(organization_id: str) -> dict[str, Any]:
    """team_settings 조회 — auto_approve 최상위 게이트용 (bravo 설계서 4절).

    실계약에서 auto_approve 기본값은 FALSE(꺼짐) — 꺼져 있으면 금액·판단과 무관하게
    무조건 ESCALATED. 값 자체는 백엔드 DB가 진실 원천이고 우리는 읽기만 한다.

    목 규약: organization_id에 "noauto" 포함 → auto_approve=False (게이트 검증용).
    그 외에는 True — 골든셋·데모의 자동판정 흐름을 보존하기 위한 목 전용 기본값이며
    실서비스 기본값(False)과 다르다는 점에 주의.
    """
    s = get_settings()
    if s.mock_backend:
        return {
            "auto_approve": "noauto" not in organization_id.lower(),
            "auto_approve_limit": 50_000,
            "escalation_threshold": 0.8,
        }
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(
            f"/internal/agent/organizations/{organization_id}/team-settings")
        r.raise_for_status()
        return r.json()


async def get_receipt_by_path(receipt_path: str) -> bytes | None:
    """영수증 이미지 조회 — 백엔드가 준 '조회 경로'로 Spring에 재요청 (동적 참조).

    signed URL 직접 fetch 방식이 아니라 Agent 전용 토큰으로 백엔드에 되묻는 방식
    (bravo 설계서 4절 'Agent 전용 토큰'). 목 모드에서는 None을 반환하고
    intake_receipt가 청구 일치 영수증을 생성한다(mock://receipt?... 오버라이드는
    intake 쪽 규약 그대로).
    TODO(실키 연결 후): 반환된 bytes를 Vision OCR(parse_receipt)에 전달.
    """
    s = get_settings()
    if s.mock_backend:
        return None
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(receipt_path)
        r.raise_for_status()
        return r.content


async def get_team_profile(team_id: str) -> dict[str, Any]:
    """팀 프로필(모임 유형 등) 조회 — 유형별 카테고리 카탈로그 선택에 사용.

    목 규약: team_id에 포함된 단서로 유형 추론 (club/study/social/hobby/company).
    실제 엔드포인트 경로는 풀스택 팀과 미확정.
    """
    s = get_settings()
    if s.mock_backend:
        tid = team_id.lower()
        for hint, team_type in [("club", "동아리/학생회"), ("study", "스터디"),
                                ("social", "친목"), ("hobby", "동호회"),
                                ("company", "회사"), ("corp", "회사")]:
            if hint in tid:
                return {"team_type": team_type}
        return {"team_type": "동아리/학생회"}  # 기본값
    async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
        r = await client.get(f"/internal/agent/teams/{team_id}/profile")
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
                    payload.get("verdict"), payload.get("expenseId"))
        return True
    try:
        async with httpx.AsyncClient(base_url=s.backend_base_url, headers=_headers()) as client:
            r = await client.post("/agent-callback", json=payload, timeout=10)
            r.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception("callback failed — 백엔드 폴링 fallback에 위임")
        return False
