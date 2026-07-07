"""지출 심사 그래프 조립 (§4.1 메인 워크플로우).

START → load_context → intake_receipt → mismatch_gate
      ─(불일치)→ escalate
      ─(일치)→ [rule / budget / precedent 병렬] → guardrail_gate
      ─(차단)→ escalate
      ─(통과)→ adjudicate ─(저신뢰)→ escalate / ─(판정)→ execute_decision
      → callback → persist_precedent → END

checkpointer를 넘기면 각 노드 완료 시점 상태가 저장되어(§4.2), 워커가 죽어도
완료된 노드부터 재개된다 — thread_id=job_id로 잡 1건 = 스레드 1개 (app/worker.py 참고).
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.graphs.review.nodes.adjudicate import adjudicate, route_after_adjudicate
from app.graphs.review.nodes.budget_auditor import budget_auditor
from app.graphs.review.nodes.callback import callback
from app.graphs.review.nodes.escalate import escalate
from app.graphs.review.nodes.execute_decision import execute_decision
from app.graphs.review.nodes.guardrail_gate import guardrail_gate, route_after_guardrail
from app.graphs.review.nodes.intake_receipt import intake_receipt
from app.graphs.review.nodes.load_context import load_context
from app.graphs.review.nodes.mismatch_gate import AUDITORS, mismatch_gate, route_after_mismatch
from app.graphs.review.nodes.persist_precedent import persist_precedent
from app.graphs.review.nodes.precedent_auditor import precedent_auditor
from app.graphs.review.nodes.rule_auditor import rule_auditor
from app.graphs.review.state import ReviewState


def build_review_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(ReviewState)

    g.add_node("load_context", load_context)
    g.add_node("intake_receipt", intake_receipt)
    g.add_node("mismatch_gate", mismatch_gate)
    g.add_node("rule_auditor", rule_auditor)
    g.add_node("budget_auditor", budget_auditor)
    g.add_node("precedent_auditor", precedent_auditor)
    g.add_node("guardrail_gate", guardrail_gate)
    g.add_node("adjudicate", adjudicate)
    g.add_node("escalate", escalate)
    g.add_node("execute_decision", execute_decision)
    g.add_node("callback", callback)
    g.add_node("persist_precedent", persist_precedent)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "intake_receipt")
    g.add_edge("intake_receipt", "mismatch_gate")

    # 불일치 → escalate / 일치 → 3-심사관 fan-out (§3.2)
    # 라우터가 노드 리스트를 반환하면 해당 노드들이 병렬 실행된다
    g.add_conditional_edges("mismatch_gate", route_after_mismatch,
                            ["escalate", *AUDITORS])

    # fan-in → 결정적 가드레일
    for auditor in AUDITORS:
        g.add_edge(auditor, "guardrail_gate")

    g.add_conditional_edges("guardrail_gate", route_after_guardrail,
                            {"escalate": "escalate", "adjudicate": "adjudicate"})
    g.add_conditional_edges("adjudicate", route_after_adjudicate,
                            {"escalate": "escalate", "execute_decision": "execute_decision"})

    g.add_edge("escalate", "callback")
    g.add_edge("execute_decision", "callback")
    g.add_edge("callback", "persist_precedent")
    g.add_edge("persist_precedent", END)

    return g.compile(checkpointer=checkpointer)


# checkpointer 없는 기본 인스턴스 — 단위/스모크 테스트 전용(DB 불필요).
# 실제 워커는 app/worker.py에서 AsyncPostgresSaver를 붙여 별도로 컴파일한다.
review_graph = build_review_graph()
