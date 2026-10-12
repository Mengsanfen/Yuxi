from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from yuxi.agents import BaseContext
from yuxi.agents.buildin.enterprise_service import graph as enterprise_graph
from yuxi.agents.buildin.enterprise_service.nodes import _tool_exchange
from yuxi.evaluation.enterprise.metrics import build_case_result
from yuxi.evaluation.enterprise.schemas import (
    EnterpriseEvalCase,
    EnterpriseEvalObservation,
    EnterpriseToolExecution,
)


@pytest.mark.asyncio
async def test_offline_graph_eval_smoke_routes_order_through_quality(monkeypatch):
    async def classify(_state, runtime):
        del runtime
        return {"intent": "order_query", "domain": "order", "action": "query"}

    async def extract(_state, runtime):
        del runtime
        return {"order_no": "NM-SMOKE-001"}

    async def order(_state, runtime):
        del runtime
        result = {"ok": True, "data": {"id": 1, "order_no": "NM-SMOKE-001", "status": "shipped"}}
        return {
            "order_context": result["data"],
            "draft_answer": "订单 NM-SMOKE-001 已发货。",
            "messages": _tool_exchange("enterprise_get_order_by_no", {"order_no": "NM-SMOKE-001"}, result),
        }

    monkeypatch.setattr(enterprise_graph, "classify_node", classify)
    monkeypatch.setattr(enterprise_graph, "extract_entities_node", extract)
    monkeypatch.setattr(enterprise_graph, "order_node", order)
    workflow = enterprise_graph.build_enterprise_workflow(BaseContext).compile()
    state = await workflow.ainvoke(
        {"messages": [HumanMessage(content="查询订单 NM-SMOKE-001")]}, context=BaseContext()
    )

    observation = EnterpriseEvalObservation(
        actual_intent=state["intent"],
        actual_domain=state["domain"],
        actual_action=state["action"],
        tool_executions=[EnterpriseToolExecution(name="enterprise_get_order_by_no", status="success")],
        quality_passed=state["quality_result"]["passed"],
        final_status="completed",
        final_answer=state["final_answer"],
    )
    case = EnterpriseEvalCase(
        id="offline-order-smoke",
        category="CI smoke",
        query="查询订单 NM-SMOKE-001",
        expected_intent="order_query",
        expected_domain="order",
        expected_action="query",
        expected_tools=["enterprise_get_order_by_no"],
        expected_final_status="completed",
        must_contain=["已发货"],
    )
    assert build_case_result(case, observation).passed is True
