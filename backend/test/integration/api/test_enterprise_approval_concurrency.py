from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import ApprovalTask, Customer, Order, OrderItem, Product, Refund

pytestmark = [pytest.mark.integration, pytest.mark.auth]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_decision", "second_decision"),
    [("approved", "rejected"), ("rejected", "approved"), ("approved", "approved"), ("rejected", "rejected")],
)
async def test_concurrent_approval_reviews_have_one_consistent_winner(
    test_client, admin_headers, first_decision, second_decision
):
    suffix = uuid.uuid4().hex[:10]
    created = {"customers": [], "products": [], "orders": [], "refunds": [], "approvals": []}

    try:
        customer_response = await test_client.post(
            "/api/enterprise/customers",
            headers=admin_headers,
            json={"name": f"审批竞争客户-{suffix}", "email": f"approval-race-{suffix}@pytest.local"},
        )
        assert customer_response.status_code == 201, customer_response.text
        customer = customer_response.json()
        created["customers"].append(customer["id"])

        product_response = await test_client.post(
            "/api/enterprise/products",
            headers=admin_headers,
            json={"sku": f"APPROVAL-RACE-{suffix}", "name": "审批竞争产品", "category": "测试", "price": "399.00"},
        )
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()
        created["products"].append(product["id"])

        order_response = await test_client.post(
            "/api/enterprise/orders",
            headers=admin_headers,
            json={
                "customer_id": customer["id"],
                "order_no": f"APPROVAL-RACE-{suffix}",
                "status": "delivered",
                "items": [{"product_id": product["id"], "quantity": 1}],
            },
        )
        assert order_response.status_code == 201, order_response.text
        order = order_response.json()
        created["orders"].append(order["id"])

        refund_response = await test_client.post(
            "/api/enterprise/refunds",
            headers=admin_headers,
            json={
                "order_id": order["id"],
                "amount": "399.00",
                "reason": "高额退款审批竞争测试",
                "idempotency_key": f"approval-race-{suffix}",
            },
        )
        assert refund_response.status_code == 201, refund_response.text
        refund = refund_response.json()
        created["refunds"].append(refund["id"])
        assert refund["status"] == "pending_approval"

        approvals_response = await test_client.get("/api/enterprise/approvals?status=pending", headers=admin_headers)
        assert approvals_response.status_code == 200, approvals_response.text
        approval = next(item for item in approvals_response.json()["items"] if item["business_id"] == refund["id"])
        created["approvals"].append(approval["id"])

        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.AsyncSession() as hold_session:
            await hold_session.execute(
                select(ApprovalTask.id).where(ApprovalTask.id == approval["id"]).with_for_update()
            )
            approve_call = asyncio.create_task(
                test_client.post(
                    f"/api/enterprise/approvals/{approval['id']}/review",
                    headers=admin_headers,
                    json={"decision": first_decision, "review_comment": "并发请求一"},
                )
            )
            reject_call = asyncio.create_task(
                test_client.post(
                    f"/api/enterprise/approvals/{approval['id']}/review",
                    headers=admin_headers,
                    json={"decision": second_decision, "review_comment": "并发请求二"},
                )
            )
            await asyncio.sleep(0.3)
            both_waited = not approve_call.done() and not reject_call.done()
            await hold_session.commit()
            responses = await asyncio.gather(approve_call, reject_call)

        assert both_waited
        assert sorted(response.status_code for response in responses) == [200, 409], [
            (response.status_code, response.text) for response in responses
        ]
        winner = next(response for response in responses if response.status_code == 200)
        loser = next(response for response in responses if response.status_code == 409)
        assert loser.json()["detail"]["code"] == "APPROVAL_ALREADY_REVIEWED"
        decision = winner.json()["status"]
        assert decision in {"approved", "rejected"}
        assert winner.json()["resume"] == {"attempted": False, "status": "not_linked"}

        task_result = await test_client.get(f"/api/enterprise/approvals/{approval['id']}", headers=admin_headers)
        refund_result = await test_client.get(f"/api/enterprise/refunds/{refund['id']}", headers=admin_headers)
        order_result = await test_client.get(f"/api/enterprise/orders/{order['id']}", headers=admin_headers)
        assert task_result.status_code == refund_result.status_code == order_result.status_code == 200
        assert task_result.json()["status"] == refund_result.json()["status"] == decision
        assert task_result.json()["review_comment"] == winner.json()["review_comment"]
        assert order_result.json()["status"] == ("refunded" if decision == "approved" else "delivered")
    finally:
        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            if created["approvals"]:
                await session.execute(delete(ApprovalTask).where(ApprovalTask.id.in_(created["approvals"])))
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
