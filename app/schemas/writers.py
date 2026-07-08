"""문서 생성 에이전트 계약 — PolicyDrafter(/v1/policy-draft) · ReportWriter(/v1/reports/summary)."""
from typing import Literal

from pydantic import BaseModel, Field

TeamType = Literal["동아리/학생회", "스터디", "친목", "동호회", "회사"]


# ── PolicyDrafter (REQ-036) ──────────────────────────────

class PolicyDraftRequest(BaseModel):
    """모임 생성 화면 입력 (실제 화면: 유형 5종 · 이름 · 초기예산 총액)."""
    team_type: TeamType
    team_name: str
    initial_budget: int = Field(gt=0, description="원 단위 총액")
    member_count: int | None = None
    description: str = ""


class BudgetLine(BaseModel):
    category: str
    amount: int
    ratio: float


class PolicyParamsSuggestion(BaseModel):
    auto_approve_limit: int
    force_escalation_amount: int
    confidence_threshold: float = 0.8


class PolicyDraft(BaseModel):
    rules: list[str]                     # 회칙 초안 (조항 단위 — 그대로 인덱싱 가능)
    budget_plan: list[BudgetLine]        # 합계 == initial_budget (검증 노드가 보장)
    policy_params: PolicyParamsSuggestion
    notes: str = ""


# ── ReportWriter + 예산 추천 (REQ-019) ───────────────────

class ReportRequest(BaseModel):
    team_id: str
    period: str = Field(description="YYYY-MM")


class CategoryStat(BaseModel):
    category: str
    spent: int
    count: int
    share: float                         # 전체 지출 대비 비중 0~1


class ReportFigures(BaseModel):
    """결정적 집계 결과 — 생성 텍스트의 수치는 반드시 이 값과 대조·일치해야 함."""
    period: str
    total_spent: int
    expense_count: int
    by_category: list[CategoryStat]
    top_expense_title: str
    top_expense_amount: int


class BudgetReport(BaseModel):
    figures: ReportFigures
    summary: str                         # AI 요약 (수치는 figures에서만 인용)
    recommendations: list[str]           # 다음 예산 활용 추천
    verified: bool                       # 수치 대조 통과 여부


# ── BriefingWriter — 인수인계 브리핑 (REQ-043) ───────────

class BriefingRequest(BaseModel):
    team_id: str


class BriefingFigures(BaseModel):
    """판례 로그 결정적 집계 — 브리핑 텍스트의 수치는 이 값과 대조·일치해야 함."""
    total_precedents: int
    agent_decisions: int
    admin_decisions: int
    override_count: int                  # AI 추천을 뒤집은 관리자 결정
    escalated_count: int
    gap_categories: list[str]            # 에스컬레이션이 잦은 카테고리 (회칙 보완 후보)


class BriefingDoc(BaseModel):
    figures: BriefingFigures
    summary: str
    handover_notes: list[str]            # 차기 관리자 인수인계 노트
    verified: bool
