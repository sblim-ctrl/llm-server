"""reviews_stream — SSE 포맷·노드 라벨 정합 (데모·관측 전용 스트리밍, 강의 04-07).

전체 그래프 실행 검증은 골든셋(eval)·대시보드 수동 경로 담당 — 여기서는
의존성 없는 순수 부분만: SSE 직렬화 형식과, 타임라인 노드 목록이 실제 심사
그래프 배선과 일치하는지(노드 추가·개명 시 드리프트 감지)를 잠근다.
"""
from app.api.reviews_stream import NODE_LABELS, _sse
from app.graphs.review.graph import build_review_graph


def test_sse_format_and_korean_passthrough():
    out = _sse("node", {"label": "회칙 심사관", "ms": 3})
    assert out.startswith("event: node\ndata: ")
    assert out.endswith("\n\n")                # SSE 이벤트 구분자
    assert '"회칙 심사관"' in out              # ensure_ascii=False — 한글 원문 유지


def test_node_labels_match_review_graph():
    """타임라인이 그리는 노드 == 실제 그래프 노드 (배선 변경 시 여기서 잡힌다)."""
    g = build_review_graph()
    graph_nodes = set(g.get_graph().nodes) - {"__start__", "__end__"}
    assert graph_nodes == set(NODE_LABELS)


def test_node_labels_order_follows_graph_wiring():
    """NODE_LABELS의 나열 순서가 그래프 배선의 위상 순서인지 — set 비교로는 못 잡는다.

    화면 단계 목록이 이 dict 순서 그대로 프론트에 실려 나가는데(steps 이벤트),
    2026-08-06 그래프 순서 변경(intake_receipt를 classify_category 앞으로) 때
    여기가 옛 순서로 남아 3번째 단계가 2번째보다 먼저 켜지는 표시 어긋남이 있었다.
    모든 간선 (u→v)에 대해 u가 v보다 먼저 나열돼야 한다로 잠근다 — 다음 순서
    변경 때는 이 테스트가 잡는다.
    """
    g = build_review_graph().get_graph()
    pos = {n: i for i, n in enumerate(NODE_LABELS)}
    for e in g.edges:
        if e.source in pos and e.target in pos:
            assert pos[e.source] < pos[e.target], (
                f"배선은 {e.source} → {e.target}인데 화면 단계 목록은 "
                f"{e.target}를 먼저 그린다 — NODE_LABELS 순서를 graph.py에 맞출 것"
            )
