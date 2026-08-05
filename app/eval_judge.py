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
    """사유 품질 채점 결과 (judge rubric)."""
    requester_polite: bool                 # 요청자용: 정중·건설적
    requester_leaks_internal: bool         # 요청자용: 내부 수치·판례 노출(위반=True)
    admin_has_grounds: bool                # 관리자용: 조항·수치·판례 근거 포함
    # 관리자용: 인용한 수치가 소견에 실재하는가(환각 아닌가). judge/v3 신설 —
    # 소견 미제공 시 대조 불가라 기본 True(무죄추정). v1·v2 프롬프트는 이 필드를
    # 채점하지 않으므로 기본값이 게이트에 영향을 주지 않는다.
    admin_grounds_faithful: bool = True
    overall_score: float = Field(ge=0.0, le=1.0)
    notes: str = ""


def passes(r: JudgeResult) -> bool:
    """머지·게이트용 종합 판정 — 요건 4개 + 임계 점수."""
    return (r.requester_polite
            and not r.requester_leaks_internal
            and r.admin_has_grounds
            and r.admin_grounds_faithful
            and r.overall_score >= PASS_THRESHOLD)


# 구체 금액만 매칭 — "1,000원"·"5만원"은 위반, "예산 잔액이 부족하여"는 정상.
# judge 캘리브레이션(2026-07-21): '잔액'·'부족' 같은 정성 표현은 내부 노출이 아니다.
_MONEY_RE = re.compile(r"\d[\d,]*\s*원|\d+\s*만\s*원")
_NUM_RE = re.compile(r"\d[\d,]*")


def _digits(token: str) -> str:
    """수치 토큰을 자릿수만 남겨 정규화 — '182,000원'과 정수 182000을 동일 비교."""
    return re.sub(r"[^\d]", "", token)


def _opinion_numbers(opinions: dict | None) -> set[str]:
    """심사관 소견(summary·figures)에 실재하는 수치를 자릿수 집합으로 추출."""
    if not opinions:
        return set()
    parts: list[str] = []
    for op in opinions.values():
        parts.append(getattr(op, "summary", "") or "")
        for value in (getattr(op, "figures", {}) or {}).values():
            parts.append(str(value))
    return {_digits(tok) for tok in _NUM_RE.findall(" ".join(parts))} - {""}


def _mock_judge(reason_requester: str, reason_admin: str,
                opinions: dict | None = None) -> JudgeResult:
    """목 모드 결정적 채점 — 실 judge 없이 하니스·테스트가 돌도록.
    요청자용에 구체 금액이나 '판례'가 있으면 내부 노출; 관리자용에 숫자가 있으면 근거.
    소견이 주어지면 관리자용 인용 수치가 소견에 실재하는지(faithful) 대조한다."""
    leaks = bool(_MONEY_RE.search(reason_requester)) or ("판례" in reason_requester)
    grounded = any(ch.isdigit() for ch in reason_admin) or ("조" in reason_admin)
    # 관리자용이 인용한 금액이 전부 소견에 실재하면 faithful. 소견 미제공 또는
    # 인용 수치 없음(정성 표현만) → 대조 불가라 무죄추정(True).
    cited = {_digits(tok) for tok in _MONEY_RE.findall(reason_admin)} - {""}
    faithful = (not cited) or (not opinions) or cited.issubset(_opinion_numbers(opinions))
    score = 0.9 if (not leaks and grounded and faithful) else 0.4
    return JudgeResult(
        requester_polite=True, requester_leaks_internal=leaks,
        admin_has_grounds=grounded, admin_grounds_faithful=faithful,
        overall_score=score, notes="(mock) 표지 기반 채점")


async def judge_reasons(verdict: str, reason_requester: str, reason_admin: str,
                        opinions: dict | None = None) -> tuple[JudgeResult, LLMCallMeta]:
    """사유 2종을 judge에 넘겨 품질 채점. 목 모드면 결정적 mock.

    opinions(심사관 소견 dict)가 주어지면 judge가 관리자 사유의 인용 수치가
    실재하는지(환각 여부)까지 대조한다 — judge/v3. 미제공 시 기존 동작(호환).
    """
    spec = load_prompt("judge")
    doc: dict = {"verdict": verdict,
                 "reason_requester": reason_requester,
                 "reason_admin": reason_admin}
    if opinions:
        doc["auditor_opinions"] = [
            {"auditor": op.auditor, "verdict": op.verdict, "summary": op.summary,
             "evidence": op.evidence, "figures": op.figures,
             "similar_cases": op.similar_cases}
            for op in opinions.values()
        ]
    return await chat_structured(
        agent="judge",
        system=spec.system_with_few_shot(),
        user=json.dumps(doc, ensure_ascii=False),
        schema=JudgeResult,
        mock_response=_mock_judge(reason_requester, reason_admin, opinions),
        prompt_version=spec.version,
    )
