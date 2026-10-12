"""Idempotent enterprise customer-service demo data seed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import (
    ApprovalBusinessType,
    ApprovalStatus,
    ApprovalTask,
    Customer,
    CustomerLevel,
    Department,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductStatus,
    Refund,
    RefundStatus,
    RiskLevel,
    Ticket,
    TicketPriority,
    TicketSource,
    TicketStatus,
    TicketType,
)
from yuxi.utils.datetime_utils import utc_now_naive


@dataclass(frozen=True)
class EnterpriseSeedResult:
    customers_created: int
    products_created: int
    orders_created: int
    refunds_created: int
    tickets_created: int
    approvals_created: int


CUSTOMER_SEED = (
    ("林晓", "linxiao@demo.local", "13800001001", CustomerLevel.VIP, RiskLevel.LOW),
    ("周航", "zhouhang@demo.local", "13800001002", CustomerLevel.STANDARD, RiskLevel.LOW),
    ("陈雨", "chenyu@demo.local", "13800001003", CustomerLevel.VIP, RiskLevel.MEDIUM),
    ("王宁", "wangning@demo.local", "13800001004", CustomerLevel.STANDARD, RiskLevel.LOW),
    ("赵敏", "zhaomin@demo.local", "13800001005", CustomerLevel.STANDARD, RiskLevel.HIGH),
)

PRODUCT_SEED = (
    ("NM-KEY-001", "Aurora 机械键盘", "智能办公", "699.00"),
    ("NM-MOU-002", "Flow 无线鼠标", "智能办公", "299.00"),
    ("NM-HUB-003", "Link Pro 扩展坞", "数码配件", "459.00"),
    ("NM-EAR-004", "Echo 降噪耳机", "音频设备", "899.00"),
    ("NM-CAM-005", "Vision 高清摄像头", "智能办公", "529.00"),
    ("NM-LGT-006", "Focus 屏幕挂灯", "办公照明", "239.00"),
    ("NM-SSD-007", "Vault 移动固态硬盘", "存储设备", "799.00"),
    ("NM-MIC-008", "Voice USB 麦克风", "音频设备", "399.00"),
    ("NM-PAD-009", "Glide 桌垫", "办公配件", "89.00"),
    ("NM-STD-010", "Lift 笔记本支架", "办公配件", "169.00"),
)


async def ensure_enterprise_demo_seed(tenant_name: str = "默认部门") -> EnterpriseSeedResult:
    """Create a stable demo dataset once for the selected department tenant."""
    counters = {"customers": 0, "products": 0, "orders": 0, "refunds": 0, "tickets": 0, "approvals": 0}
    now = utc_now_naive()

    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(select(Department).where(Department.name == tenant_name))
        department = result.scalar_one_or_none()
        if department is None:
            raise RuntimeError(f"Demo tenant department not found: {tenant_name}")
        tenant_id = department.id

        customers: list[Customer] = []
        for name, email, phone, level, risk_level in CUSTOMER_SEED:
            result = await session.execute(
                select(Customer).where(Customer.tenant_id == tenant_id, Customer.email == email)
            )
            customer = result.scalar_one_or_none()
            if customer is None:
                customer = Customer(
                    tenant_id=tenant_id,
                    name=name,
                    email=email,
                    phone=phone,
                    level=level,
                    risk_level=risk_level,
                )
                session.add(customer)
                await session.flush()
                counters["customers"] += 1
            customers.append(customer)

        products: list[Product] = []
        for sku, name, category, price in PRODUCT_SEED:
            result = await session.execute(
                select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
            )
            product = result.scalar_one_or_none()
            if product is None:
                product = Product(
                    tenant_id=tenant_id,
                    sku=sku,
                    name=name,
                    category=category,
                    price=Decimal(price),
                    status=ProductStatus.ACTIVE,
                )
                session.add(product)
                await session.flush()
                counters["products"] += 1
            products.append(product)

        statuses = (
            OrderStatus.PENDING,
            OrderStatus.PAID,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
            OrderStatus.REFUNDED,
        )
        orders: list[Order] = []
        for index in range(20):
            order_no = f"NM-DEMO-2026-{index + 1:04d}"
            result = await session.execute(
                select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no)
            )
            order = result.scalar_one_or_none()
            if order is None:
                customer = customers[index % len(customers)]
                product = products[index % len(products)]
                quantity = 1 + (index % 2)
                total_amount = (product.price * quantity).quantize(Decimal("0.01"))
                order_status = statuses[index % len(statuses)]
                created_at = now - timedelta(days=20 - index)
                is_paid = order_status != OrderStatus.PENDING
                is_shipped = order_status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}
                is_delivered = order_status in {OrderStatus.DELIVERED, OrderStatus.REFUNDED}
                order = Order(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    order_no=order_no,
                    status=order_status,
                    total_amount=total_amount,
                    paid_amount=total_amount if is_paid else Decimal("0.00"),
                    logistics_company="顺丰速运" if is_shipped else None,
                    tracking_no=f"SF-DEMO-{index + 1:08d}" if is_shipped else None,
                    created_at=created_at,
                    updated_at=created_at,
                    paid_at=created_at + timedelta(hours=1) if is_paid else None,
                    shipped_at=created_at + timedelta(days=1) if is_shipped else None,
                    delivered_at=created_at + timedelta(days=3) if is_delivered else None,
                )
                order.items = [
                    OrderItem(
                        tenant_id=tenant_id,
                        product_id=product.id,
                        quantity=quantity,
                        unit_price=product.price,
                    )
                ]
                session.add(order)
                await session.flush()
                counters["orders"] += 1
            orders.append(order)

        refund_specs = (
            (
                orders[4],
                "demo-refund-low",
                "商品体验不符合预期",
                RefundStatus.APPROVED,
                RiskLevel.LOW,
            ),
            (
                orders[7],
                "demo-refund-high",
                "申请高额退款",
                RefundStatus.PENDING_APPROVAL,
                RiskLevel.MEDIUM,
            ),
            (
                orders[14],
                "demo-refund-risk",
                "客户投诉并反馈疑似欺诈",
                RefundStatus.PENDING_APPROVAL,
                RiskLevel.HIGH,
            ),
        )
        pending_refunds: list[Refund] = []
        for order, key, reason, refund_status, risk_level in refund_specs:
            result = await session.execute(
                select(Refund).where(Refund.tenant_id == tenant_id, Refund.idempotency_key == key)
            )
            refund = result.scalar_one_or_none()
            if refund is None:
                refund = Refund(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    customer_id=order.customer_id,
                    amount=order.paid_amount,
                    reason=reason,
                    status=refund_status,
                    risk_level=risk_level,
                    requires_approval=refund_status == RefundStatus.PENDING_APPROVAL,
                    approved_by="system" if refund_status == RefundStatus.APPROVED else None,
                    idempotency_key=key,
                )
                session.add(refund)
                await session.flush()
                counters["refunds"] += 1
            if refund.status == RefundStatus.PENDING_APPROVAL:
                pending_refunds.append(refund)

        ticket_statuses = (
            TicketStatus.OPEN,
            TicketStatus.PROCESSING,
            TicketStatus.WAITING_CUSTOMER,
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        )
        ticket_types = (TicketType.INQUIRY, TicketType.LOGISTICS, TicketType.REFUND, TicketType.COMPLAINT)
        for index in range(8):
            key = f"demo-ticket-{index + 1}"
            result = await session.execute(
                select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.idempotency_key == key)
            )
            if result.scalar_one_or_none() is not None:
                continue
            order = orders[index]
            session.add(
                Ticket(
                    tenant_id=tenant_id,
                    customer_id=order.customer_id,
                    order_id=order.id,
                    type=ticket_types[index % len(ticket_types)],
                    priority=TicketPriority.HIGH if index in {2, 3} else TicketPriority.MEDIUM,
                    status=ticket_statuses[index % len(ticket_statuses)],
                    summary=f"演示工单 {index + 1}：订单 {order.order_no} 售后跟进",
                    assignee="cs_user" if index % 2 == 0 else None,
                    source=TicketSource.AGENT if index % 2 == 0 else TicketSource.MANUAL,
                    idempotency_key=key,
                )
            )
            counters["tickets"] += 1

        for refund in pending_refunds:
            key = f"refund:{refund.id}"
            result = await session.execute(
                select(ApprovalTask).where(
                    ApprovalTask.tenant_id == tenant_id,
                    ApprovalTask.idempotency_key == key,
                )
            )
            if result.scalar_one_or_none() is not None:
                continue
            session.add(
                ApprovalTask(
                    tenant_id=tenant_id,
                    business_type=ApprovalBusinessType.REFUND,
                    business_id=refund.id,
                    requested_by="demo_seed",
                    status=ApprovalStatus.PENDING,
                    idempotency_key=key,
                )
            )
            counters["approvals"] += 1

    return EnterpriseSeedResult(
        customers_created=counters["customers"],
        products_created=counters["products"],
        orders_created=counters["orders"],
        refunds_created=counters["refunds"],
        tickets_created=counters["tickets"],
        approvals_created=counters["approvals"],
    )
