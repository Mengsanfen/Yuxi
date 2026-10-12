from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import (
    ApprovalTask,
    Customer,
    Department,
    Order,
    OrderItem,
    Product,
    Refund,
    RefundStatus,
    Ticket,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


@pytest.mark.asyncio
async def test_enterprise_refund_approval_ticket_and_tenant_boundary(
    test_client,
    admin_headers,
    standard_user,
):
    suffix = uuid.uuid4().hex[:10]
    created = {
        "departments": [],
        "customers": [],
        "products": [],
        "orders": [],
        "refunds": [],
        "tickets": [],
        "approvals": [],
    }

    try:
        customer_response = await test_client.post(
            "/api/enterprise/customers",
            headers=admin_headers,
            json={
                "name": f"集成测试客户-{suffix}",
                "email": f"enterprise-{suffix}@pytest.local",
                "phone": f"139{suffix[:8]}",
                "level": "standard",
                "risk_level": "low",
            },
        )
        assert customer_response.status_code == 201, customer_response.text
        customer = customer_response.json()
        created["customers"].append(customer["id"])

        product_response = await test_client.post(
            "/api/enterprise/products",
            headers=admin_headers,
            json={
                "sku": f"PYTEST-{suffix}",
                "name": "集成测试产品",
                "category": "测试",
                "price": "399.00",
                "status": "active",
            },
        )
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()
        created["products"].append(product["id"])

        order_response = await test_client.post(
            "/api/enterprise/orders",
            headers=admin_headers,
            json={
                "customer_id": customer["id"],
                "order_no": f"PYTEST-{suffix}",
                "status": "delivered",
                "items": [{"product_id": product["id"], "quantity": 1}],
                "logistics_company": "测试物流",
                "tracking_no": f"TRACK-{suffix}",
            },
        )
        assert order_response.status_code == 201, order_response.text
        order = order_response.json()
        created["orders"].append(order["id"])
        assert order["tenant_id"] == customer["tenant_id"]
        assert order["total_amount"] == "399.00"

        refund_key = f"pytest-refund-{suffix}"
        refund_response = await test_client.post(
            "/api/enterprise/refunds",
            headers=admin_headers,
            json={
                "order_id": order["id"],
                "amount": "399.00",
                "reason": "高额退款集成测试",
                "idempotency_key": refund_key,
            },
        )
        assert refund_response.status_code == 201, refund_response.text
        refund = refund_response.json()
        created["refunds"].append(refund["id"])
        assert refund["status"] == "pending_approval"
        assert refund["requires_approval"] is True

        replay_response = await test_client.post(
            "/api/enterprise/refunds",
            headers=admin_headers,
            json={
                "order_id": order["id"],
                "amount": "399.00",
                "reason": "重复请求不应创建新记录",
                "idempotency_key": refund_key,
            },
        )
        assert replay_response.status_code == 201, replay_response.text
        assert replay_response.json()["id"] == refund["id"]

        approvals_response = await test_client.get(
            "/api/enterprise/approvals?status=pending",
            headers=admin_headers,
        )
        assert approvals_response.status_code == 200, approvals_response.text
        approval = next(item for item in approvals_response.json()["items"] if item["business_id"] == refund["id"])
        created["approvals"].append(approval["id"])
        assert approval["business"]["amount"] == "399.00"
        assert approval["business"]["risk_level"] == "medium"
        assert approval["business"]["reason"] == "高额退款集成测试"

        denied_review = await test_client.post(
            f"/api/enterprise/approvals/{approval['id']}/review",
            headers=standard_user["headers"],
            json={"decision": "approved", "review_comment": "普通用户越权审批"},
        )
        assert denied_review.status_code == 403
        assert denied_review.json()["detail"]["code"] == "ENTERPRISE_PERMISSION_DENIED"

        review_response = await test_client.post(
            f"/api/enterprise/approvals/{approval['id']}/review",
            headers=admin_headers,
            json={"decision": "approved", "review_comment": "集成测试审批通过"},
        )
        assert review_response.status_code == 200, review_response.text
        assert review_response.json()["status"] == "approved"
        assert review_response.json()["resume"] == {"attempted": False, "status": "not_linked"}

        ticket_response = await test_client.post(
            "/api/enterprise/tickets",
            headers=admin_headers,
            json={
                "customer_id": customer["id"],
                "order_id": order["id"],
                "type": "after_sale",
                "priority": "medium",
                "summary": "集成测试售后工单",
                "source": "api",
                "idempotency_key": f"pytest-ticket-{suffix}",
            },
        )
        assert ticket_response.status_code == 201, ticket_response.text
        ticket = ticket_response.json()
        created["tickets"].append(ticket["id"])

        denied_close = await test_client.patch(
            f"/api/enterprise/tickets/{ticket['id']}/status",
            headers=standard_user["headers"],
            json={"status": "closed"},
        )
        assert denied_close.status_code == 403
        assert denied_close.json()["detail"]["code"] == "ENTERPRISE_PERMISSION_DENIED"

        illegal_transition = await test_client.patch(
            f"/api/enterprise/tickets/{ticket['id']}/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert illegal_transition.status_code == 422
        assert illegal_transition.json()["detail"]["code"] == "TICKET_TRANSITION_NOT_ALLOWED"

        missing_customer = await test_client.get("/api/enterprise/customers/2147483647", headers=admin_headers)
        assert missing_customer.status_code == 404
        assert missing_customer.json()["detail"]["code"] == "CUSTOMER_NOT_FOUND"

        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            foreign_department = Department(name=f"pytest-tenant-{suffix}")
            session.add(foreign_department)
            await session.flush()
            foreign_customer = Customer(
                tenant_id=foreign_department.id,
                name="其他租户客户",
                email=f"foreign-{suffix}@pytest.local",
            )
            session.add(foreign_customer)
            await session.flush()
            created["departments"].append(foreign_department.id)
            created["customers"].append(foreign_customer.id)

        isolated_response = await test_client.get(
            f"/api/enterprise/customers/{foreign_customer.id}",
            headers=admin_headers,
        )
        assert isolated_response.status_code == 404
    finally:
        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            if created["approvals"]:
                await session.execute(delete(ApprovalTask).where(ApprovalTask.id.in_(created["approvals"])))
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
            if created["departments"]:
                await session.execute(delete(Department).where(Department.id.in_(created["departments"])))
        await pg_manager.async_engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_refund_ticket_and_approval_are_idempotent(test_client, admin_headers):
    suffix = uuid.uuid4().hex[:10]
    created = {
        "customers": [],
        "products": [],
        "orders": [],
        "refunds": [],
        "tickets": [],
        "approvals": [],
    }

    try:
        customer_response = await test_client.post(
            "/api/enterprise/customers",
            headers=admin_headers,
            json={
                "name": f"并发幂等客户-{suffix}",
                "email": f"concurrent-{suffix}@pytest.local",
            },
        )
        assert customer_response.status_code == 201, customer_response.text
        customer = customer_response.json()
        created["customers"].append(customer["id"])

        product_response = await test_client.post(
            "/api/enterprise/products",
            headers=admin_headers,
            json={
                "sku": f"CONCURRENT-{suffix}",
                "name": "并发幂等测试产品",
                "category": "测试",
                "price": "399.00",
            },
        )
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()
        created["products"].append(product["id"])

        order_response = await test_client.post(
            "/api/enterprise/orders",
            headers=admin_headers,
            json={
                "customer_id": customer["id"],
                "order_no": f"CONCURRENT-{suffix}",
                "status": "delivered",
                "items": [{"product_id": product["id"], "quantity": 1}],
            },
        )
        assert order_response.status_code == 201, order_response.text
        order = order_response.json()
        created["orders"].append(order["id"])

        refund_payload = {
            "order_id": order["id"],
            "amount": "399.00",
            "reason": "并发退款幂等测试",
            "idempotency_key": f"concurrent-refund-{suffix}",
        }
        refund_responses = await asyncio.gather(
            *(
                test_client.post(
                    "/api/enterprise/refunds",
                    headers=admin_headers,
                    json=refund_payload,
                )
                for _ in range(5)
            )
        )
        assert {response.status_code for response in refund_responses} == {201}
        refund_ids = {response.json()["id"] for response in refund_responses}
        assert len(refund_ids) == 1
        created["refunds"].extend(refund_ids)

        approvals_response = await test_client.get(
            "/api/enterprise/approvals?status=pending",
            headers=admin_headers,
        )
        assert approvals_response.status_code == 200, approvals_response.text
        approvals = [item for item in approvals_response.json()["items"] if item["business_id"] in refund_ids]
        assert len(approvals) == 1
        created["approvals"].append(approvals[0]["id"])

        distinct_order_response = await test_client.post(
            "/api/enterprise/orders",
            headers=admin_headers,
            json={
                "customer_id": customer["id"],
                "order_no": f"DISTINCT-KEYS-{suffix}",
                "status": "delivered",
                "items": [{"product_id": product["id"], "quantity": 1}],
            },
        )
        assert distinct_order_response.status_code == 201, distinct_order_response.text
        distinct_order = distinct_order_response.json()
        created["orders"].append(distinct_order["id"])

        distinct_responses = await asyncio.gather(
            *(
                test_client.post(
                    "/api/enterprise/refunds",
                    headers=admin_headers,
                    json={
                        "order_id": distinct_order["id"],
                        "amount": "399.00",
                        "reason": "不同 key 并发退款测试",
                        "idempotency_key": f"distinct-refund-{suffix}-{index}",
                    },
                )
                for index in range(5)
            )
        )
        assert {response.status_code for response in distinct_responses} == {201}
        distinct_refund_ids = {response.json()["id"] for response in distinct_responses}
        created["refunds"].extend(distinct_refund_ids)

        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            distinct_approval_ids = (
                await session.execute(
                    select(ApprovalTask.id).where(
                        ApprovalTask.tenant_id == distinct_order["tenant_id"],
                        ApprovalTask.business_id.in_(distinct_refund_ids),
                    )
                )
            ).scalars().all()
            created["approvals"].extend(distinct_approval_ids)
            active_refund_ids = (
                await session.execute(
                    select(Refund.id).where(
                        Refund.tenant_id == distinct_order["tenant_id"],
                        Refund.order_id == distinct_order["id"],
                        Refund.status != RefundStatus.REJECTED,
                    )
                )
            ).scalars().all()
        assert len(distinct_refund_ids) == 1
        assert len(distinct_approval_ids) == 1
        assert active_refund_ids == list(distinct_refund_ids)

        rejected_response = await test_client.post(
            f"/api/enterprise/approvals/{distinct_approval_ids[0]}/review",
            headers=admin_headers,
            json={"decision": "rejected", "review_comment": "重新申请回归测试"},
        )
        assert rejected_response.status_code == 200, rejected_response.text

        replacement_response = await test_client.post(
            "/api/enterprise/refunds",
            headers=admin_headers,
            json={
                "order_id": distinct_order["id"],
                "amount": "399.00",
                "reason": "拒绝后重新申请",
                "idempotency_key": f"replacement-refund-{suffix}",
            },
        )
        assert replacement_response.status_code == 201, replacement_response.text
        replacement_refund = replacement_response.json()
        created["refunds"].append(replacement_refund["id"])
        assert replacement_refund["id"] not in distinct_refund_ids
        assert replacement_refund["status"] == "pending_approval"

        async with pg_manager.get_async_session_context() as session:
            created["approvals"].extend(
                (
                    await session.execute(
                        select(ApprovalTask.id).where(ApprovalTask.business_id == replacement_refund["id"])
                    )
                ).scalars().all()
            )
            active_refund_ids = (
                await session.execute(
                    select(Refund.id).where(
                        Refund.tenant_id == distinct_order["tenant_id"],
                        Refund.order_id == distinct_order["id"],
                        Refund.status != RefundStatus.REJECTED,
                    )
                )
            ).scalars().all()
        assert active_refund_ids == [replacement_refund["id"]]

        ticket_payload = {
            "customer_id": customer["id"],
            "order_id": order["id"],
            "type": "after_sale",
            "priority": "medium",
            "summary": "并发工单幂等测试",
            "source": "api",
            "idempotency_key": f"concurrent-ticket-{suffix}",
        }
        ticket_responses = await asyncio.gather(
            *(
                test_client.post(
                    "/api/enterprise/tickets",
                    headers=admin_headers,
                    json=ticket_payload,
                )
                for _ in range(5)
            )
        )
        assert {response.status_code for response in ticket_responses} == {201}
        ticket_ids = {response.json()["id"] for response in ticket_responses}
        assert len(ticket_ids) == 1
        created["tickets"].extend(ticket_ids)
    finally:
        if not pg_manager._initialized:
            pg_manager.initialize()
        async with pg_manager.get_async_session_context() as session:
            if created["approvals"]:
                await session.execute(delete(ApprovalTask).where(ApprovalTask.id.in_(created["approvals"])))
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
