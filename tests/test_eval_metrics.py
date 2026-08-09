"""판정 지표 순수 함수 테스트 (§4 Sprint 2)."""
from app.eval_metrics import (
    automation_rate, confusion_matrix, per_class_prf, verdict_metrics,
)


def _r(expected, actual):
    return {"expected": expected, "actual": actual}


# 시나리오: approve 3건(2정답·1을 escalate로 흘림), reject 2건(정답),
#           escalate 3건(2정답·1을 approve로 오판 = 위험한 오분류)
RESULTS = [
    _r("approve", "approve"), _r("approve", "approve"), _r("approve", "escalate"),
    _r("reject", "reject"), _r("reject", "reject"),
    _r("escalate", "escalate"), _r("escalate", "escalate"), _r("escalate", "approve"),
]


def test_confusion_matrix_counts():
    cm = confusion_matrix(RESULTS)
    assert cm["approve"]["approve"] == 2
    assert cm["approve"]["escalate"] == 1
    assert cm["escalate"]["escalate"] == 2
    assert cm["escalate"]["approve"] == 1     # 위험한 오분류 1건 포착
    assert cm["reject"]["reject"] == 2


def test_escalate_precision_recall():
    prf = per_class_prf(RESULTS)
    esc = prf["escalate"]
    # 실제 escalate로 판정: approve→esc 1 + escalate→esc 2 = 3, 그중 맞은 것 2 → P=2/3
    assert round(esc["precision"], 3) == round(2 / 3, 3)
    # 기대 escalate 3건 중 실제 escalate 2건 → R=2/3
    assert round(esc["recall"], 3) == round(2 / 3, 3)
    assert esc["support"] == 3


def test_approve_precision_recall():
    prf = per_class_prf(RESULTS)
    ap = prf["approve"]
    # 실제 approve 판정: approve→ap 2 + escalate→ap 1 = 3, 맞은 것 2 → P=2/3
    assert round(ap["precision"], 3) == round(2 / 3, 3)
    # 기대 approve 3건 중 2건 approve → R=2/3
    assert round(ap["recall"], 3) == round(2 / 3, 3)


def test_perfect_class_is_one():
    prf = per_class_prf(RESULTS)
    rej = prf["reject"]                       # reject는 완벽
    assert rej["precision"] == 1.0 and rej["recall"] == 1.0 and rej["f1"] == 1.0


def test_automation_rate():
    # actual이 approve/reject인 건: approve 2 + reject 2 + (escalate→approve) 1 = 5 / 8
    assert automation_rate(RESULTS) == 5 / 8


def test_empty_results_safe():
    assert automation_rate([]) == 0.0
    prf = per_class_prf([])
    assert prf["approve"]["precision"] is None   # 예측·정답 0 → 정의 안 됨(N/A)
    assert prf["approve"]["support"] == 0


def test_no_prediction_precision_is_none():
    """어떤 라벨로도 판정하지 않으면 그 라벨 precision은 None(0으로 왜곡 안 함)."""
    prf = per_class_prf([_r("approve", "approve")])
    assert prf["escalate"]["precision"] is None   # escalate 판정 0건
    assert prf["escalate"]["recall"] is None       # escalate 기대 0건


def test_verdict_metrics_bundle():
    m = verdict_metrics(RESULTS)
    assert m["escalation_recall"] == m["per_class"]["escalate"]["recall"]
    assert m["escalation_precision"] == m["per_class"]["escalate"]["precision"]
    assert "confusion" in m and "automation_rate" in m


def test_zero_precision_reports_zero_not_na():
    """전부 틀린 것(0.0)과 측정 불가(None)를 구분한다.

    진리값 검사로 짜면 precision=0.0이 None으로 빠져 화면에 N/A로 뜬다.
    성능이 바닥인 상황이 오히려 안 보이게 되는 쪽이라 위험하다.
    """
    # reject 정답 1건을 approve로 흘리고, approve로 판정한 건은 그것뿐 → approve precision 0.0
    results = [_r("reject", "approve")]
    ap = per_class_prf(results)["approve"]
    assert ap["precision"] == 0.0, "N/A가 아니라 0.0이어야 한다"
    assert ap["recall"] is None, "approve 정답이 0건이라 recall은 측정 불가"
    assert ap["f1"] is None, "recall이 없으면 f1도 측정 불가"


def test_f1_is_zero_when_both_zero():
    """precision·recall이 둘 다 0이면 f1은 0.0이다 (0으로 나누지 않는다)."""
    # escalate 정답 1건을 approve로 흘리고, escalate로 판정한 것도 1건 있으나 오답
    results = [_r("escalate", "approve"), _r("approve", "escalate")]
    esc = per_class_prf(results)["escalate"]
    assert esc["precision"] == 0.0 and esc["recall"] == 0.0
    assert esc["f1"] == 0.0


# ── 분류 채점 (T9) ────────────────────────────────────────
#
# 판정 지표와 달리 **게이트가 아니라서** 여기가 틀려도 CI가 빨개지지 않는다.
# 그래서 채점 자체가 망가지면 조용히 틀린 숫자가 나온다 — 그물을 여기 놓는다
# (2026-08-07 뮤테이션 검증: 이 그물이 없을 때 결함 6종이 전부 통과했다).

from app.eval_metrics import category_metrics, score_category  # noqa: E402


def _c(cid, expected, actual):
    """분류 채점 대상 결과 한 줄."""
    return {
        "id": cid,
        "expected_category": expected,
        "actual_category": actual,
        "category_ok": score_category(actual, expected),
    }


def test_score_category_distinguishes_hit_from_miss():
    """맞음과 틀림이 갈려야 한다 — 항상 True로 짜면 정확도가 영원히 100%가 된다."""
    assert score_category("식비", "식비") is True
    assert score_category("교통", "식비") is False


def test_case_without_expected_is_not_scored():
    """정답을 안 매긴 케이스는 채점 대상이 아니다(None) — 오답으로 깎지 않는다."""
    assert score_category("식비", None) is None
    assert score_category("식비", "") is None


def test_missing_classification_counts_as_miss():
    """기대값이 있는데 아무 카테고리도 못 냈으면 오답이다 (claim이 없는 경로)."""
    assert score_category(None, "식비") is False


def test_accuracy_denominator_excludes_unscored_cases():
    """분모는 **기대값이 있는 케이스만**이다.

    전체 건수를 분모로 쓰면 정답을 안 매긴 케이스가 정확도를 조용히 끌어내린다.
    """
    results = [
        _c("a", "식비", "식비"),
        _c("b", "교통", "교육"),      # 오답
        _c("c", None, "비품"),        # 채점 제외
    ]
    m = category_metrics(results)
    assert m["category_total"] == 2, "채점 제외 케이스가 분모에 들어갔다"
    assert m["category_correct"] == 1
    assert m["category_accuracy"] == 0.5


def test_misses_name_what_went_wrong():
    """오분류는 개수만이 아니라 무엇이 무엇으로 틀렸는지까지 나와야 한다.

    숫자만 있으면 정확도가 떨어졌을 때 어디를 볼지 알 수 없다.
    """
    results = [_c("a", "식비", "식비"), _c("b", "교통", "교육")]
    misses = category_metrics(results)["category_misses"]
    assert misses == [{"id": "b", "expected": "교통", "actual": "교육"}]


def test_accuracy_is_none_when_nothing_is_scorable():
    """채점할 게 하나도 없으면 0%가 아니라 '측정 불가'다 (0으로 나누지 않는다)."""
    m = category_metrics([_c("a", None, "식비")])
    assert m["category_total"] == 0
    assert m["category_accuracy"] is None
    assert m["category_misses"] == []


def test_csv_carries_the_category_columns():
    """결과 CSV에 분류 채점 3열이 실려야 한다 — 헤더와 행의 열 수가 어긋나면 안 된다.

    CSV는 사람이 오분류를 훑는 통로다(가이드 제출물). 열이 하나 빠지면 이후 열이
    통째로 밀려 다른 값으로 읽힌다.
    """
    import csv as _csv

    from app.eval_support import export_results_csv

    row = {
        "id": "case-1", "scenario": "", "expected": "approve", "actual": "approve",
        "correct": True, "false_approve": False, "gate": [], "expected_gate": [],
        "trajectory_ok": None, "expected_category": "식비", "actual_category": "교통",
        "category_ok": False,
    }
    path = export_results_csv([row])
    with path.open(encoding="utf-8-sig") as f:
        header, data = list(_csv.reader(f))[:2]
    assert len(header) == len(data), "헤더와 행의 열 수가 다르다"
    at = {k: v for k, v in zip(header, data, strict=True)}
    assert at["expected_category"] == "식비"
    assert at["actual_category"] == "교통"
    assert at["category_ok"] == "False"
