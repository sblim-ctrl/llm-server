"""문서 생성 에이전트 계약 — PolicyDrafter(/v1/policy-draft) · ReportWriter(/v1/reports/summary)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TeamType = Literal["동아리/학생회", "스터디", "친목", "동호회", "회사"]


# ── PolicyDrafter (REQ-036) ──────────────────────────────

class PolicyDraftRequest(BaseModel):
    """모임 생성 화면 입력 (실제 화면: 유형 5종 · 이름 · 초기예산 총액)."""
    team_type: TeamType
    team_name: str
    initial_budget: int = Field(gt=0, description="원 단위 총액")
    member_count: int | None = None
    description: str = ""


class PolicyParamsSuggestion(BaseModel):
    auto_approve_limit: int
    force_escalation_amount: int
    confidence_threshold: float = 0.8


class PolicyDraft(BaseModel):
    """[팀 결정 2026-07-09] 예산 카테고리 배분(budget_plan) 제거 —
    예산 현황은 지난 지출 내역 기반(ReportWriter)으로 표시."""
    rules: list[str]                     # 회칙 초안 (조항 단위 — 그대로 인덱싱 가능)
    policy_params: PolicyParamsSuggestion
    # 유형별 고정 카테고리 6개 (마법사 ①단계 "AI가 카테고리 추천" — 신규 생성 없음)
    recommended_categories: list[str] = []
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


# ── DigestWriter — AI 총무 주간 브리핑 (§4.4-c, A-4) ─────

class DigestRequest(BaseModel):
    """주간 윈도우는 요청이 지정 — 목 데이터가 6월 고정이라 '오늘 기준 최근 7일'은
    비결정적(A-4 명세). week_of가 속한 월~일이 브리핑 대상 주가 된다.
    (DigestFigures 등 결과 모델은 BurnForecast 순환 import 때문에
    app/graphs/writers/digest.py에 정의.)"""
    team_id: str
    week_of: str = Field(description="주간 윈도우 기준일 YYYY-MM-DD")

    @field_validator("week_of")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        # 실존 날짜 검증 — 잘못된 값은 API에서 422로 거절 (워커가 3회 재시도 끝에
        # dead가 되는 것 방지). B-3 period 형식 검증과 대칭.
        date.fromisoformat(v)
        return v


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
