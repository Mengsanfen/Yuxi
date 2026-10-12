from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from yuxi.agents import BaseContext
from yuxi.agents.buildin.enterprise_service import nodes
from yuxi.agents.enterprise_schemas import EnterpriseIntent, EnterpriseIntentDecision
from yuxi.storage.postgres.models_business import TicketPriority, TicketStatus, TicketType


@pytest.mark.parametrize(
    ("domain", "action", "ticket_type", "expected_intent", "expected_node"),
    [
        ("knowledge", "policy", "unknown", EnterpriseIntent.POLICY_QUESTION, "knowledge"),
        ("order", "query", "unknown", EnterpriseIntent.ORDER_QUERY, "order"),
        ("order", "logistics", "unknown", EnterpriseIntent.LOGISTICS_QUERY, "order"),
        ("refund", "request", "unknown", EnterpriseIntent.REFUND_REQUEST, "refund_order"),
        ("ticket", "query", "unknown", EnterpriseIntent.TICKET_QUERY, "ticket"),
        ("ticket", "create", "after_sale", EnterpriseIntent.TICKET_QUERY, "ticket"),
        ("ticket", "create", "complaint", EnterpriseIntent.COMPLAINT, "ticket"),
        ("refund", "query", "unknown", EnterpriseIntent.UNKNOWN, "finalize"),
        ("unknown", "unknown", "unknown", EnterpriseIntent.UNKNOWN, "finalize"),
    ],
)
def test_domain_action_route_preserves_legacy_intent(domain, action, ticket_type, expected_intent, expected_node):
    decision = EnterpriseIntentDecision(
        domain=domain,
        action=action,
        ticket_type=ticket_type,
        confidence=0.9,
        risk_level="low",
    )

    assert decision.intent == expected_intent
    assert decision.model_dump(mode="json")["intent"] == expected_intent.value
    assert nodes.route_after_entities(decision.model_dump(mode="json")) == expected_node
    if ticket_type == "complaint":
        assert decision.risk_level == "high"


def test_legacy_intent_payload_maps_to_domain_action():
    decision = EnterpriseIntentDecision.model_validate(
        {
            "intent": "logistics_query",
            "confidence": 0.8,
            "risk_level": "low",
            "requires_order_context": True,
            "requires_knowledge": False,
        }
    )

    assert decision.domain == "order"
    assert decision.action == "logistics"
    assert decision.intent == EnterpriseIntent.LOGISTICS_QUERY


def test_refund_request_cannot_carry_ticket_creation_type():
    decision = EnterpriseIntentDecision(
        domain="refund",
        action="request",
        ticket_type="complaint",
        confidence=0.9,
        risk_level="high",
    )

    assert decision.ticket_type == "unknown"
    assert decision.intent == EnterpriseIntent.REFUND_REQUEST


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ticket_type", "expected_type", "expected_priority"),
    [
        ("after_sale", TicketType.AFTER_SALE, TicketPriority.MEDIUM),
        ("complaint", TicketType.COMPLAINT, TicketPriority.HIGH),
    ],
)
async def test_ticket_create_action_uses_business_type(monkeypatch, ticket_type, expected_type, expected_priority):
    calls = []

    class FakeSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    class FakeService:
        async def create_ticket(self, _tenant_id, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                id=12,
                status=TicketStatus.OPEN,
                to_dict=lambda: {"id": 12, "status": "open"},
            )

    monkeypatch.setattr(nodes.pg_manager, "get_async_session_context", FakeSession)
    monkeypatch.setattr(nodes, "EnterpriseRepository", lambda _session: object())
    monkeypatch.setattr(nodes, "EnterpriseService", lambda _repo: FakeService())
    runtime = SimpleNamespace(
        context=BaseContext(
            tenant_id=1,
            user_id="user-1",
            user_role="user",
            thread_id="thread-1",
            agent_id="EnterpriseServiceAgent",
        )
    )

    result = await nodes.ticket_node(
        {
            "messages": [HumanMessage(content="请创建售后工单")],
            "domain": "ticket",
            "action": "create",
            "ticket_type": ticket_type,
            "intent": "complaint" if ticket_type == "complaint" else "ticket_query",
            "customer_id": 12,
        },
        runtime,
    )

    assert calls[0]["type"] == expected_type
    assert calls[0]["priority"] == expected_priority
    assert result["ticket_result"]["id"] == 12
