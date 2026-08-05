"""대시보드 AI 요약 계약 — POST /v1/dashboard/summary (풀스택 협의 2026-08-04 5번).

정산 리포트의 AI 요약은 MVP에서 빠지고(회의록 9번) 대시보드로 자리를 옮긴다.
리포트가 '기간 정산'이라면 대시보드는 '지금 상태'라서, 같은 문장을 재활용하지 않고
현재 시점 지표로 다시 쓴다.
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ids import BigIntId


class DashboardSummaryRequest(BaseModel):
    team_id: BigIntId
    # 미지정 시 당월. 대외 명세(LLM-017)가 '선택, 미지정 시 당월'로 나갔는데 코드는
    # 필수여서, 명세대로 period 없이 호출하면 422가 나던 것을 맞췄다 (2026-08-05).
    #
    # 원래 필수였던 이유는 결정성이다 — 목 데이터가 특정 월 고정이라 '오늘'을 쓰면
    # 실행 시점에 따라 결과가 달라진다. 그래서 **채우는 것은 요청이 생략했을 때뿐**이고,
    # 테스트·골든셋·스모크는 계속 period를 명시한다(결정성 유지).
    period: str | None = Field(default=None, description="대상 월 YYYY-MM (미지정 시 당월)")

    @field_validator("period")
    @classmethod
    def _check_period(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parts = v.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValueError("period는 YYYY-MM 형식이어야 합니다")
        if not (parts[0].isdigit() and parts[1].isdigit() and 1 <= int(parts[1]) <= 12):
            raise ValueError("period의 연·월이 올바르지 않습니다")
        return v

    @model_validator(mode="after")
    def _default_to_current_month(self) -> "DashboardSummaryRequest":
        """생략됐을 때만 당월로 채운다 — 이후 코드는 period가 항상 있다고 보면 된다.

        여기서 채우는 이유는 소비처(`dashboard.py`의 집계·문장 생성)가 두 군데인데,
        각자 None을 처리하면 기본값이 갈라질 수 있어서다. 경계에서 한 번만 정한다.
        """
        if self.period is None:
            today = date.today()
            object.__setattr__(self, "period", f"{today.year}-{today.month:02d}")
        return self


class CategoryTrend(BaseModel):
    """카테고리 하나의 이번 달 지출과 전월 대비 변화."""

    category: str
    spent: int
    share: float                 # 이번 달 전체 지출 대비 비중 0~1
    prev_spent: int              # 전월 지출
    change_ratio: float | None   # (이번 달 − 전월) / 전월. 전월이 0이면 null


class DashboardFigures(BaseModel):
    """결정적 집계 — 요약문의 수치는 반드시 이 값과 일치해야 한다.

    LLM은 문장만 쓰고 숫자는 전부 여기서 나온다. 검증기(verify_summary_pure)가
    본문의 금액 토큰을 이 값에서 유도한 허용 목록과 대조한다.
    """

    period: str
    total_budget: int
    spent: int                   # 승인된 지출 합계
    remaining: int               # total_budget − spent
    usage_ratio: float           # spent / total_budget (예산 0이면 0.0)
    pending_count: int           # 승인 대기 건수
    pending_amount: int          # 승인 대기 금액 합계
    categories: list[CategoryTrend]        # 이번 달 지출 상위 순
    top_category: CategoryTrend | None     # 비중 1위 (지출 없으면 null)
    fastest_growing: CategoryTrend | None  # 전월 대비 증가율 1위 (증가가 없으면 null)
    largest_expense_title: str | None      # 단일 최대 지출
    largest_expense_amount: int


class DashboardSummary(BaseModel):
    """LLM 산출물 — 문장만. 수치는 figures에서 온 것만 쓴다."""

    message: str                 # 화면에 그대로 띄우는 2~4문장


class DashboardSummaryDoc(BaseModel):
    figures: DashboardFigures
    message: str
    # 검증 실패 시 false. 화면은 이 값이 false면 요약을 감추거나 '확인 필요'로 표시한다.
    verified: bool
