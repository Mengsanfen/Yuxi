from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import Customer, Order, OrderItem, Product, Refund, Ticket

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_low_value_refund_completes_once_and_creates_ticket(e2e_client, e2e_headers):
    suffix = uuid.uuid4().hex[:10]
    created = {"customers": [], "products": [], "orders": [], "refunds": [], "tickets": []}

    try:
        customer_response = await e2e_client.post(
            "/api/enterprise/customers",
            headers=e2e_headers,
            json={
                "name": f"E2E 客户-{suffix}",
                "email": f"e2e-{suffix}@pytest.local",
                "phone": f"137{suffix[:8]}",
            },
        )
        assert customer_response.status_code == 201, customer_response.text
        customer = customer_response.json()
        created["customers"].append(customer["id"])

        product_response = await e2e_client.post(
            "/api/enterprise/products",
            headers=e2e_headers,
            json={
                "sku": f"E2E-{suffix}",
                "name": "E2E 售后产品",
                "category": "测试",
                "price": "99.00",
            },
        )
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()
        created["products"].append(product["id"])

        order_response = await e2e_client.post(
            "/api/enterprise/orders",
            headers=e2e_headers,
            json={
                "customer_id": customer["id"],
                "order_no": f"E2E-{suffix}",
                "status": "delivered",
                "items": [{"product_id": product["id"], "quantity": 1}],
            },
        )
        assert order_response.status_code == 201, order_response.text
        order = order_response.json()
        created["orders"].append(order["id"])

        partial_response = await e2e_client.post(
            "/api/enterprise/refunds",
            headers=e2e_headers,
            json={
                "order_id": order["id"],
                "amount": "59.00",
                "reason": "商品轻微破损",
                "idempotency_key": f"e2e-partial-refund-{suffix}",
            },
        )
        assert partial_response.status_code == 422, partial_response.text
        assert partial_response.json()["detail"]["code"] == "PARTIAL_REFUND_NOT_SUPPORTED"
        assert "仅支持整单退款" in partial_response.json()["detail"]["message"]

        unchanged_order = await e2e_client.get(f"/api/enterprise/orders/{order['id']}", headers=e2e_headers)
        assert unchanged_order.status_code == 200, unchanged_order.text
        assert unchanged_order.json()["status"] == "delivered"
        refund_list = await e2e_client.get("/api/enterprise/refunds", headers=e2e_headers)
        assert refund_list.status_code == 200, refund_list.text
        assert not any(item["order_id"] == order["id"] for item in refund_list.json()["items"])

        refund_payload = {
            "order_id": order["id"],
            "amount": "99.00",
            "reason": "商品轻微破损",
            "idempotency_key": f"e2e-refund-{suffix}",
        }
        refund_response = await e2e_client.post(
            "/api/enterprise/refunds",
            headers=e2e_headers,
            json=refund_payload,
        )
        assert refund_response.status_code == 201, refund_response.text
        refund = refund_response.json()
        created["refunds"].append(refund["id"])
        assert refund["amount"] == order["paid_amount"] == "99.00"
        assert refund["status"] == "approved"
        assert refund["requires_approval"] is False

        replay_response = await e2e_client.post(
            "/api/enterprise/refunds",
            headers=e2e_headers,
            json=refund_payload,
        )
        assert replay_response.status_code == 201, replay_response.text
        assert replay_response.json()["id"] == refund["id"]

        updated_order = await e2e_client.get(
            f"/api/enterprise/orders/{order['id']}",
            headers=e2e_headers,
        )
        assert updated_order.status_code == 200, updated_order.text
        assert updated_order.json()["status"] == "refunded"

        ticket_payload = {
            "customer_id": customer["id"],
            "order_id": order["id"],
            "type": "after_sale",
            "priority": "medium",
            "summary": "退款完成后的售后回访",
            "source": "agent",
            "idempotency_key": f"e2e-ticket-{suffix}",
        }
        ticket_response = await e2e_client.post(
            "/api/enterprise/tickets",
            headers=e2e_headers,
            json=ticket_payload,
        )
        assert ticket_response.status_code == 201, ticket_response.text
        ticket = ticket_response.json()
        created["tickets"].append(ticket["id"])

        ticket_replay = await e2e_client.post(
            "/api/enterprise/tickets",
            headers=e2e_headers,
            json=ticket_payload,
        )
        assert ticket_replay.status_code == 201, ticket_replay.text
        assert ticket_replay.json()["id"] == ticket["id"]
    finally:
        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            if created["tickets"]:
                await session.execute(delete(Ticket).where(Ticket.id.in_(created["tickets"])))
            if created["refunds"]:
                await session.execute(delete(Refund).where(Refund.id.in_(created["refunds"])))
            if created["orders"]:
                await session.execute(delete(OrderItem).where(OrderItem.order_id.in_(created["orders"])))
                await session.execute(delete(Order).where(Order.id.in_(created["orders"])))
            if created["products"]:
                await session.execute(delete(Product).where(Product.id.in_(created["products"])))
            if created["customers"]:
                await session.execute(delete(Customer).where(Customer.id.in_(created["customers"])))
        await pg_manager.async_engine.dispose()
