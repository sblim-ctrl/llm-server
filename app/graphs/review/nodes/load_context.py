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

성능: 4개 조회는 상호 독립이라 asyncio.gather로 동시 실행 (심사 크리티컬 패스의
백엔드 왕복 4회 → 1회 분량). return_exceptions=True로 받아 위 실패 정책을 조회별로
그대로 적용한다 — 병렬화가 fail-safe 의미론을 바꾸지 않는다.
"""

import asyncio
import logging
import time

from app.graphs.review.state import ReviewState
from app.schemas.common import ExpenseClaim, PolicyParams
from app.tools.backend_client import (
    get_expense_detail,
    get_team_members,
    get_team_profile,
    get_team_settings,
)

logger = logging.getLogger(__name__)

DEFAULT_TEAM_TYPE = "동아리/학생회"


async def load_context(state: ReviewState) -> dict:
    updates: dict = {"started_at": time.time(), "rule_version": 1}
    team_id = state["team_id"]
    need_claim = state.get("claim") is None

    coros = [get_team_settings(team_id), get_team_profile(team_id), get_team_members(team_id)]
    if need_claim:
        coros.append(get_expense_detail(team_id, state["expense_id"]))
    results = await asyncio.gather(*coros, return_exceptions=True)
    settings_r, profile_r, members_r = results[:3]

    # 1. 지출 상세 pull — 조회 실패는 심사 불가 (예외 전파 → 재시도/fail-safe)
    if need_claim:
        detail = results[3]
        if isinstance(detail, BaseException):
            raise detail
        updates["claim"] = ExpenseClaim(
            title=detail.get("title", ""),
            amount=int(detail.get("amount", 0)),
            category=detail.get("category") or "",
            date=detail.get("date", ""),
            description=detail.get("description") or "",
        )

    # 2. team_settings — auto_approve 게이트 재료. 실패 시 False (fail-safe)
    if isinstance(settings_r, BaseException):
        logger.error(
            "get_team_settings failed — auto_approve=False로 fail-safe 진행", exc_info=settings_r
        )
        updates["policy_params"] = PolicyParams(auto_approve=False)
    else:
        defaults = PolicyParams()
        # escalation_threshold는 금액이다 — "이 금액 초과 시 무조건 관리자 검토"
        # (풀스택 DB 스키마 team_settings, 2026-07-27 수령분에서 확정 / Q4①).
        # confidence_threshold(θ)는 백엔드가 모르는 LLM 내부 파라미터라 분리 유지(Q4④).
        # auto_approve_limit은 NULL 허용 — 자동승인 미사용 팀(실서비스 기본)은 값이 없다.
        # None이면 0으로 둔다: 한도 0이면 모든 금액이 걸려 에스컬레이션되므로 §8
        # "어떤 실패도 자동 승인으로 이어지지 않는다"에 부합하는 안전 방향이다.
        limit = settings_r.get("auto_approve_limit")
        force = settings_r.get("escalation_threshold")
        updates["policy_params"] = PolicyParams(
            auto_approve=bool(settings_r.get("auto_approve", False)),
            auto_approve_limit=int(limit) if limit is not None else 0,
            force_escalation_amount=(
                int(force) if force is not None else defaults.force_escalation_amount
            ),
        )

    # 3. 모임 유형 — classify_category의 카테고리 카탈로그 선택용 (fail-open)
    if isinstance(profile_r, BaseException):
        logger.error("get_team_profile failed — 기본 유형으로 진행", exc_info=profile_r)
        updates["team_type"] = DEFAULT_TEAM_TYPE
    else:
        updates["team_type"] = profile_r.get("team_type") or DEFAULT_TEAM_TYPE

    # 4. PII 마스킹용 멤버 명단 (B2, §4.3) — 실패해도 반드시 [] (심사를 막지 않음)
    if isinstance(members_r, BaseException):
        logger.error("get_team_members failed — 마스킹 없이 진행", exc_info=members_r)
        updates["team_members"] = []
    else:
        updates["team_members"] = members_r

    return updates
