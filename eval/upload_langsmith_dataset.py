"""골든셋 → LangSmith Dataset 업로드 (Sprint 2 선행, 관측 트랙).

실행:  uv run python eval/upload_langsmith_dataset.py [golden_path]
       (.env의 LANGSMITH_API_KEY 필요 — LANGSMITH_TRACING은 무관)

golden_v1.json의 케이스들을 LangSmith Dataset으로 올린다 — 웹 UI에서 케이스를
탐색하고, 이후 Experiment(프롬프트 버전 간 비교 실행)를 데이터셋 기준으로 관리하는
기반. 멱등: 같은 이름의 데이터셋이 있으면 지우고 현재 파일 기준으로 재생성한다
(진실 원천은 항상 리포의 golden json — LangSmith는 뷰).

example 구조:
- inputs : 심사 그래프 초기 상태 재료 (pull 모델 5필드 + receipt_text 변환값)
- outputs: 기대 판정·오승인 금지 여부·기대 가드레일 (채점 기준)
- metadata: 시나리오·모임 유형 (UI 필터용)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_settings                    # noqa: E402
from eval.run_eval_real import receipt_text_for        # noqa: E402 — 변환 규약 공유

DATASET_NAME = "budgetops-golden"


def main() -> int:
    s = get_settings()
    if not s.langsmith_api_key:
        print("LANGSMITH_API_KEY가 없습니다 (.env) — 업로드 불가")
        return 2

    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "eval" / "golden" / "golden_v1.json")
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]

    from langsmith import Client
    client = Client(api_key=s.langsmith_api_key)

    # 멱등: 기존 동명 데이터셋 제거 후 재생성 (리포 json이 진실 원천)
    if client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
        print(f"기존 데이터셋 '{DATASET_NAME}' 제거")

    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description=(f"BudgetOps 심사 골든셋 {golden['version']} ({len(cases)}건) — "
                     "진실 원천은 리포 eval/golden/golden_v1.json (이 데이터셋은 뷰). "
                     "실행 하니스: eval/run_eval_real.py"),
    )
    client.create_examples(
        dataset_id=dataset.id,
        inputs=[{**c["input"], "receipt_text": receipt_text_for(c["input"])}
                for c in cases],
        outputs=[{"expected_verdict": c["expected_verdict"],
                  "must_not_approve": bool(c.get("must_not_approve")),
                  "expected_gate_includes": c.get("expected_gate_includes", []),
                  # 분류 채점 기준 — run_eval_real.py와 같은 축. 없으면 채점 제외(None)
                  "expected_category": c.get("expected_category", "")}
                 for c in cases],
        metadata=[{"case_id": c["id"], "scenario": c.get("scenario", ""),
                   "team_type": c.get("team_type", "")} for c in cases],
    )

    n = sum(1 for _ in client.list_examples(dataset_id=dataset.id))
    print(f"업로드 완료: '{DATASET_NAME}' — {n}건 (골든셋 {golden['version']})")
    print("LangSmith 웹 → Datasets에서 확인 가능")
    return 0 if n == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
