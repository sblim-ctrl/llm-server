"""load_context — 팀 정책 파라미터·회칙 버전·모임 유형 로드. 읽기 전용 (§4.2).

모임 유형은 classify_category가 유형별 카테고리 카탈로그를 고르는 데 사용한다.
조회 실패 시에도 심사를 막지 않는다 — 기본 유형으로 진행 (fail-open은 분류에만 해당,
판정 안전장치는 가드레일이 별도 보장).

TODO(계약 확정 후): 팀별 실제 정책 파라미터(auto_approve_limit 등)도 백엔드에서 조회.
"""
import logging

from app.graphs.review.state import ReviewState
from app.schemas.common import PolicyParams
from app.tools.backend_client import get_team_profile

logger = logging.getLogger(__name__)

DEFAULT_TEAM_TYPE = "동아리/학생회"


async def load_context(state: ReviewState) -> dict:
    try:
        profile = await get_team_profile(state["team_id"])
        team_type = profile.get("team_type") or DEFAULT_TEAM_TYPE
    except Exception:
        logger.exception("get_team_profile failed — 기본 유형으로 진행")
        team_type = DEFAULT_TEAM_TYPE

    return {
        "policy_params": PolicyParams(),
        "rule_version": 1,
        "team_type": team_type,
    }
