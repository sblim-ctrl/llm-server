"""POST /v1/precedents — 관리자 결정 수신 계약 (REQ-042 학습 루프의 입구).

이 엔드포인트는 테스트가 하나도 없었다. 2026-08-12 백엔드가 push 연동을 붙이는
과정에서 요청 바디가 스키마와 어긋나 **매 요청이 422로 거절**됐고, 그래서 관리자
반려가 판례로 저장되지 않았다 — 실제로 겪은 두 불일치를 회귀로 고정한다:
  · `claim`에 dict가 아닌 제목 **문자열**만 보냄 → "valid dictionary or object"
  · `decision`을 백엔드 상태 ENUM(`approved`/`rejected`)로 보냄 (계약은 approve/reject)

저장 성공 경로는 `save_precedent`를 목킹해 라우터 계약만 본다(DB 불필요). 422/401은
미들웨어·Pydantic 단계에서 막혀 라우터 본체에 닿지 않으므로 목킹도 필요 없다.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import precedents as precedents_mod
from app.config import get_settings
from app.main import app

client = TestClient(
    app
)  # lifespan 없이 — 인증·검증은 라우팅 전에 끝난다(test_auth_middleware 관례)
AUTH = {"Authorization": f"Bearer {get_settings().service_token}"}


def _body(**over) -> dict:
    """정상 요청 바디(예시 계약). 개별 필드를 덮어써 불일치 케이스를 만든다."""
    body = {
        "team_id": 2,
        "expense_id": 39,
        "claim": {
            "title": "팀 회식비",
            "amount": 180_000,
            "category": "식비",
            "date": "2026-06-14",
            "description": "6월 팀 정기 회식",
        },
        "decision": "reject",
        "reason": "예산 한도 초과로 반려",
        "is_override": True,
        "rule_version": 3,
    }
    body.update(over)
    return body


# ── 저장 성공 경로 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_admin_decision_saved_as_admin_precedent(monkeypatch, decision):
    """정상 요청 → 201, 그리고 decided_by='ADMIN'·요청 필드가 그대로 save_precedent로 넘어간다.

    decided_by는 요청 값이 아니라 핸들러가 항상 'ADMIN'으로 못박는다(수신 계약).
    """
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "prec-1"

    monkeypatch.setattr(precedents_mod, "save_precedent", _capture)

    r = client.post("/v1/precedents", json=_body(decision=decision), headers=AUTH)

    assert r.status_code == 201
    assert r.json() == {"precedent_id": "prec-1"}
    assert captured["decided_by"] == "ADMIN"
    assert captured["decision"] == decision
    assert captured["team_id"] == 2
    assert captured["is_override"] is True
    assert captured["rule_version"] == 3
    # summarize_claim이 요약에 제목을 넣는다(저장·검색이 같은 포맷이어야 유사도가 성립)
    assert "팀 회식비" in captured["summary"]


# ── 백엔드가 실제로 보냈던 불일치(회귀 방지) ──────────────────────────────


def test_claim_as_string_is_rejected():
    """claim에 제목 문자열만 보내면 422 — 백엔드가 처음 겪은 바로 그 케이스."""
    r = client.post("/v1/precedents", json=_body(claim="팀 회식비"), headers=AUTH)
    assert r.status_code == 422


@pytest.mark.parametrize("bad_decision", ["approved", "rejected", "escalate"])
def test_backend_enum_decision_is_rejected(bad_decision):
    """decision은 approve/reject만 — 백엔드 상태 ENUM(approved/rejected)나 escalate는 422."""
    r = client.post("/v1/precedents", json=_body(decision=bad_decision), headers=AUTH)
    assert r.status_code == 422


# ── 스키마 경계 계약 ──────────────────────────────────────────────────────


def test_missing_required_claim_field_is_rejected():
    """claim.date는 필수 — 빠지면 422(놓치기 쉬운 필드)."""
    body = _body()
    del body["claim"]["date"]
    r = client.post("/v1/precedents", json=body, headers=AUTH)
    assert r.status_code == 422


def test_string_team_id_is_rejected():
    """team_id는 본문에서 strict 정수 — 문자열 "2"는 422(BigIntId 계약)."""
    r = client.post("/v1/precedents", json=_body(team_id="2"), headers=AUTH)
    assert r.status_code == 422


def test_requires_service_token():
    """수신 엔드포인트도 서비스 토큰이 필요하다 — 토큰 없으면 401."""
    r = client.post("/v1/precedents", json=_body())
    assert r.status_code == 401
