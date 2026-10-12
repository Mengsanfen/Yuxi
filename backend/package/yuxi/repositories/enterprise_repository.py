from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yuxi.storage.postgres.models_business import (
    ApprovalStatus,
    ApprovalTask,
    Customer,
    Order,
    OrderItem,
    Product,
    Refund,
    RefundStatus,
    Ticket,
)

EnterpriseModel = TypeVar("EnterpriseModel")


class EnterpriseRepository:
    """Tenant-scoped persistence for enterprise customer-service data."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    @staticmethod
    def _matches_unique_constraint(exc: IntegrityError, constraint_name: str) -> bool:
        candidates = (exc.orig, getattr(exc.orig, "__cause__", None))
        return any(
            getattr(candidate, "constraint_name", None) == constraint_name or constraint_name in str(candidate)
            for candidate in candidates
            if candidate is not None
        )

    async def _create_idempotent(
        self,
        entity: EnterpriseModel,
        *,
        constraint_name: str,
        load_replay: Callable[[], Awaitable[EnterpriseModel | None]],
    ) -> EnterpriseModel:
        try:
            async with self.db.begin_nested():
                self.db.add(entity)
                await self.db.flush()
            return entity
        except IntegrityError as exc:
            if not self._matches_unique_constraint(exc, constraint_name):
                raise
            replay = await load_replay()
            if replay is None:
                raise
            return replay

    async def create_customer(self, **data: Any) -> Customer:
        customer = Customer(**data)
        self.db.add(customer)
        await self.db.flush()
        return customer

    async def get_customer(self, tenant_id: int, customer_id: int) -> Customer | None:
        result = await self.db.execute(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_customer_by_email(self, tenant_id: int, email: str) -> Customer | None:
        result = await self.db.execute(select(Customer).where(Customer.tenant_id == tenant_id, Customer.email == email))
        return result.scalar_one_or_none()

    async def list_customers(self, tenant_id: int, *, offset: int, limit: int) -> list[Customer]:
        result = await self.db.execute(
            select(Customer)
            .where(Customer.tenant_id == tenant_id)
            .order_by(Customer.created_at.desc(), Customer.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_product(self, **data: Any) -> Product:
        product = Product(**data)
        self.db.add(product)
        await self.db.flush()
        return product

    async def get_product(self, tenant_id: int, product_id: int) -> Product | None:
        result = await self.db.execute(select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id))
        return result.scalar_one_or_none()

    async def get_product_by_sku(self, tenant_id: int, sku: str) -> Product | None:
        result = await self.db.execute(select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku))
        return result.scalar_one_or_none()

    async def get_products(self, tenant_id: int, product_ids: Sequence[int]) -> dict[int, Product]:
        result = await self.db.execute(
            select(Product).where(Product.tenant_id == tenant_id, Product.id.in_(product_ids))
        )
        return {product.id: product for product in result.scalars().all()}

    async def list_products(self, tenant_id: int, *, offset: int, limit: int) -> list[Product]:
        result = await self.db.execute(
            select(Product)
            .where(Product.tenant_id == tenant_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_order(self, *, items: list[dict[str, Any]], **data: Any) -> Order:
        order = Order(**data)
        order.items = [OrderItem(tenant_id=order.tenant_id, **item) for item in items]
        self.db.add(order)
        await self.db.flush()
        return order

    async def get_order(self, tenant_id: int, order_id: int) -> Order | None:
        result = await self.db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.tenant_id == tenant_id, Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_order_by_no(self, tenant_id: int, order_no: str) -> Order | None:
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.tenant_id == tenant_id, Order.order_no == order_no)
        )
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        tenant_id: int,
        *,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> list[Order]:
        stmt = select(Order).options(selectinload(Order.items)).where(Order.tenant_id == tenant_id)
        if customer_id is not None:
            stmt = stmt.where(Order.customer_id == customer_id)
        result = await self.db.execute(
            stmt.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def create_refund(self, **data: Any) -> Refund:
        refund = Refund(**data)
        try:
            return await self._create_idempotent(
                refund,
                constraint_name="uq_refunds_tenant_idempotency",
                load_replay=lambda: self.get_refund_by_idempotency_key(
                    data["tenant_id"],
                    data["idempotency_key"],
                ),
            )
        except IntegrityError as exc:
            if not self._matches_unique_constraint(exc, "uq_refunds_tenant_order_active"):
                raise
            existing = await self.get_active_refund_by_order(data["tenant_id"], data["order_id"])
            if existing is None:
                raise
            return existing

    async def get_refund(self, tenant_id: int, refund_id: int) -> Refund | None:
        result = await self.db.execute(select(Refund).where(Refund.tenant_id == tenant_id, Refund.id == refund_id))
        return result.scalar_one_or_none()

    async def get_refund_by_idempotency_key(self, tenant_id: int, idempotency_key: str) -> Refund | None:
        result = await self.db.execute(
            select(Refund).where(Refund.tenant_id == tenant_id, Refund.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def get_active_refund_by_order(self, tenant_id: int, order_id: int) -> Refund | None:
        result = await self.db.execute(
            select(Refund)
            .where(
                Refund.tenant_id == tenant_id,
                Refund.order_id == order_id,
                Refund.status != RefundStatus.REJECTED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_refunds(self, tenant_id: int, *, offset: int, limit: int) -> list[Refund]:
        result = await self.db.execute(
            select(Refund)
            .where(Refund.tenant_id == tenant_id)
            .order_by(Refund.created_at.desc(), Refund.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_ticket(self, **data: Any) -> Ticket:
        ticket = Ticket(**data)
        return await self._create_idempotent(
            ticket,
            constraint_name="uq_tickets_tenant_idempotency",
            load_replay=lambda: self.get_ticket_by_idempotency_key(
                data["tenant_id"],
                data["idempotency_key"],
            ),
        )

    async def get_ticket(self, tenant_id: int, ticket_id: int) -> Ticket | None:
        result = await self.db.execute(select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.id == ticket_id))
        return result.scalar_one_or_none()

    async def get_ticket_by_idempotency_key(self, tenant_id: int, idempotency_key: str) -> Ticket | None:
        result = await self.db.execute(
            select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def list_tickets(
        self,
        tenant_id: int,
        *,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> list[Ticket]:
        stmt = select(Ticket).where(Ticket.tenant_id == tenant_id)
        if customer_id is not None:
            stmt = stmt.where(Ticket.customer_id == customer_id)
        result = await self.db.execute(
            stmt.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def create_approval_task(self, **data: Any) -> ApprovalTask:
        task = ApprovalTask(**data)
        return await self._create_idempotent(
            task,
            constraint_name="uq_approval_tasks_tenant_idempotency",
            load_replay=lambda: self.get_approval_task_by_idempotency_key(
                data["tenant_id"],
                data["idempotency_key"],
            ),
        )

    async def get_approval_task_by_idempotency_key(
        self,
        tenant_id: int,
        idempotency_key: str,
    ) -> ApprovalTask | None:
        result = await self.db.execute(
            select(ApprovalTask).where(
                ApprovalTask.tenant_id == tenant_id,
                ApprovalTask.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_approval_task(
        self, tenant_id: int, task_id: int, *, for_update: bool = False
    ) -> ApprovalTask | None:
        stmt = select(ApprovalTask).where(ApprovalTask.tenant_id == tenant_id, ApprovalTask.id == task_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_approval_task_by_business(
        self,
        tenant_id: int,
        *,
        business_type,
        business_id: int,
    ) -> ApprovalTask | None:
        result = await self.db.execute(
            select(ApprovalTask).where(
                ApprovalTask.tenant_id == tenant_id,
                ApprovalTask.business_type == business_type,
                ApprovalTask.business_id == business_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_approval_tasks(
        self,
        tenant_id: int,
        *,
        status: ApprovalStatus | None,
        offset: int,
        limit: int,
    ) -> list[ApprovalTask]:
        stmt = select(ApprovalTask).where(ApprovalTask.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ApprovalTask.status == status)
        result = await self.db.execute(
            stmt.order_by(ApprovalTask.created_at.desc(), ApprovalTask.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())
