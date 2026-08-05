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
