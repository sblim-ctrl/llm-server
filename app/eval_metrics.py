"""판정 품질 지표 — 순수 함수 (§4 Sprint 2 '심사관별 평가·에스컬레이션 P/R').

정확도 하나로는 안 보이는 것을 분해한다:
- 혼동 행렬: 어떤 오분류가 나는지 (approve를 escalate로? reject를 approve로?)
- 클래스별 Precision/Recall/F1: 특히 escalate(사람에게 넘김)의 P/R —
  Recall이 낮으면 넘겨야 할 걸 자동 처리한 것(위험), Precision이 낮으면 불필요하게
  많이 넘긴 것(자동화율 저하). 안전 최우선이라 escalate Recall이 핵심 안전 지표.
- 자동 처리율: 사람 개입 없이 자동 종결(approve/reject)한 비율 — 서비스 가치 지표.

입력은 run_case 결과 리스트({expected, actual, ...})면 충분하다 — DB·LLM 무관.
"""
from typing import Any

VERDICTS = ("approve", "reject", "escalate")


def confusion_matrix(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """expected → actual 카운트. 알 수 없는 라벨은 무시(방어)."""
    m = {e: {a: 0 for a in VERDICTS} for e in VERDICTS}
    for r in results:
        exp, act = r["expected"], r["actual"]
        if exp in m and act in m[exp]:
            m[exp][act] += 1
    return m


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int | None]:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    # None(측정 불가)과 0.0(측정했는데 전부 틀림)을 구분한다. 진리값으로 검사하면
    # precision=0.0이 None으로 빠져 화면에 N/A로 뜨는데, 그건 "재료가 없다"는 뜻이라
    # 성능이 바닥인 상황이 오히려 안 보이게 된다. 분모가 0일 때만 f1도 None이다.
    if precision is None or recall is None:
        f1: float | None = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}


def per_class_prf(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """클래스별 Precision/Recall/F1/support (support = 기대가 그 라벨인 건수)."""
    cm = confusion_matrix(results)
    out: dict[str, dict[str, Any]] = {}
    for label in VERDICTS:
        tp = cm[label][label]
        fp = sum(cm[e][label] for e in VERDICTS if e != label)  # 잘못 이 라벨로 판정
        fn = sum(cm[label][a] for a in VERDICTS if a != label)  # 이 라벨인데 놓침
        out[label] = _prf(tp, fp, fn)
    return out


def automation_rate(results: list[dict[str, Any]]) -> float:
    """자동 처리율 — actual이 approve/reject(사람 개입 없이 종결)인 비율."""
    if not results:
        return 0.0
    auto = sum(1 for r in results if r["actual"] in ("approve", "reject"))
    return auto / len(results)


def verdict_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """판정 지표 묶음 — run_golden_set summary에 그대로 얹는다."""
    prf = per_class_prf(results)
    esc = prf["escalate"]
    return {
        "confusion": confusion_matrix(results),
        "per_class": prf,
        "automation_rate": automation_rate(results),
        # 안전 핵심 지표를 최상위로도 노출 — escalate Recall(놓치지 않았나)
        "escalation_recall": esc["recall"],
        "escalation_precision": esc["precision"],
    }


def score_category(actual: str | None, expected: str | None) -> bool | None:
    """분류 채점 한 건 — 사람이 매긴 정답 대비 AI가 확정한 카테고리.

    기대값이 없는 케이스는 **채점 대상이 아니다(None)**. False로 두면 정답을 안 매긴
    케이스가 오답으로 깎여 분모·분자가 같이 틀어진다.

    `actual`이 None인 것(claim이 없는 경로)은 오답으로 센다 — 기대값이 있는데 아무
    카테고리도 못 냈다는 뜻이라 맞혔다고 볼 수 없다.
    """
    if not expected:
        return None
    return actual == expected


def category_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """분류 정확도 — 기대값이 있는 케이스만 분모에 넣는다.

    **판정과 독립된 관측 지표이고 하드 게이트가 아니다.** 목 모드 분류는 실LLM을 안
    부르고 키워드 규칙으로 답하므로 이 숫자는 "키워드 규칙의 정확도"이지 실서비스 품질이
    아니다. 게이트로 만들면 실모드에서만 나올 개선을 목 숫자로 막게 된다 — 임계값은
    실모드 측정(`eval/run_eval_real.py`) 후에 정한다.

    오분류를 세기만 하지 않고 `category_misses`로 **무엇이 무엇으로 틀렸는지**까지
    돌려준다. 숫자만 있으면 떨어졌을 때 어디를 볼지 알 수 없다.
    """
    cases = [r for r in results if r.get("category_ok") is not None]
    correct = sum(1 for r in cases if r["category_ok"])
    return {
        "category_total": len(cases),
        "category_correct": correct,
        "category_accuracy": (correct / len(cases)) if cases else None,
        "category_misses": [
            {"id": r["id"], "expected": r["expected_category"], "actual": r["actual_category"]}
            for r in cases
            if not r["category_ok"]
        ],
    }
