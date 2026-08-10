"""분류기 프롬프트 A/B — 카테고리 분류만 직접 호출해 버전별 정확도를 잰다.

골든셋으로는 분류기를 잴 수 없다. 골든셋의 기대 카테고리가 전부 카탈로그 밖 어휘라
채점 기준이 서지 않는다(T9에서 정합 예정). 그래서 라벨을 붙인 케이스로 직접
호출한다 — 팀장이 sblim에서 쓴 방식과 같다.
(2026-08-06 정정: 종전 사유였던 "카탈로그 밖 값이면 classify_category가 LLM을 부르기
 전에 즉시 반환한다"는 T7로 사라졌다 — 이제 어떤 값이 와도 항상 분류한다.)

**키워드 단독 정확도는 LLM 없이 잴 수 있다** — 아래 CASES에 `classify_by_keywords`를
돌리면 된다. 실측(2026-08-06, 재현): 카탈로그에서 '구입' 제거 전 17/17 → 제거 후
16/17 ('농구공 5개 구입'→기타). 카탈로그 주석이 명시한 의도된 교환의 비용 쪽 수치다.

실행:

    MOCK_LLM=false uv run python scripts/ab_classifier.py              # 기본 버전만
    MOCK_LLM=false uv run python scripts/ab_classifier.py v3 v4        # A/B

DB·백엔드가 필요 없다. gpt-4o-mini라 케이스당 비용이 매우 작다.

케이스는 9종 전부와 경계를 덮는다. 특히 '용도 vs 물건 형태'가 갈리는 쌍
(교재 구입/문구 구입, 회의실 대관/스터디룸 대관)을 넣었다 — v3가 실모드 스모크에서
"스터디 교재 구입"을 비품으로 분류한 것이 이 A/B의 출발점이다.
"""
import asyncio
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
    # 회의 vs 장소_대관 — 카탈로그 순서로 가른 경계
    ("월례 회의실 대관료", "회의"),
    ("스터디룸 4시간 대관", "장소_대관"),
    # 나머지 카테고리
    ("정기 모임 후 뒤풀이 치킨", "식비"),
    ("대회 참가 위한 KTX 왕복", "교통"),
    ("팀 노션 연간 구독료", "IT_인프라"),
    ("여름 MT 펜션 2박 예약", "장소_대관"),
    ("신입 모집 홍보 포스터 제작", "행사_활동"),
    ("지역 리그 참가비 납부", "행사_활동"),
    ("배드민턴 셔틀콕 3박스", "비품"),
    ("회원 경조사 조화", "기타"),
    # 활동 용품 vs 활동 참가 — v5가 규칙으로 가른 경계.
    # 셔틀콕은 v5 few_shot에 있으므로 아래 3건은 **예시에 없는 표현**으로 뒀다.
    # 개선이 암기가 아니라 규칙 학습인지 보기 위해서다.
    ("풋살 유니폼 12벌 제작", "비품"),
    ("농구공 5개 구입", "비품"),
    ("볼링 리그 참가 신청비", "행사_활동"),
    # 교육 참가비 vs 행사 참가비 — v7이 규칙으로 가른 경계 (2026-08-10).
    # 앞 2건은 **실모드 골든셋에서 실제로 틀렸던 두 케이스의 문구 그대로**다(측정 대상).
    # 나머지는 v7의 system·few_shot 어디에도 없는 표현이다 — 암기가 아니라 규칙을
    # 배웠는지 보려는 것이고, 뒤 3건은 반대 방향(과잉 적용) 감지용이다.
    ("대회 참가 강습비 전국 대회 참가를 위한 사전 강습비", "교육"),   # club-approve-004
    ("모임 강연 참가비 외부 강사 초청 강연 참가비", "교육"),          # social-approve-003
    ("주말 코딩 부트캠프 수강 신청비", "교육"),
    ("신입생 오리엔테이션 세미나 참가비", "교육"),
    ("교내 체육대회 팀 참가비", "행사_활동"),
    ("전국 동아리 페스티벌 등록비", "행사_활동"),
    ("합숙 훈련 숙소 대관료", "장소_대관"),        # 뒷말이 대상 — 훈련이 아니라 대관
    # v7 회귀 유형 4종 — 실모드 골든 2회 재현으로 확정된 자리(2026-08-10). v7의
    # '복합어는 뒷말이 대상' 규칙이 깨뜨렸고 v8이 그 규칙을 제거했다. v7의 A/B가
    # 이 유형을 안 덮어서 회귀를 통과시켰다 — 골든 문구를 베끼지 않은 동일 유형
    # 표현으로 그물을 메운다.
    ("가을 축제 부스 배너 제작", "행사_활동"),     # 행사 홍보물(물건 형태) — 현수막 유형
    ("어학 스터디 단어장 구입", "교육"),           # 학습 자료 구입 — '구입'이 물건축으로 끌면 안 됨
    ("동아리 물품 택배 발송비", "기타"),           # 택배·배송 — 교통이 아니다
    ("스터디 워크숍 펜션 숙박비", "장소_대관"),    # 행사 맥락 + 숙박 — 회의·교육이 아니다
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
