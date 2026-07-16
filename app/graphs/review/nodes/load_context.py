"""load_context — pull 모델 컨텍스트 로드 (bravo 설계서 TABLE 18, §4.2). 읽기 전용.

백엔드 심사 요청에는 지출 상세가 없다 — 여기서 organizationId(state.team_id)+
expense_id로 백엔드에 되물어 ExpenseClaim을 구성한다. 단, 초기 상태에 claim이
이미 있으면(직접 그래프 호출 — smoke_review·seed_demo·단위테스트) 조회를 생략한다.

실패 정책 (§8 '어떤 실패도 자동 승인으로 이어지지 않는다'):
- 지출 상세 조회 실패 → 심사 불가이므로 예외를 그대로 던진다 — 워커 재시도,
  소진 시 fail-safe ESCALATED 콜백.
- team_settings 조회 실패 → auto_approve=False로 진행 (자동판정 권한이 확인되지
  않으면 판정하지 않는다 — 무조건 ESCALATED).
- 모임 유형·멤버 명단 실패 → 기본값으로 진행 (분류·마스킹 보조 정보일 뿐).
"""
import logging
import time

from app.graphs.review.state import ReviewState
from app.schemas.common import ExpenseClaim, PolicyParams
from app.tools.backend_client import (
    get_expense_detail, get_team_members, get_team_profile, get_team_settings,
)

logger = logging.getLogger(__name__)

DEFAULT_TEAM_TYPE = "동아리/학생회"


async def load_context(state: ReviewState) -> dict:
    updates: dict = {"started_at": time.time(), "rule_version": 1}

    # 1. 지출 상세 pull — 조회 실패는 심사 불가 (예외 전파 → 재시도/fail-safe)
    if state.get("claim") is None:
        detail = await get_expense_detail(state["team_id"], state["expense_id"])
        updates["claim"] = ExpenseClaim(
            title=detail.get("title", ""),
            amount=int(detail.get("amount", 0)),
            category=detail.get("category") or "",
            date=detail.get("date", ""),
            description=detail.get("description") or "",
        )

    # 2. team_settings — auto_approve 게이트 재료. 실패 시 False (fail-safe)
    try:
        ts = await get_team_settings(state["team_id"])
        defaults = PolicyParams()
        updates["policy_params"] = PolicyParams(
            auto_approve=bool(ts.get("auto_approve", False)),
            auto_approve_limit=int(ts.get("auto_approve_limit",
                                          defaults.auto_approve_limit)),
            confidence_threshold=float(ts.get("escalation_threshold",
                                              defaults.confidence_threshold)),
        )
    except Exception:
        logger.exception("get_team_settings failed — auto_approve=False로 fail-safe 진행")
        updates["policy_params"] = PolicyParams(auto_approve=False)

    # 3. 모임 유형 — classify_category의 카테고리 카탈로그 선택용 (fail-open)
    try:
        profile = await get_team_profile(state["team_id"])
        updates["team_type"] = profile.get("team_type") or DEFAULT_TEAM_TYPE
    except Exception:
        logger.exception("get_team_profile failed — 기본 유형으로 진행")
        updates["team_type"] = DEFAULT_TEAM_TYPE

    # 4. PII 마스킹용 멤버 명단 (B2, §4.3) — 실패해도 반드시 [] (심사를 막지 않음)
    try:
        updates["team_members"] = await get_team_members(state["team_id"])
    except Exception:
        logger.exception("get_team_members failed — 마스킹 없이 진행")
        updates["team_members"] = []

    return updates
