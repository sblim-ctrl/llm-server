"""모임 유형별 기본 정책 — 회칙을 등록하지 않은 팀의 심사 근거.

마법사 3단계에서 회칙 등록을 건너뛰면 화면이 "나중에 등록해도 돼요. 없으면 기본 정책
모드로 시작해요"라고 안내한다(프로토타입 10/38). 그 '기본 정책'의 실체가 이 모듈이다 —
templates/policy_templates.yaml의 유형별 기본 조항을 심사 근거로 쓴다.

전에는 회칙이 없으면 rule_auditor가 무조건 pass여서 회칙 심사가 통째로 비었다.

## 금액 조항을 근거에서 빼는 이유

기본 조항 중 금액 한도가 든 것과 영수증·증빙 첨부를 다루는 것은 근거로 쓰지 않는다.

1. **중복이다.** 금액은 이미 가드레일이 본다 — `auto_approve_limit` 이하만 자동 심사고
   `force_escalation_amount` 이상은 무조건 관리자다. 회칙 축에서 또 금액을 따지면
   같은 잣대를 두 번 대는 셈이다. 영수증 첨부·판독 여부도 마찬가지로 evidence
   심사관(증빙 심사관, `mismatch_gate`)과 가드레일(`receipt_unreadable`)이 이미 판단한다
   — rule 축이 같은 사실을 또 판단하면 화면에 같은 내용이 두 번 뜬다.
2. **팀이 합의한 금액이 아니다.** 템플릿의 한도는 우리가 모임 유형만 보고 정한 값이다.
   회칙 등록을 건너뛴 팀은 그 숫자에 동의한 적이 없다. 합의한 적 없는 금액을 근거로
   지출을 문제 삼으면 관리자가 납득할 수 없고, 화면의 "나중에 등록해도 돼요"라는
   가벼운 톤과도 어긋난다.

남는 것은 성격 조항(개인 용도·목적 무관 등)인데, 이건 유형과 무관하게 대체로 통용되는
상식에 가까워 기본값으로 적용해도 무리가 없다.

## 금액 조항을 가려내는 방법

템플릿 placeholder **유무**로 가른다 — 구현은 `"{" not in r` 한 줄이라 placeholder
이름이 바뀌어도 따라간다. 금액이 든 조항은 전부 치환을 쓰기 때문에 정확히 갈린다.
템플릿에 새 조항을 추가할 때 금액을 넣는다면 반드시 placeholder를 쓸 것.

현재 쓰이는 이름은 `{auto_approve_limit}`·`{meal}`·`{venue}`·`{supplies}`·
`{transport}`·`{education}`·`{event}`·`{gift}`·`{travel}`·`{dues}`·`{dues_period}`다.
2026-08-11 회칙 개편으로 유형별 한도가 도입되며 구 `{per_meal_limit}`은 사라졌는데
이 문단이 그 이름을 근거로 들고 있었다 (PR #65 리뷰 N3으로 정정).

## 영수증 조항을 가려내는 방법

"영수증"·"증빙" 키워드로 가른다(5유형 전수 확인 — 유형마다 정확히 1건씩 존재, 필터 후
성격 조항 1~3건 남아 빈 근거로 떨어지는 유형 없음). `templates/policy_templates.yaml`
자체는 건드리지 않는다 — PolicyDrafter가 만드는 회칙 초안에는 영수증 조항이 그대로
들어가야 한다(팀이 실제로 등록할 회칙이므로). 여기서 빼는 것은 **회칙을 등록 안 한
팀의 임시 심사 근거**로 쓸 때뿐이다.
"""

from functools import lru_cache
from pathlib import Path

import yaml

_TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "templates" / "policy_templates.yaml"

# 유형을 못 받았거나 템플릿에 없는 유형일 때 — load_context.DEFAULT_TEAM_TYPE와 같은 값.
FALLBACK_TEAM_TYPE = "동아리/학생회"


@lru_cache
def load_templates() -> dict:
    return yaml.safe_load(_TEMPLATES_PATH.read_text(encoding="utf-8"))


@lru_cache
def default_conduct_rules(team_type: str) -> tuple[str, ...]:
    """기본 정책 모드의 심사 근거 — 유형별 성격 조항만. 금액 한도·영수증 조항은 뺀다.

    tuple을 반환하는 것은 lru_cache 캐시값이 밖에서 변형되지 않게 하기 위해서다.
    """
    templates = load_templates()
    template = templates.get(team_type) or templates[FALLBACK_TEAM_TYPE]
    return tuple(
        r for r in template["base_rules"] if "{" not in r and "영수증" not in r and "증빙" not in r
    )
