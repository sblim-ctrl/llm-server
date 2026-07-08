"""PIIMasker — 멤버 실명 → 역할명 치환 (§4.3, REQ-042·043 익명화).

프롬프트 투입 전·판례 저장 전·브리핑 생성 전에 적용한다.
mask_names는 순수 함수 — 단위 테스트 대상.

멤버 명단은 백엔드에서 받아야 하지만(연동 미확정) 함수 자체는 명단을
인자로 받는 순수 구조라 연동 방식과 무관하게 완성 상태다.
"""
from collections import Counter


def build_alias_map(members: list[dict]) -> dict[str, str]:
    """[{name, role}] → {실명: 역할별칭}. 같은 역할이 여럿이면 번호를 붙여 구분한다.

    예: [{"name":"김철수","role":"총무"}, {"name":"이영희","role":"회원"},
         {"name":"박민준","role":"회원"}]
        → {"김철수": "총무", "이영희": "회원1", "박민준": "회원2"}
    """
    role_counts = Counter(m["role"] for m in members)
    seen: Counter = Counter()
    alias: dict[str, str] = {}
    for m in members:
        role = m["role"]
        if role_counts[role] > 1:
            seen[role] += 1
            alias[m["name"]] = f"{role}{seen[role]}"
        else:
            alias[m["name"]] = role
    return alias


def mask_names(text: str, members: list[dict]) -> str:
    """텍스트 내 멤버 실명을 역할명으로 치환. 긴 이름부터 치환해 부분 일치 오염 방지."""
    if not text or not members:
        return text
    alias = build_alias_map(members)
    for name in sorted(alias, key=len, reverse=True):
        text = text.replace(name, alias[name])
    return text
