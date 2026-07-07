"""컨텍스트 인덱싱 파이프라인 그래프 (§4.4-a).

EV(백엔드 이벤트: team_id·change_type·version) → fetch → chunk → embed → upsert

LLM 호출 없음 — embeddings만 사용. 메인 심사 그래프와 별개 그래프로 두어
재인덱싱이 진행 중인 팀의 심사 흐름에 영향을 주지 않는다(§4.4).
"""
from langgraph.graph import END, START, StateGraph

from app.graphs.indexing.nodes.chunk import chunk
from app.graphs.indexing.nodes.embed import embed
from app.graphs.indexing.nodes.fetch import fetch
from app.graphs.indexing.nodes.upsert import upsert
from app.graphs.indexing.state import IndexingState


def build_indexing_graph():
    g = StateGraph(IndexingState)
    g.add_node("fetch", fetch)
    g.add_node("chunk", chunk)
    g.add_node("embed", embed)
    g.add_node("upsert", upsert)

    g.add_edge(START, "fetch")
    g.add_edge("fetch", "chunk")
    g.add_edge("chunk", "embed")
    g.add_edge("embed", "upsert")
    g.add_edge("upsert", END)

    return g.compile()


indexing_graph = build_indexing_graph()
