from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from yuxi.repositories.enterprise_repository import EnterpriseRepository
from yuxi.storage.postgres.models_business import (
    ApprovalBusinessType,
    ApprovalResume,
    ApprovalStatus,
    Customer,
    Order,
    OrderStatus,
    ProductStatus,
    Refund,
    RefundStatus,
    RiskLevel,
    Ticket,
    TicketStatus,
)
from yuxi.utils.datetime_utils import utc_now_naive

from .enterprise_errors import (
    BusinessConflictError,
    BusinessRuleViolation,
    EnterpriseError,
    EntityNotFoundError,
)
from .enterprise_permission_service import EnterpriseAction, EnterprisePermissionService

AUTO_REFUND_LIMIT = Decimal("100.00")
REFUND_WINDOW_DAYS = 30


EnterpriseServiceError = EnterpriseError


@dataclass(frozen=True)
class RefundDecision:
    requires_approval: bool
    risk_level: RiskLevel
    status: RefundStatus


class RefundPolicyService:
    """Deterministic refund policy kept outside prompts and agent decisions."""

    RISK_REASON_MARKERS = ("欺诈", "诈骗", "投诉", "fraud", "complaint")

    @classmethod
    def evaluate(
        cls,
        *,
        amount: Decimal,
        paid_amount: Decimal,
        order_status: OrderStatus,
        customer_risk_level: RiskLevel,
        reason: str,
        delivered_at=None,
        now=None,
    ) -> RefundDecision:
        amount = Decimal(amount)
        paid_amount = Decimal(paid_amount)
        now = now or utc_now_naive()

        if amount <= 0:
            raise BusinessRuleViolation("退款金额必须大于 0", code="REFUND_AMOUNT_INVALID")
        if amount > paid_amount:
            raise BusinessRuleViolation("退款金额不能超过订单实付金额", code="REFUND_AMOUNT_EXCEEDS_PAID")
        if amount < paid_amount:
            raise BusinessRuleViolation(
                "当前 Demo 仅支持整单退款，请按订单实际可退款金额提交退款。",
                code="PARTIAL_REFUND_NOT_SUPPORTED",
            )
        if order_status in {OrderStatus.PENDING, OrderStatus.CANCELLED}:
            raise BusinessRuleViolation("当前订单状态不允许退款", code="REFUND_STATUS_NOT_ALLOWED")
        if order_status == OrderStatus.REFUNDED:
            raise BusinessConflictError("订单已退款", code="ORDER_ALREADY_REFUNDED")
        if delivered_at and now - delivered_at > timedelta(days=REFUND_WINDOW_DAYS):
            raise BusinessRuleViolation(
                f"订单已超过 {REFUND_WINDOW_DAYS} 天退款期限",
                code="REFUND_WINDOW_EXPIRED",
            )

        normalized_reason = reason.casefold()
        risky_reason = any(marker in normalized_reason for marker in cls.RISK_REASON_MARKERS)
        high_risk = customer_risk_level == RiskLevel.HIGH or risky_reason
        requires_approval = high_risk or amount > AUTO_REFUND_LIMIT
        risk_level = RiskLevel.HIGH if high_risk else RiskLevel.MEDIUM if requires_approval else RiskLevel.LOW
        status = RefundStatus.PENDING_APPROVAL if requires_approval else RefundStatus.APPROVED
        return RefundDecision(requires_approval=requires_approval, risk_level=risk_level, status=status)


class TicketStateMachine:
    ALLOWED_TRANSITIONS = {
        TicketStatus.OPEN: {TicketStatus.PROCESSING, TicketStatus.RESOLVED},
        TicketStatus.PROCESSING: {TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED},
        TicketStatus.WAITING_CUSTOMER: {TicketStatus.PROCESSING, TicketStatus.RESOLVED},
        TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.PROCESSING},
        TicketStatus.CLOSED: set(),
    }

    @classmethod
    def validate(cls, current: TicketStatus, target: TicketStatus) -> None:
        if current == target:
            return
        if target not in cls.ALLOWED_TRANSITIONS[current]:
            raise BusinessRuleViolation(
                f"非法工单状态流转: {current.value} -> {target.value}",
                code="TICKET_TRANSITION_NOT_ALLOWED",
            )


class EnterpriseService:
    def __init__(self, repository: EnterpriseRepository):
        self.repository = repository

    async def create_customer(self, tenant_id: int, *, actor_role: str, **data: Any) -> Customer:
        EnterprisePermissionService.require(actor_role, EnterpriseAction.CUSTOMER_MANAGE)
        return await self.repository.create_customer(tenant_id=tenant_id, **data)

    async def get_customer(self, tenant_id: int, customer_id: int) -> Customer:
        customer = await self.repository.get_customer(tenant_id, customer_id)
        if customer is None:
            raise EntityNotFoundError("客户不存在", code="CUSTOMER_NOT_FOUND")
        return customer

    async def list_customers(self, tenant_id: int, *, offset: int, limit: int) -> list[Customer]:
        return await self.repository.list_customers(tenant_id, offset=offset, limit=limit)

    async def create_product(self, tenant_id: int, *, actor_role: str, **data: Any):
        EnterprisePermissionService.require(actor_role, EnterpriseAction.PRODUCT_MANAGE)
        return await self.repository.create_product(tenant_id=tenant_id, **data)

    async def get_product(self, tenant_id: int, product_id: int):
        product = await self.repository.get_product(tenant_id, product_id)
        if product is None:
            raise EntityNotFoundError("产品不存在", code="PRODUCT_NOT_FOUND")
        return product

    async def list_products(self, tenant_id: int, *, offset: int, limit: int):
        return await self.repository.list_products(tenant_id, offset=offset, limit=limit)

    async def create_order(
        self,
        tenant_id: int,
        *,
        customer_id: int,
        order_no: str,
        status: OrderStatus,
        items: list[dict[str, int]],
        logistics_company: str | None = None,
        tracking_no: str | None = None,
    ) -> Order:
        await self.get_customer(tenant_id, customer_id)
        if not items:
            raise BusinessRuleViolation("订单至少需要一个商品", code="ORDER_ITEMS_REQUIRED")

        product_ids = [item["product_id"] for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise BusinessRuleViolation("同一商品不能重复出现在订单明细中", code="ORDER_ITEM_DUPLICATED")
        if any(item["quantity"] <= 0 for item in items):
            raise BusinessRuleViolation("商品数量必须大于 0", code="ORDER_ITEM_QUANTITY_INVALID")

        products = await self.repository.get_products(tenant_id, product_ids)
        if len(products) != len(product_ids):
            raise EntityNotFoundError("订单包含不存在的产品", code="ORDER_PRODUCT_NOT_FOUND")
        if any(product.status != ProductStatus.ACTIVE for product in products.values()):
            raise BusinessRuleViolation("订单包含已下架产品", code="ORDER_PRODUCT_INACTIVE")

        order_items = [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "unit_price": products[item["product_id"]].price,
            }
            for item in items
        ]
        total_amount = sum(
            (Decimal(item["unit_price"]) * item["quantity"] for item in order_items),
            start=Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        now = utc_now_naive()
        is_paid = status in {OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}
        return await self.repository.create_order(
            tenant_id=tenant_id,
            customer_id=customer_id,
            order_no=order_no,
            status=status,
            total_amount=total_amount,
            paid_amount=total_amount if is_paid else Decimal("0.00"),
            logistics_company=logistics_company,
            tracking_no=tracking_no,
            paid_at=now if is_paid else None,
            shipped_at=now if status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED} else None,
            delivered_at=now if status in {OrderStatus.DELIVERED, OrderStatus.REFUNDED} else None,
            items=order_items,
        )

    async def get_order(self, tenant_id: int, order_id: int) -> Order:
        order = await self.repository.get_order(tenant_id, order_id)
        if order is None:
            raise EntityNotFoundError("订单不存在", code="ORDER_NOT_FOUND")
        return order

    async def get_order_by_no(self, tenant_id: int, order_no: str) -> Order:
        order = await self.repository.get_order_by_no(tenant_id, order_no)
        if order is None:
            raise EntityNotFoundError("订单不存在", code="ORDER_NOT_FOUND")
        return order

    async def list_orders(
        self,
        tenant_id: int,
        *,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> list[Order]:
        return await self.repository.list_orders(
            tenant_id,
            customer_id=customer_id,
            offset=offset,
            limit=limit,
        )

    async def request_refund(
        self,
        tenant_id: int,
        *,
        order_id: int,
        amount: Decimal,
        reason: str,
        idempotency_key: str,
        requested_by: str,
        requester_role: str,
        thread_id: str | None = None,
        agent_id: str | None = None,
        agent_config_id: int | None = None,
    ) -> Refund:
        EnterprisePermissionService.require(requester_role, EnterpriseAction.REFUND_REQUEST)
        replay = await self.repository.get_refund_by_idempotency_key(tenant_id, idempotency_key)
        if replay is not None:
            return replay

        order = await self.get_order(tenant_id, order_id)
        existing = await self.repository.get_active_refund_by_order(tenant_id, order_id)
        if existing is not None:
            return existing

        customer = await self.get_customer(tenant_id, order.customer_id)
        decision = RefundPolicyService.evaluate(
            amount=amount,
            paid_amount=order.paid_amount,
            order_status=order.status,
            customer_risk_level=customer.risk_level,
            reason=reason,
            delivered_at=order.delivered_at,
        )
        refund = await self.repository.create_refund(
            tenant_id=tenant_id,
            order_id=order.id,
            customer_id=order.customer_id,
            amount=amount,
            reason=reason,
            status=decision.status,
            risk_level=decision.risk_level,
            requires_approval=decision.requires_approval,
            approved_by=None if decision.requires_approval else "system",
            idempotency_key=idempotency_key,
        )
        if refund.idempotency_key != idempotency_key:
            return refund
        if decision.requires_approval:
            await self.repository.create_approval_task(
                tenant_id=tenant_id,
                business_type=ApprovalBusinessType.REFUND,
                business_id=refund.id,
                requested_by=requested_by,
                status=ApprovalStatus.PENDING,
                idempotency_key=f"refund:{refund.id}",
                thread_id=thread_id,
                agent_id=agent_id,
                agent_config_id=agent_config_id,
            )
        else:
            order.status = OrderStatus.REFUNDED
            order.updated_at = utc_now_naive()
        return refund

    async def get_refund(self, tenant_id: int, refund_id: int) -> Refund:
        refund = await self.repository.get_refund(tenant_id, refund_id)
        if refund is None:
            raise EntityNotFoundError("退款记录不存在", code="REFUND_NOT_FOUND")
        return refund

    async def list_refunds(self, tenant_id: int, *, offset: int, limit: int) -> list[Refund]:
        return await self.repository.list_refunds(tenant_id, offset=offset, limit=limit)

    async def create_ticket(
        self,
        tenant_id: int,
        *,
        customer_id: int,
        order_id: int | None,
        idempotency_key: str,
        requester_role: str,
        **data: Any,
    ) -> Ticket:
        EnterprisePermissionService.require(requester_role, EnterpriseAction.TICKET_CREATE)
        replay = await self.repository.get_ticket_by_idempotency_key(tenant_id, idempotency_key)
        if replay is not None:
            return replay
        await self.get_customer(tenant_id, customer_id)
        if order_id is not None:
            order = await self.get_order(tenant_id, order_id)
            if order.customer_id != customer_id:
                raise BusinessRuleViolation(
                    "工单客户与订单客户不一致",
                    code="TICKET_ORDER_CUSTOMER_MISMATCH",
                )
        return await self.repository.create_ticket(
            tenant_id=tenant_id,
            customer_id=customer_id,
            order_id=order_id,
            idempotency_key=idempotency_key,
            **data,
        )

    async def get_ticket(self, tenant_id: int, ticket_id: int) -> Ticket:
        ticket = await self.repository.get_ticket(tenant_id, ticket_id)
        if ticket is None:
            raise EntityNotFoundError("工单不存在", code="TICKET_NOT_FOUND")
        return ticket

    async def list_tickets(
        self,
        tenant_id: int,
        *,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> list[Ticket]:
        return await self.repository.list_tickets(
            tenant_id,
            customer_id=customer_id,
            offset=offset,
            limit=limit,
        )

    async def update_ticket_status(
        self,
        tenant_id: int,
        ticket_id: int,
        status: TicketStatus,
        *,
        actor_role: str,
    ) -> Ticket:
        action = EnterpriseAction.TICKET_CLOSE if status == TicketStatus.CLOSED else EnterpriseAction.TICKET_UPDATE
        EnterprisePermissionService.require(actor_role, action)
        ticket = await self.get_ticket(tenant_id, ticket_id)
        TicketStateMachine.validate(ticket.status, status)
        ticket.status = status
        ticket.updated_at = utc_now_naive()
        return ticket

    async def get_approval_task(self, tenant_id: int, task_id: int):
        task = await self.repository.get_approval_task(tenant_id, task_id)
        if task is None:
            raise EntityNotFoundError("审批任务不存在", code="APPROVAL_NOT_FOUND")
        return task

    async def get_refund_approval_task(self, tenant_id: int, refund_id: int):
        task = await self.repository.get_approval_task_by_business(
            tenant_id,
            business_type=ApprovalBusinessType.REFUND,
            business_id=refund_id,
        )
        if task is None:
            raise EntityNotFoundError("退款审批任务不存在", code="REFUND_APPROVAL_NOT_FOUND")
        return task

    async def list_approval_tasks(
        self,
        tenant_id: int,
        *,
        status: ApprovalStatus | None,
        offset: int,
        limit: int,
    ):
        return await self.repository.list_approval_tasks(
            tenant_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def review_approval(
        self,
        tenant_id: int,
        *,
        task_id: int,
        decision: ApprovalStatus,
        reviewer: str,
        reviewer_role: str,
        review_comment: str | None,
    ):
        EnterprisePermissionService.require(reviewer_role, EnterpriseAction.APPROVAL_REVIEW)
        if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise BusinessRuleViolation(
                "审批决定只能是 approved 或 rejected",
                code="APPROVAL_DECISION_INVALID",
            )
        task = await self.repository.get_approval_task(tenant_id, task_id, for_update=True)
        if task is None:
            raise EntityNotFoundError("审批任务不存在", code="APPROVAL_NOT_FOUND")
        if task.status != ApprovalStatus.PENDING:
            raise BusinessConflictError("审批任务已处理", code="APPROVAL_ALREADY_REVIEWED")
        if task.business_type != ApprovalBusinessType.REFUND:
            raise BusinessRuleViolation("暂不支持该业务类型的审批", code="APPROVAL_TYPE_NOT_SUPPORTED")

        refund = await self.get_refund(tenant_id, task.business_id)
        refund.status = RefundStatus.APPROVED if decision == ApprovalStatus.APPROVED else RefundStatus.REJECTED
        refund.approved_by = reviewer
        refund.updated_at = utc_now_naive()
        if decision == ApprovalStatus.APPROVED:
            order = await self.get_order(tenant_id, refund.order_id)
            order.status = OrderStatus.REFUNDED
            order.updated_at = utc_now_naive()

        task.status = decision
        task.reviewer = reviewer
        task.review_comment = review_comment
        task.reviewed_at = utc_now_naive()
        task.updated_at = task.reviewed_at
        if task.thread_id and task.agent_id and task.requested_by:
            self.repository.db.add(ApprovalResume(approval_task_id=task.id, tenant_id=tenant_id))
        return task
