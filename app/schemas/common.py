"""도메인 공통 스키마 — ReviewState를 구성하는 값 객체들 (§4.2)."""
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["approve", "reject", "escalate"]
AuditorVerdict = Literal["pass", "warn", "fail", "error"]


class ExpenseClaim(BaseModel):
    """지출 청구 내용 (백엔드가 /v1/analyze 페이로드로 전달).

    category는 선택 — 비어 있으면 classify_category 노드가 AI 분류로 채운다 (팀 합의 사항).
    """
    title: str
    amount: int = Field(ge=0, description="원 단위")
    category: str = ""
    date: str  # YYYY-MM-DD
    description: str = ""


class ReceiptData(BaseModel):
    """Intake(OCR) 결과 — 영수증에서 추출한 구조화 데이터."""
    amount: int | None = None
    date: str | None = None
    merchant: str | None = None
    items: list[str] = []
    parse_ok: bool = True
    parse_error: str | None = None


class Mismatch(BaseModel):
    """영수증-청구 불일치 항목 (REQ-028)."""
    field: Literal["amount", "date", "merchant", "items"]
    claimed: str
    receipt: str


class PolicyParams(BaseModel):
    """팀별 심사 파라미터 — 관리자 설정."""
    auto_approve_limit: int = 50_000          # 이 금액 초과 시 무조건 에스컬레이션
    force_escalation_amount: int = 300_000    # 절대 상한
    confidence_threshold: float = 0.8         # θ (§3.3)


class Opinion(BaseModel):
    """심사관 1명의 소견 — opinions 딕셔너리의 값."""
    auditor: Literal["rule", "budget", "precedent"]
    verdict: AuditorVerdict
    summary: str
    evidence: list[str] = []                  # rule: 근거 조항
    figures: dict[str, int | float] = {}      # budget: 잔액·한도 등 수치
    similar_cases: list[str] = []             # precedent: 유사 판례 요약


class GateResult(BaseModel):
    """guardrail_gate(순수 함수) 출력 (§3.3 1단계)."""
    decision: Literal["proceed", "escalate", "reject_candidate"]
    triggered_rules: list[str] = []           # 어떤 가드레일에 걸렸는지 (감사로그용)


class Reasons(BaseModel):
    """판정 사유 2종 (§3.3 2단계)."""
    requester: str  # 요청자용 — 정중·간결
    admin: str      # 관리자용 — 근거 조항·수치 포함
