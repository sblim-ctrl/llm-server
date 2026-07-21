"""LLM-as-Judge — 심사 사유(reason) 품질 채점 (§4 Sprint 2).

verdict 정확도는 골든셋이 채점하지만 요청자용/관리자용 사유는 자유 텍스트라 정답이
없다. 판단 LLM과 분리된 gpt-4o-mini judge가 §3.3 사유 요건을 rubric으로 채점한다.
심사 그래프에는 관여하지 않는 평가 전용 도구 — eval 하니스가 판정 후 호출한다.
"""
import json
import re

from pydantic import BaseModel, Field

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.common import LLMCallMeta

PASS_THRESHOLD = 0.7


class JudgeResult(BaseModel):
    """사유 품질 채점 결과 (judge/v1.yaml rubric)."""
    requester_polite: bool                 # 요청자용: 정중·건설적
    requester_leaks_internal: bool         # 요청자용: 내부 수치·판례 노출(위반=True)
    admin_has_grounds: bool                # 관리자용: 조항·수치·판례 근거 포함
    overall_score: float = Field(ge=0.0, le=1.0)
    notes: str = ""


def passes(r: JudgeResult) -> bool:
    """머지·게이트용 종합 판정 — 요건 3개 + 임계 점수."""
    return (r.requester_polite
            and not r.requester_leaks_internal
            and r.admin_has_grounds
            and r.overall_score >= PASS_THRESHOLD)


# 구체 금액만 매칭 — "1,000원"·"5만원"은 위반, "예산 잔액이 부족하여"는 정상.
# judge 캘리브레이션(2026-07-21): '잔액'·'부족' 같은 정성 표현은 내부 노출이 아니다.
_MONEY_RE = re.compile(r"\d[\d,]*\s*원|\d+\s*만\s*원")


def _mock_judge(reason_requester: str, reason_admin: str) -> JudgeResult:
    """목 모드 결정적 채점 — 실 judge 없이 하니스·테스트가 돌도록.
    요청자용에 구체 금액이나 '판례'가 있으면 내부 노출; 관리자용에 숫자가 있으면 근거."""
    leaks = bool(_MONEY_RE.search(reason_requester)) or ("판례" in reason_requester)
    grounded = any(ch.isdigit() for ch in reason_admin) or ("조" in reason_admin)
    score = 0.9 if (not leaks and grounded) else 0.4
    return JudgeResult(
        requester_polite=True, requester_leaks_internal=leaks,
        admin_has_grounds=grounded, overall_score=score,
        notes="(mock) 표지 기반 채점")


async def judge_reasons(verdict: str, reason_requester: str,
                        reason_admin: str) -> tuple[JudgeResult, LLMCallMeta]:
    """사유 2종을 judge에 넘겨 품질 채점. 목 모드면 결정적 mock."""
    spec = load_prompt("judge")
    payload = json.dumps({"verdict": verdict,
                          "reason_requester": reason_requester,
                          "reason_admin": reason_admin}, ensure_ascii=False)
    return await chat_structured(
        agent="judge",
        system=spec.system_with_few_shot(),
        user=payload,
        schema=JudgeResult,
        mock_response=_mock_judge(reason_requester, reason_admin),
        prompt_version=spec.version,
    )
