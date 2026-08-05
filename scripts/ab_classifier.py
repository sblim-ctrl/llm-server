"""분류기 프롬프트 A/B — 카테고리 분류만 직접 호출해 버전별 정확도를 잰다.

골든셋으로는 분류기를 잴 수 없다. 골든셋 42건의 카테고리가 전부 카탈로그 밖이라
`classify_category`가 LLM을 부르기 전에 즉시 반환한다(handoff §4-3). 그래서 라벨을
붙인 케이스로 직접 호출한다 — 팀장이 sblim에서 쓴 방식과 같다.

실행:

    MOCK_LLM=false uv run python scripts/ab_classifier.py              # 기본 버전만
    MOCK_LLM=false uv run python scripts/ab_classifier.py v3 v4        # A/B

DB·백엔드가 필요 없다. gpt-4o-mini라 케이스당 비용이 매우 작다.

케이스는 9종 전부와 경계를 덮는다. 특히 '용도 vs 물건 형태'가 갈리는 쌍
(교재 구입/문구 구입, 회의실 대관/스터디룸 대관)을 넣었다 — v3가 실모드 스모크에서
"스터디 교재 구입"을 비품으로 분류한 것이 이 A/B의 출발점이다.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings                                   # noqa: E402
from app.graphs.review.nodes.classify_category import CategoryPrediction  # noqa: E402
from app.llm.client import chat_structured                            # noqa: E402
from app.llm.prompts import load_prompt                               # noqa: E402
from app.tools.category_catalog import all_categories                 # noqa: E402

# (지출 내용, 기대 카테고리)
CASES = [
    # 용도 vs 물건 형태 — v3가 틀린 지점
    ("스터디 교재 구입 알고리즘 스터디 교재 2권", "교육"),
    ("회의용 마커와 포스트잇 구입", "비품"),
    ("전공 서적 3권 구입", "교육"),
    ("사무용품 구입 A4용지와 파일철", "비품"),
    # 회의 vs 장소/대관 — 카탈로그 순서로 가른 경계
    ("월례 회의실 대관료", "회의"),
    ("스터디룸 4시간 대관", "장소/대관"),
    # 나머지 카테고리
    ("정기 모임 후 뒤풀이 치킨", "식비"),
    ("대회 참가 위한 KTX 왕복", "교통"),
    ("팀 노션 연간 구독료", "IT/인프라"),
    ("여름 MT 펜션 2박 예약", "장소/대관"),
    ("신입 모집 홍보 포스터 제작", "행사/활동"),
    ("지역 리그 참가비 납부", "행사/활동"),
    ("배드민턴 셔틀콕 3박스", "비품"),
    ("회원 경조사 조화", "기타"),
]


async def classify(text: str, version: str | None) -> CategoryPrediction:
    spec = load_prompt("classifier", version) if version else load_prompt("classifier")
    candidates = all_categories()
    pred, _ = await chat_structured(
        agent="classifier",
        system=spec.system_with_few_shot(),
        user=f"카테고리 후보(이 중에서만 선택): {', '.join(candidates)}\n\n지출 내용: {text}",
        schema=CategoryPrediction,
        mock_response=CategoryPrediction(category="기타"),
        prompt_version=spec.version,
    )
    return pred


async def run_version(version: str | None) -> tuple[str, list[tuple]]:
    spec = load_prompt("classifier", version) if version else load_prompt("classifier")
    rows = []
    for text, expected in CASES:
        pred = await classify(text, version)
        valid = pred.category in all_categories()
        rows.append((text, expected, pred.category, pred.confidence, valid))
    return spec.version, rows


async def main() -> int:
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드가 아닙니다 — MOCK_LLM=false 환경변수와 OPENAI_API_KEY가 필요합니다.")
        return 2

    versions = sys.argv[1:] or [None]
    results = {}
    for v in versions:
        label, rows = await run_version(v)
        results[label] = rows

    labels = list(results)
    print(f"분류기 A/B — 케이스 {len(CASES)}건\n")
    head = f"{'지출 내용':<34} {'기대':<10}" + "".join(f" {lab:<20}" for lab in labels)
    print(head)
    print("-" * len(head))
    for i, (text, expected) in enumerate(CASES):
        line = f"{text[:33]:<34} {expected:<10}"
        for lab in labels:
            _, _, got, conf, valid = results[lab][i]
            mark = "O" if got == expected else "X"
            flag = "" if valid else "!"      # 후보 밖 값 = 코드가 폐기한다
            line += f" {mark} {got}{flag} {conf:.2f}".ljust(21)
        print(line)

    print()
    for lab in labels:
        rows = results[lab]
        hit = sum(1 for _, exp, got, _, _ in rows if got == exp)
        invalid = sum(1 for *_, valid in rows if not valid)
        lows = sum(1 for _, _, _, c, _ in rows if c < 0.8)
        print(f"{lab:<20} 정확도 {hit}/{len(rows)} = {hit / len(rows):.1%}"
              f" · 후보 밖 출력 {invalid}건 · 저확신(<0.8) {lows}건")

    if len(labels) > 1:
        base, cand = labels[0], labels[-1]
        changed = [(CASES[i][0], results[base][i][2], results[cand][i][2])
                   for i in range(len(CASES))
                   if results[base][i][2] != results[cand][i][2]]
        print(f"\n판정이 달라진 건: {len(changed)}건")
        for text, a, b in changed:
            exp = dict(CASES)[text]
            verdict = "개선" if b == exp else ("회귀" if a == exp else "변화")
            print(f"  [{verdict}] {text[:40]} : {a} → {b} (기대 {exp})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
