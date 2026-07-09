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
from typing_extensions import TypedDict

from app.schemas.writers import PolicyDraft, PolicyDraftRequest, PolicyParamsSuggestion

logger = logging.getLogger(__name__)

_TEMPLATES_PATH = Path(__file__).resolve().parents[3] / "templates" / "policy_templates.yaml"
PER_MEAL_LIMIT = 30_000  # 1인당 식비 기본 한도 — 추후 팀 규모 기반 조정


@lru_cache
def load_templates() -> dict:
    import yaml
    return yaml.safe_load(_TEMPLATES_PATH.read_text(encoding="utf-8"))


class DraftState(TypedDict, total=False):
    request: PolicyDraftRequest
    template: dict
    draft: PolicyDraft
    verified: bool
    verify_error: str | None


async def load_template(state: DraftState) -> dict:
    req = state["request"]
    template = load_templates()[req.team_type]
    return {"template": template}


async def generate_draft(state: DraftState) -> dict:
    """초안 조립. 한도 수치는 코드 계산, 조항 문구는 템플릿 + 치환.

    TODO(실키 연결 후): description·member_count를 반영해 gpt-4o가 조항을
    팀 맞춤으로 다듬는 단계 추가 (수치 placeholder는 코드 값 유지).
    """
    req, template = state["request"], state["template"]

    auto_limit = max(10_000, (int(req.initial_budget * template["auto_approve_ratio"])
                              // 10000) * 10000)
    params = PolicyParamsSuggestion(
        auto_approve_limit=auto_limit,
        force_escalation_amount=auto_limit * 6,
    )
    rules = [r.format(auto_approve_limit=f"{params.auto_approve_limit:,}",
                      per_meal_limit=f"{PER_MEAL_LIMIT:,}")
             for r in template["base_rules"]]

    draft = PolicyDraft(
        rules=rules, policy_params=params,
        notes=f"'{req.team_name}' ({req.team_type}) 초기예산 {req.initial_budget:,}원 기준 자동 생성 초안 — 관리자 검토 후 확정",
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
    g.add_node("generate_draft", generate_draft)
    g.add_node("verify_draft", verify_draft)
    g.add_edge(START, "load_template")
    g.add_edge("load_template", "generate_draft")
    g.add_edge("generate_draft", "verify_draft")
    g.add_edge("verify_draft", END)
    return g.compile()


policy_draft_graph = build_policy_draft_graph()
