"""프롬프트 YAML 로더 (스프린트1 C3 계약) — `prompts/{agent}/{version}.yaml`.

버전의 진실 원천은 YAML 내부 `version:` 필드다 (파일명 아님) — 판정 기록·판례에
남는 prompt_version은 항상 `load_prompt(...).version`을 쓴다. YAML 형식은
version / system / output_schema(문서용 주석) / few_shot 4키로 고정
(기존 prompts/rule_auditor/v1.yaml 기준). 신규 에이전트 프롬프트도 동일 형식.
"""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_ENV_PREFIX = "PROMPT_VERSION_"  # A/B 실험용 오버라이드: PROMPT_VERSION_ADJUDICATOR=v2

# 에이전트별 기본 버전 — 실측 A/B로 우세가 재현된 버전만 승격한다 (미등재=v1).
# 승격 근거(2026-07-20 실모드 골든셋 6회전, 오승인 전 회차 0 — 상세 PROGRESS §6-1):
# rule_auditor v1 80.0% → v2 93.3%·90.0%(재현) → v3+temp0 100.0% (연 한도 편차 해소)
# adjudicator v1 80.0% → v2 93.3%~ (잔액 부족 확신 반려)
# briefing_writer v1 3/5(bf-override·bf-gap 실패) → v2 5/5, verified 불통과 0건
#   (실키 writers golden, gap_categories 처리·0건 생략 금지 few_shot 보강 효과)
# report_writer v1 4/4 → v2 4/4 유지(실키 writers golden, 회귀 없음 확인 후 승격)
#
# 2026-07-24 골든셋 receiptPath를 실제 로컬 이미지(file://)로 교체 후 재측정.
# 주의: compare_prompts.py는 A(베이스라인)를 먼저 실행해 판례를 쌓고 그 위에서
# B(오버라이드)를 평가하는 구조라, 초기 측정에서 adjudicator/rule_auditor/
# classifier 전부 동일한 3개 adversarial 케이스(hobby-adversarial-001·
# social-adversarial-001·study-adversarial-002)가 "회귀"로 보였다 — 오버라이드
# 없이 판례만 안 지우고 재실행해도 동일하게 재현되어(57/60·95.0%), 프롬프트
# 문제가 아니라 A→B 판례 오염 아티팩트임을 확정했다. 이후 전부 골든-* 팀 판례
# 리셋 + 단독 실행(compare 없이 PROMPT_VERSION_*만 지정)으로 재검증:
# adjudicator v2 100.0%(2회) vs v3 100.0%(2회) — 동률이나 v3는
#   build_adjudication_user(근거 조항·수치·판례 확장 입력)와 few_shot 형식이
#   정합하는 필수 수정이라 승격.
# intake v1 100.0%(수 회) vs v2 100.0%(2회) — 동률, items 포맷 고정 등 부가
#   개선이라 회귀 없음 확인 후 승격.
# classifier: 골든셋 60건 전부 category가 이미 지정돼 있어 classify_category가
#   즉시 반환 — LLM classifier 자체가 호출되지 않음(A/B 무효). category 없는
#   대표 케이스 직접 호출 스모크(5유형+fallback 1건)로 재검증: v1 6/6 = v2 6/6
#   동률이나, v1 few_shot이 실제 카탈로그와 다른 가짜 후보 라벨을 쓰던 결함을
#   v2가 수정했으므로 승격.
# rule_auditor v3 100.0%(2회) vs v4 100.0%(2회) — 완전 동률, v4는 조항 번호
#   인용이라는 순수 부가 개선이라 기존 방침("동률이면 v3 유지") 그대로 미승격.
# precedent_auditor v2: 판례 리셋한 클린 상태에서도 100.0%→61.7% 붕괴(23건,
#   대부분 승인 기대 건이 보류로) — 판례 오염과 무관한 진짜 결함. "중복·분할
#   청구 검사는 결정주체 무관"이라는 v2 규칙이 AGENT의 정상 반복 승인(매달
#   반복되는 도서 구입 등)을 중복/분할 청구로 오탐. 미승격, 재작업 필요.
DEFAULT_VERSIONS = {
    "rule_auditor": "v3",
    "adjudicator": "v3",
    "briefing_writer": "v2",
    "report_writer": "v2",
    "intake": "v2",
    "classifier": "v2",
}


class PromptSpec(BaseModel):
    version: str
    system: str
    few_shot: list[dict] = []

    def system_with_few_shot(self) -> str:
        """few_shot이 있으면 system 뒤에 예시 블록을 조립해 반환."""
        if not self.few_shot:
            return self.system
        examples = "\n\n".join(
            f"예시 {i}:\n입력: {ex.get('input', '')}\n출력: {ex.get('output', '')}"
            for i, ex in enumerate(self.few_shot, 1)
        )
        return f"{self.system}\n\n{examples}"


@lru_cache
def _load(agent: str, version: str) -> PromptSpec:
    path = _PROMPTS_DIR / agent / f"{version}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptSpec(
        version=data["version"], system=data["system"], few_shot=data.get("few_shot") or []
    )


def load_prompt(agent: str, version: str | None = None) -> PromptSpec:
    """version 미지정 시 `PROMPT_VERSION_{AGENT}` 환경변수 → DEFAULT_VERSIONS → 'v1'.

    환경변수 해석을 캐시 밖에서 하므로, A/B 비교 러너(eval/compare_prompts.py)가
    같은 프로세스 안에서 버전을 바꿔가며 실행해도 즉시 반영된다.
    """
    version = (
        version
        or os.environ.get(f"{_ENV_PREFIX}{agent.upper()}")
        or DEFAULT_VERSIONS.get(agent, "v1")
    )
    return _load(agent, version)
