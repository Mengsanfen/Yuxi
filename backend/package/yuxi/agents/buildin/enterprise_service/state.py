from __future__ import annotations

from typing import Any

from yuxi.agents import BaseState


class EnterpriseWorkflowState(BaseState):
    """Serializable workflow state; PostgreSQL remains the business source of truth."""

    intent: str | None
    domain: str | None
    action: str | None
    ticket_type: str | None
    security_signals: list[str]
    intent_confidence: float | None
    risk_level: str | None
    requires_order_context: bool
    requires_knowledge: bool

    order_no: str | None
    customer_id: int | None
    refund_amount: str | None
    refund_reason: str | None
    ticket_id: int | None

    order_context: dict[str, Any] | None
    knowledge_result: dict[str, Any] | None
    refund_result: dict[str, Any] | None
    ticket_result: dict[str, Any] | None
    approval_result: dict[str, Any] | None

    quality_result: dict[str, Any] | None
    quality_call_count: int
    repair_count: int
    draft_answer: str | None
    final_answer: str | None
    tool_timings: list[dict[str, Any]]
