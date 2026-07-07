"""load_context — 팀 정책 파라미터·회칙 버전 로드. 읽기 전용, 부수효과 없음 (§4.2).

TODO(2주차): 백엔드/DB에서 팀별 실제 파라미터 조회. 지금은 기본값.
"""
from app.graphs.review.state import ReviewState
from app.schemas.common import PolicyParams


async def load_context(state: ReviewState) -> dict:
    return {
        "policy_params": PolicyParams(),
        "rule_version": 1,
    }
