"""문서 생성 에이전트 계약 — PolicyDrafter(/v1/policy-draft) · ReportWriter(/v1/reports/summary)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.ids import BigIntId

TeamType = Literal["동아리/학생회", "스터디", "친목", "동호회", "회사"]


# ── PolicyDrafter (REQ-036) ──────────────────────────────


class PolicyDraftRequest(BaseModel):
    """모임 생성 화면 + AI 마법사 1단계 입력
    (모임 생성: 유형 5종 · 이름 · 초기예산 총액 · 소개 / 마법사 1단계: 회비)."""

    team_type: TeamType
    team_name: str
    initial_budget: int = Field(gt=0, description="원 단위 총액")
    member_count: int | None = None
    description: str = ""
    # 마법사 1단계 '회비 금액'. 화면의 '없음' 체크는 None·0 둘 다 허용한다
    # (백엔드가 어느 쪽으로 보낼지 회신 대기 — 풀스택_회신요청.md 15번 ①).
    dues: int | None = Field(default=None, ge=0, description="1인당 회비. None·0 = 없음")


class PolicyParamsSuggestion(BaseModel):
    auto_approve_limit: int
    force_escalation_amount: int
    confidence_threshold: float = 0.8
    # 마법사 2단계 '당연히 모든 지출을 직접 확인할래요' 토글의 AI 추천 초기값
    # (화면_대조 §2-3 — 이 값을 내려줄 통로가 없어 AI가 토글을 추천하지 못하던 항목).
    #
    # true인 근거는 프로토타입 2단계 화면(9/38, 2026-07-31 확인)이다. 그 토글은 기본
    # **꺼짐**이고, 같은 화면 구간표의 '소액 지출 50,000원 미만 → AI 자동 승인'이 활성으로
    # 표시된다. 즉 화면의 기본 상태가 '자동 심사 사용'이므로 auto_approve=true가 화면과 맞는다.
    # (토글이 켜지면 auto_approve=false — 문구와 값이 반대 방향인 점에 주의.)
    #
    # 저장은 백엔드 team-settings 소관 — 우리는 추천만 한다(규율 3).
    auto_approve: bool = True


class PolicyDraft(BaseModel):
    """[팀 결정 2026-07-09] 예산 카테고리 배분(budget_plan) 제거 —
    예산 현황은 지난 지출 내역 기반(ReportWriter)으로 표시."""

    rules: list[str]  # 회칙 초안 (조항 단위 — 그대로 인덱싱 가능)
    policy_params: PolicyParamsSuggestion
    # 전역 고정 카테고리 9종 (마법사 ①단계 "AI가 카테고리 추천" — 신규 생성 없음)
    recommended_categories: list[str] = []
    notes: str = ""


class PolicyProposalRequest(PolicyDraftRequest):
    """회칙·정책 관리 화면의 초안 요청 (풀스택 협의 2026-08-04 7번).

    입력은 마법사 3단계와 같다 — 초안을 만드는 재료가 달라질 이유가 없다. 다른 것은
    결과를 `proposals`에 남긴다는 점과, 이미 있으면 재사용한다는 점이다.
    """

    team_id: BigIntId
    # true면 미결정 초안이 있어도 새로 만든다. 관리자가 '다시 생성'을 눌렀을 때만 쓴다 —
    # 기본이 재사용인 이유는 화면을 새로 고칠 때마다 회칙이 바뀌면 안 되기 때문이다
    # (LLM은 부를 때마다 다른 문장을 낸다).
    regenerate: bool = False

    def to_draft_request(self) -> "PolicyDraftRequest":
        return PolicyDraftRequest(
            team_type=self.team_type, team_name=self.team_name,
            initial_budget=self.initial_budget, member_count=self.member_count,
            description=self.description, dues=self.dues,
        )


class PolicyProposal(BaseModel):
    """저장된 회칙 초안. 승인·거절은 PATCH /v1/proposals/{proposalId}로 기록한다."""

    proposal_id: str
    team_id: BigIntId
    status: str          # proposed | accepted | dismissed
    draft: PolicyDraft
    # true면 새로 만들지 않고 저장돼 있던 초안을 돌려준 것이다. 화면에서 '방금 생성'과
    # '이전에 만든 것'을 구분해 보여주실 때 쓰시면 된다.
    reused: bool = False


# ── ReportWriter + 예산 추천 (REQ-019) ───────────────────


class ReportRequest(BaseModel):
    team_id: BigIntId
    period: str = Field(description="YYYY-MM")


class CategoryStat(BaseModel):
    category: str
    spent: int
    count: int
    share: float  # 전체 지출 대비 비중 0~1


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
    summary: str  # AI 요약 (수치는 figures에서만 인용)
    recommendations: list[str]  # 다음 예산 활용 추천
    verified: bool  # 수치 대조 통과 여부


# ── DigestWriter — AI 총무 주간 브리핑 (§4.4-c, A-4) ─────


class DigestRequest(BaseModel):
    """주간 윈도우는 요청이 지정 — 목 데이터가 6월 고정이라 '오늘 기준 최근 7일'은
    비결정적(A-4 명세). week_of가 속한 월~일이 브리핑 대상 주가 된다.
    (DigestFigures 등 결과 모델은 BurnForecast 순환 import 때문에
    app/graphs/writers/digest.py에 정의.)"""

    team_id: BigIntId
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
    team_id: BigIntId


class BriefingFigures(BaseModel):
    """판례 로그 결정적 집계 — 브리핑 텍스트의 수치는 이 값과 대조·일치해야 함."""

    total_precedents: int
    agent_decisions: int
    admin_decisions: int
    override_count: int  # AI 추천을 뒤집은 관리자 결정
    escalated_count: int
    gap_categories: list[str]  # 에스컬레이션이 잦은 카테고리 (회칙 보완 후보)


class BriefingDoc(BaseModel):
    figures: BriefingFigures
    summary: str
    handover_notes: list[str]  # 차기 관리자 인수인계 노트
    verified: bool
