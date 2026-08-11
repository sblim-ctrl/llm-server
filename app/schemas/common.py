"""도메인 공통 스키마 — ReviewState를 구성하는 값 객체들 (§4.2)."""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["approve", "reject", "escalate"]
AuditorVerdict = Literal["pass", "warn", "fail", "error"]


class LLMCallMeta(BaseModel):
    """LLM 호출 1건의 계측 메타 (§5.3 재현성·§9 비용 지표) — chat_structured가 채운다."""

    model: str
    prompt_version: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    mock: bool = False


class ExpenseClaim(BaseModel):
    """지출 청구 내용 — pull 모델에서는 요청에 없고 load_context가 백엔드
    get_expense_detail 조회 결과로 구성한다 (직접 그래프 호출 시엔 초기 상태로 주입).

    category는 어떤 값이 오든 **classify_category가 AI 분류로 확정한다** (T7,
    2026-08-06) — 들어온 값은 라벨로 쓰이지 않는다. 백엔드 계약상 null이 정상이고
    (등록 시 null 저장, 첫 심사 콜백의 suggestedCategory로 채움 — 8/6 회신), 채워져
    오는 값은 대부분 그 콜백 값이 재심사 때 되돌아온 에코다.
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
    """팀별 심사 파라미터 — 관리자 설정 (team_settings에서 load_context가 채움)."""

    # AI 자동판정 권한 스위치 (bravo 설계서: team_settings.auto_approve, 실서비스
    # 기본 FALSE). 꺼져 있으면 금액·판단과 무관하게 무조건 ESCALATED — guardrail_gate
    # 최상위 규칙. 모델 기본값 True는 목·단위테스트의 기존 흐름 보존용이고, 실제 값은
    # 항상 백엔드 조회 결과로 덮인다(조회 실패 시 load_context가 False로 fail-safe).
    auto_approve: bool = True
    auto_approve_limit: int = 50_000  # 이 금액 이상이면 무조건 에스컬레이션
    # 절대 상한 — 마법사 2단계 화면의 '고액 지출 20만원 이상' 기준에 맞춤
    force_escalation_amount: int = 200_000
    confidence_threshold: float = 0.8  # θ (§3.3)


class Opinion(BaseModel):
    """심사관 1명의 소견 — opinions 딕셔너리의 값."""

    # receipt(증빙 심사관)는 영수증-청구 대조 결과를 다른 심사관과 같은 형식으로
    # 내보내기 위한 것이다 (풀스택 협의 2026-08-04 — 지출 상세 'AI 심사결과'에
    # 증빙 심사관 추가). **판정 권한은 없다** — 가드레일은 기존대로 mismatch 리스트를
    # 보고 escalate를 결정하고, 이 소견은 화면에 근거를 보여주기 위한 표현이다.
    # 그래서 REQUIRED_AUDITORS(누락 시 에스컬레이션)에도 넣지 않는다.
    auditor: Literal["rule", "budget", "precedent", "evidence"]
    verdict: AuditorVerdict
    summary: str
    evidence: list[str] = []  # rule: 근거 조항
    figures: dict[str, int | float] = {}  # budget: 잔액·한도 등 수치 / receipt: 청구·영수증 금액
    similar_cases: list[str] = []  # precedent: 유사 판례 요약


class GateResult(BaseModel):
    """guardrail_gate(순수 함수) 출력 (§3.3 1단계)."""

    decision: Literal["proceed", "escalate", "reject_candidate"]
    triggered_rules: list[str] = []  # 어떤 가드레일에 걸렸는지 (감사로그용)


class Reasons(BaseModel):
    """판정 사유 2종 (§3.3 2단계)."""

    requester: str  # 요청자용 — 정중·간결
    admin: str  # 관리자용 — 근거 조항·수치 포함
