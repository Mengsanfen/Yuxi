from langgraph.graph import END, START, StateGraph

from yuxi.agents import BaseAgent

from .nodes import (
    classify_node,
    extract_entities_node,
    finalize_node,
    knowledge_node,
    order_node,
    quality_node,
    refund_node,
    repair_node,
    route_after_entities,
    route_after_quality,
    ticket_node,
)
from .state import EnterpriseWorkflowState


def build_enterprise_workflow(context_schema) -> StateGraph:
    workflow = StateGraph(
        EnterpriseWorkflowState,
        context_schema=context_schema,
    )

    workflow.add_node("classify", classify_node)
    workflow.add_node("extract_entities", extract_entities_node)
    workflow.add_node("knowledge", knowledge_node)
    workflow.add_node("order", order_node)
    workflow.add_node("refund_order", order_node)
    workflow.add_node("refund", refund_node)
    workflow.add_node("ticket", ticket_node)
    workflow.add_node("quality", quality_node)
    workflow.add_node("repair", repair_node)
    workflow.add_node("finalize", finalize_node)

    workflow.add_edge(START, "classify")
    workflow.add_edge("classify", "extract_entities")
    workflow.add_conditional_edges(
        "extract_entities",
        route_after_entities,
        {
            "knowledge": "knowledge",
            "order": "order",
            "refund_order": "refund_order",
            "ticket": "ticket",
            "finalize": "finalize",
        },
    )
    workflow.add_edge("knowledge", "quality")
    workflow.add_edge("order", "quality")
    workflow.add_edge("refund_order", "refund")
    workflow.add_edge("refund", "quality")
    workflow.add_edge("ticket", "quality")
    workflow.add_conditional_edges(
        "quality",
        route_after_quality,
        {"repair": "repair", "finalize": "finalize"},
    )
    workflow.add_edge("repair", "quality")
    workflow.add_edge("finalize", END)
    return workflow


class EnterpriseServiceAgent(BaseAgent):
    name = "企业智能客服"
    description = "基于 LangGraph 固定工作流处理企业知识问答、订单物流、退款审批和售后工单。"
    capabilities = ["enterprise_service", "human_approval", "knowledge_base"]
    metadata = {
        "examples": [
            "查询订单 NM-DEMO-2026-0008 的物流状态",
            "订单 NM-DEMO-2026-0008 申请退款 299 元",
            "为客户创建一个商品破损售后工单",
            "公司的退款政策是什么？",
        ]
    }

    async def get_graph(self, context=None, **kwargs):
        return build_enterprise_workflow(self.context_schema).compile(checkpointer=await self._get_checkpointer())
