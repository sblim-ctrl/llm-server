"""PolicyDrafter — 마법사 'AI 초안' 경로 (REQ-036, §4.4-c).

[팀 결정 2026-07-09] AI가 카테고리별 예산을 배분하는 기능은 제거 —
회칙 초안 + 에이전트 정책 파라미터(자동승인 한도 등) 제안만 생성한다.
예산 현황은 지난 지출 내역 기반으로 표시(ReportWriter 담당).

패턴: 템플릿 로드 → 생성 → 검증(Generator-Evaluator, 강의 12-03).
한도 수치는 코드가 계산하고, LLM은 문구 다듬기만 담당한다.

동기 실행: 마법사 UX상 즉시 응답이 필요해 llm-api가 직접 이 그래프를 호출한다
(§2.2 'LLM 호출은 워커만' 원칙의 예외 — §7.2가 동기로 명시. 지연 문제 생기면 잡 전환).
"""

import logging
from functools import lru_cache
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.writers import PolicyDraft, PolicyDraftRequest, PolicyParamsSuggestion
from app.tools.category_catalog import categories_for
from app.tools.search_references import search_references

logger = logging.getLogger(__name__)

# 추가 조항 상한 — 천장이지 목표가 아니다(프롬프트가 "빠짐없이, 단 중복·일반론 금지"로
# 실제 개수를 조절). base_rules 4~5개와 합쳐 총 10~12개 = 모바일 카드 한 장 분량.
# v1 프롬프트는 본문에 "0~3개"로 적혀 있어 실질 동작 불변, v2가 0~7개를 사용한다.
MAX_EXTRA_RULES = 7


class ExtraRules(BaseModel):
    extra_rules: list[str] = []


_TEMPLATES_PATH = Path(__file__).resolve().parents[3] / "templates" / "policy_templates.yaml"
PER_MEAL_LIMIT = 30_000  # 1인당 식비 기본 한도 — 추후 팀 규모 기반 조정
# 강제 에스컬레이션 = 자동승인 한도 × 이 배수. 마법사 2단계 화면의 구간표
# (소액 5만 미만 / 중간 5~20만 / 고액 20만 이상)에 맞춘 값 — 5만 × 4 = 20만.
FORCE_ESCALATION_MULTIPLE = 4
# 회비가 입력된 경우에만 붙는 조항 (유형 무관이라 템플릿이 아닌 코드 상수).
DUES_RULE = "회비는 1인당 {dues}원으로 하며, 회비 수입 범위 내에서 지출을 집행한다."


@lru_cache
def load_templates() -> dict:
    import yaml

    return yaml.safe_load(_TEMPLATES_PATH.read_text(encoding="utf-8"))


class DraftState(TypedDict, total=False):
    request: PolicyDraftRequest
    template: dict
    references: list[dict]
    draft: PolicyDraft
    verified: bool
    verify_error: str | None


async def load_template(state: DraftState) -> dict:
    req = state["request"]
    template = load_templates()[req.team_type]
    return {"template": template}


async def retrieve_references(state: DraftState) -> dict:
    """참고 규정 문서 검색 (RAG) — 생성 전 근거 자료 확보.

    검색 실패는 생성 자체를 막지 않는다 — 참고자료 없이도 기본 템플릿으로
    진행 가능하므로 fail-open. (강의 08 Agentic RAG 패턴)
    """
    req = state["request"]
    query = f"{req.team_type} {req.description}".strip()
    try:
        refs = await search_references(query)
    except Exception:
        logger.exception("search_references failed — 참고자료 없이 진행")
        refs = []
    return {"references": refs}


def _mock_extra_rules(description: str) -> list[str]:
    """목 모드 휴리스틱 — 소개 문구 키워드 기반 추가 조항 제안. 소개 없으면 빈 목록."""
    if not description:
        return []
    text = description.lower()
    rules: list[str] = []
    if any(k in text for k in ("등산", "캠핑", "액티비티", "레저", "운동")):
        rules.append(
            "야외·활동성 행사에 필요한 안전장비(구급용품 등) 구입은 활동 안전을 위한 지출로 우선 인정한다."
        )
    if any(k in text for k in ("스터디", "개발", "코딩", "프로젝트", "실습")):
        rules.append(
            "실습에 필요한 서버·도메인·구독형 개발 도구 비용은 스터디 기간 내 결제분만 인정한다."
        )
    if any(k in text for k in ("신입", "모집", "홍보", "리크루팅")):
        rules.append("신입 모집 관련 홍보물 제작비는 모집 기간 내 집행 건에 한해 인정한다.")
    return rules[:MAX_EXTRA_RULES]


async def generate_draft(state: DraftState) -> dict:
    """초안 조립. 한도 수치는 코드 계산, 기본 조항은 템플릿 + 치환.

    모임 소개가 있으면 LLM이 그 모임 특성에 맞는 추가 조항(최대 MAX_EXTRA_RULES개)을
    제안한다. 소개가 없으면 LLM을 호출하지 않아 기본 조항만 남는다.
    기본 조항은 LLM이 절대 건드리지 않음 — 필수 조항 보장은 코드 검증(verify_draft)의
    책임으로 유지하기 위해서다.
    """
    req, template = state["request"], state["template"]

    auto_limit = max(
        10_000, (int(req.initial_budget * template["auto_approve_ratio"]) // 10000) * 10000
    )
    params = PolicyParamsSuggestion(
        auto_approve_limit=auto_limit,
        force_escalation_amount=auto_limit * FORCE_ESCALATION_MULTIPLE,
    )
    base_rules = [
        r.format(
            auto_approve_limit=f"{params.auto_approve_limit:,}",
            per_meal_limit=f"{PER_MEAL_LIMIT:,}",
        )
        for r in template["base_rules"]
    ]
    # 마법사 1단계 회비 — 입력됐을 때만 조항 1개 추가 ('없음'은 None·0 둘 다)
    if req.dues:
        base_rules.append(DUES_RULE.format(dues=f"{req.dues:,}"))

    extra_rules: list[str] = []
    if req.description:
        refs = state.get("references") or []
        ref_text = "\n".join(f"- {r['text']}" for r in refs) or "(참고자료 없음)"
        try:
            spec = load_prompt("policy_drafter")
            result, _meta = await chat_structured(
                agent="policy_drafter",
                system=spec.system_with_few_shot(),
                user=f"모임 유형: {req.team_type}\n모임 이름: {req.team_name}\n"
                f"모임 소개: {req.description}\n\n"
                f"참고 규정(다른 모임 사례 — 그대로 베끼지 말고 참고만):\n{ref_text}",
                schema=ExtraRules,
                mock_response=ExtraRules(extra_rules=_mock_extra_rules(req.description)),
                prompt_version=spec.version,
            )
            extra_rules = result.extra_rules[:MAX_EXTRA_RULES]
        except Exception:
            logger.exception("policy_drafter 추가 조항 생성 실패 — 기본 조항만 사용")

    dues_note = f" · 회비 {req.dues:,}원" if req.dues else ""
    draft = PolicyDraft(
        rules=base_rules + extra_rules,
        policy_params=params,
        recommended_categories=categories_for(req.team_type),  # 유형별 고정 6개 (신규 생성 없음)
        notes=f"'{req.team_name}' ({req.team_type}) 초기예산 {req.initial_budget:,}원{dues_note}"
        " 기준 자동 생성 초안 — 관리자 검토 후 확정",
    )
    return {"draft": draft}


def verify_draft_pure(draft: PolicyDraft) -> str | None:
    """검증(Evaluator) — 위반 시 사유 반환, 통과 시 None. 순수 함수 (단위 테스트 대상)."""
    p = draft.policy_params
    if not (0 < p.auto_approve_limit < p.force_escalation_amount):
        return "한도 순서 오류 (auto_approve_limit < force_escalation_amount 여야 함)"
    if not draft.rules:
        return "조항 없음"
    if any("{" in r for r in draft.rules):
        return "치환되지 않은 placeholder 존재"
    return None


async def verify_draft(state: DraftState) -> dict:
    error = verify_draft_pure(state["draft"])
    if error:
        logger.error("policy draft verification failed: %s", error)
    return {"verified": error is None, "verify_error": error}


def build_policy_draft_graph():
    g = StateGraph(DraftState)
    g.add_node("load_template", load_template)
    g.add_node("retrieve_references", retrieve_references)
    g.add_node("generate_draft", generate_draft)
    g.add_node("verify_draft", verify_draft)
    g.add_edge(START, "load_template")
    g.add_edge("load_template", "retrieve_references")
    g.add_edge("retrieve_references", "generate_draft")
    g.add_edge("generate_draft", "verify_draft")
    g.add_edge("verify_draft", END)
    return g.compile()


policy_draft_graph = build_policy_draft_graph()
