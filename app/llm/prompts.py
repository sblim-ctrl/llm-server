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
_ENV_PREFIX = "PROMPT_VERSION_"   # A/B 실험용 오버라이드: PROMPT_VERSION_ADJUDICATOR=v2

# 에이전트별 기본 버전 — 실측 A/B로 우세가 재현된 버전만 승격한다 (미등재=v1).
# 승격 근거(2026-07-20 실모드 골든셋 6회전, 오승인 전 회차 0 — 상세 PROGRESS §6-1):
# rule_auditor v1 80.0% → v2 93.3%·90.0%(재현) → v3+temp0 100.0% (연 한도 편차 해소)
# adjudicator v1 80.0% → v2 93.3%~ (잔액 부족 확신 반려)
DEFAULT_VERSIONS = {
    "rule_auditor": "v3",
    "adjudicator": "v3",     # 관리자용 사유 수치 인용 명시 — v2도 실측상 100% 인용
                             #  이었으나(개선 아님) 드문 편차 방어 보험. 부작용 0 확인,
                             #  요청자용 수치 노출 없음 (v2 vs v3 실측 2026-07-22)
    "digest_writer": "v2",   # 총무 코멘트(advice) 섹션 — 실모드 확인 2026-07-20
    "judge": "v3",           # 근거 충실성(환각 검증) 차원 — 실모드 A/B 승격(2026-07-29):
                             #  정상 사유 17/17 v2와 일치(과잉 불합격 0) + 수치 조작
                             #  프로브 6/6 탐지(v2는 0/6). 캘리브레이션 2회+judge 모델
                             #  mini→4o 승급이 전제(models.yaml 참조)
    "policy_drafter": "v2",  # few_shot 3종+분량·문체 기준 — 실모드 승격(2026-07-29):
                             #  비겹침 시나리오 4종에서 조항 3.0→5.2개, 운영규칙→
                             #  지출기준 전환, 예시 복사 0건 (7/28 실측 2회 재현)
    "classifier": "v5",      # 전역 9종 대응(v3) → 물건 형태의 교육 지출(v4) →
                             #  활동 용품 vs 활동 참가 경계(v5). 전부 실모드 A/B 승격
                             #  (2026-08-04, 각 2회 재현. 하니스 scripts/ab_classifier.py):
                             #    v3 11/14(78.6%) → v4 13/14(92.9%)  회귀 0
                             #    v4 14/17(82.4%) → v5 17/17(100%)   회귀 0
                             #  v5 개선 3건 중 2건(풋살 유니폼·농구공)은 few_shot에 없는
                             #  표현이라 암기가 아니라 규칙 학습이다. 우리 9종은 축이
                             #  섞여 있어(교육·식비는 용도 축, 비품은 물건 축) 경계를
                             #  명시해야 모델이 기타로 도망가지 않는다.
                             #  v2를 건너뛴 이유는 sblim에 다른 내용의 v2가 있어서다.
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
            for i, ex in enumerate(self.few_shot, 1))
        return f"{self.system}\n\n{examples}"


@lru_cache
def _load(agent: str, version: str) -> PromptSpec:
    path = _PROMPTS_DIR / agent / f"{version}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptSpec(version=data["version"], system=data["system"],
                      few_shot=data.get("few_shot") or [])


def load_prompt(agent: str, version: str | None = None) -> PromptSpec:
    """version 미지정 시 `PROMPT_VERSION_{AGENT}` 환경변수 → DEFAULT_VERSIONS → 'v1'.

    환경변수 해석을 캐시 밖에서 하므로, A/B 비교 러너(eval/compare_prompts.py)가
    같은 프로세스 안에서 버전을 바꿔가며 실행해도 즉시 반영된다.
    """
    version = (version
               or os.environ.get(f"{_ENV_PREFIX}{agent.upper()}")
               or DEFAULT_VERSIONS.get(agent, "v1"))
    return _load(agent, version)
