"""Define the state structures for the agent."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain.agents import AgentState


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Merge artifact file paths while preserving order and removing duplicates."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))


class BaseState(AgentState):
    """Shared state fields for Yuxi agents."""

    artifacts: Annotated[list[str], merge_artifacts]


class AgentStatePayload(TypedDict, total=False):
    """Serialized agent state payload consumed by the frontend."""

    todos: list
    files: dict
    artifacts: list[str]
    intent: str | None
    domain: str | None
    action: str | None
    ticket_type: str | None
    security_signals: list[str]
    intent_confidence: float | None
    risk_level: str | None
    order_no: str | None
    customer_id: int | None
    refund_amount: str | None
    ticket_id: int | None
    order_context: dict | None
    knowledge_result: dict | None
    refund_result: dict | None
    ticket_result: dict | None
    approval_result: dict | None
    quality_result: dict | None
    repair_count: int
