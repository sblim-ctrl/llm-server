"""문서 생성 에이전트 계약 — PolicyDrafter(/v1/policy-draft) · ReportWriter(/v1/reports/summary)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ids import BigIntId

TeamType = Literal["동아리/학생회", "스터디", "친목", "동호회", "회사"]

# 마법사 3단계에서 무엇을 골랐는지 (file=파일 업로드 · manual=직접 입력 · ai=AI 초안 ·
# skip=건너뛰기). 응답 rules는 ai일 때만 채워진다 — API 명세서 개정안 §1-2.
RuleSource = Literal["file", "manual", "ai", "skip"]


# ── PolicyDrafter (REQ-036 · LLM-005 전면 개정 2026-08-05) ─


class PolicyDraftRequest(BaseModel):
    """마법사 1~3단계 통합 요청 (API 명세서 개정안 §1 — 회의 2·3·5번).

    0단계(모임 생성)는 백엔드 별도 API — 여기는 그 결과인 team_id를 받는다.
    1단계 회비(dues) · 2단계 기준 금액(force_escalation_amount) · 3단계 회칙
    (rule_source·rule_text·rule_file_ref)을 한 번에 담는다.
    """

    team_id: BigIntId  # 0단계 모임 생성 응답의 teamId
    team_type: TeamType
    team_name: str
    initial_budget: int = Field(gt=0, description="원 단위 총액")
    member_count: int | None = None
    description: str = ""
    # 마법사 1단계 '회비 금액'. 화면의 '없음' 체크는 None·0 둘 다 허용한다
    # (백엔드가 어느 쪽으로 보낼지 회신 대기 — 풀스택_회신요청.md 15번 ①).
    dues: int | None = Field(default=None, ge=0, description="1인당 회비. None·0 = 없음")
    # 마법사 2단계 '관리자 확인 설정 금액' — 이 값 하나로 승인 정책이 결정된다
    # (미만=AI 자동 승인 가능, 이상=관리자 결정). LLM은 승인 정책을 제안하지 않는다.
    # 화면 최소 5만원 하한은 여기서 걸지 않는다 — 개정안 §1-2가 요구하는 것은
    # '정수·필수'뿐이라 그 하한까지 서버가 계약에 없이 선제로 강제하지는 않는다.
    # gt=0은 그와 별개로 initial_budget과 같은 최소한의 정합성 검사다(음수·0은
    # '기준 금액'이라는 의미 자체가 성립하지 않는다).
    force_escalation_amount: int = Field(gt=0, description="원 단위 기준 금액")
    rule_source: RuleSource
    # 아래 둘은 여기서 검증만 한다 — 회칙 본문 저장은 백엔드, 심사 반영은 LLM-006 경로.
    rule_text: str | None = None  # manual일 때 필수 — 직접 입력한 회칙 원문
    rule_file_ref: str | None = None  # file일 때 필수 — BE-005로 되물을 참조 키

    @model_validator(mode="after")
    def _rule_payload_present(self) -> "PolicyDraftRequest":
        # 반대 방향(예: ai인데 rule_text가 옴)은 거절하지 않고 무시한다 — FE 관용.
        if self.rule_source == "manual" and not (self.rule_text or "").strip():
            raise ValueError("rule_source=manual이면 rule_text가 필요합니다")
        if self.rule_source == "file" and not (self.rule_file_ref or "").strip():
            raise ValueError("rule_source=file이면 rule_file_ref가 필요합니다")
        return self


class PolicyDraft(BaseModel):
    """[팀 결정 2026-07-09] 예산 카테고리 배분(budget_plan) 제거 —
    예산 현황은 지난 지출 내역 기반(ReportWriter)으로 표시.

    [개정 2026-08-05] policy_params(승인 정책 제안) 제거 — 기준 금액은 사용자 입력이
    원천이라 LLM이 되돌려 줄 값이 없다 (API 명세서 개정안 §1-4)."""

    rules: list[str]  # 회칙 초안 (조항 단위) — rule_source=ai일 때만 채움, 그 외 빈 배열
    # 전역 고정 카테고리 9종 (마법사 ①단계 "AI가 카테고리 추천" — 신규 생성 없음)
    recommended_categories: list[str] = []
    notes: str = ""


class PolicyProposalRequest(PolicyDraftRequest):
    """회칙·정책 관리 화면의 초안 요청 (풀스택 협의 2026-08-04 7번).

    입력은 마법사 3단계와 같다 — 초안을 만드는 재료가 달라질 이유가 없다. 다른 것은
    결과를 `proposals`에 남긴다는 점과, 이미 있으면 재사용한다는 점이다.
    """

    # 관리 화면의 목적 자체가 'AI 초안 생성'이라 ai로 고정한다 — 다른 값을 열어두면
    # 빈 초안이 proposals에 저장되는 조합이 생긴다. 백엔드는 이 필드를 생략해도 된다.
    rule_source: Literal["ai"] = "ai"
    # true면 미결정 초안이 있어도 새로 만든다. 관리자가 '다시 생성'을 눌렀을 때만 쓴다 —
    # 기본이 재사용인 이유는 화면을 새로 고칠 때마다 회칙이 바뀌면 안 되기 때문이다
    # (LLM은 부를 때마다 다른 문장을 낸다).
    regenerate: bool = False

    def to_draft_request(self) -> "PolicyDraftRequest":
        # 필드를 하나씩 옮기지 않는다 — PolicyDraftRequest에 필드가 늘 때 여기서
        # 조용히 빠지는 사고를 막기 위해 덤프 전체를 넘긴다 (regenerate만 제외).
        return PolicyDraftRequest.model_validate(self.model_dump(exclude={"regenerate"}))


class PolicyProposal(BaseModel):
    """저장된 회칙 초안. 승인·거절은 PATCH /v1/proposals/{proposalId}로 기록한다."""

    proposal_id: str
    team_id: BigIntId
    status: str  # proposed | accepted | dismissed
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
