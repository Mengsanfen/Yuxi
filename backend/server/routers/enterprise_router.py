from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.conversation_repository import ConversationRepository
from yuxi.repositories.enterprise_repository import EnterpriseRepository
from yuxi.repositories.enterprise_trace_repository import EnterpriseTraceRepository
from yuxi.services.enterprise_errors import (
    BusinessConflictError,
    BusinessError,
    BusinessRuleViolation,
    EnterpriseError,
    EnterpriseValidationError,
    EntityNotFoundError,
    ExternalServiceError,
    RetryableEnterpriseError,
)
from yuxi.services.enterprise_permission_service import (
    EnterpriseAction,
    EnterprisePermissionError,
    EnterprisePermissionService,
)
from yuxi.services.enterprise_service import EnterpriseService
from yuxi.services.enterprise_approval_recovery import attempt_approval_resume, enqueue_failed_approval_resume
from yuxi.services.enterprise_trace_service import build_trace_detail
from yuxi.storage.postgres.models_business import (
    ApprovalResume,
    ApprovalStatus,
    CustomerLevel,
    OrderStatus,
    ProductStatus,
    RiskLevel,
    TicketPriority,
    TicketSource,
    TicketStatus,
    TicketType,
    User,
)
from yuxi.utils import logger

enterprise = APIRouter(prefix="/enterprise", tags=["enterprise"])


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    level: CustomerLevel = CustomerLevel.STANDARD
    risk_level: RiskLevel = RiskLevel.LOW


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    status: ProductStatus = ProductStatus.ACTIVE


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10000)


class OrderCreate(BaseModel):
    customer_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=64)
    status: OrderStatus = OrderStatus.PAID
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)
    logistics_company: str | None = Field(default=None, max_length=100)
    tracking_no: str | None = Field(default=None, max_length=100)


class RefundCreate(BaseModel):
    order_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=64)


class TicketCreate(BaseModel):
    customer_id: int = Field(gt=0)
    order_id: int | None = Field(default=None, gt=0)
    type: TicketType
    priority: TicketPriority = TicketPriority.MEDIUM
    summary: str = Field(min_length=2, max_length=2000)
    assignee: str | None = Field(default=None, max_length=64)
    source: TicketSource = TicketSource.MANUAL
    idempotency_key: str = Field(min_length=8, max_length=64)


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class ApprovalReview(BaseModel):
    decision: Literal["approved", "rejected"]
    review_comment: str | None = Field(default=None, max_length=1000)


def _service(db: AsyncSession) -> EnterpriseService:
    return EnterpriseService(EnterpriseRepository(db))


async def _execute(operation):
    try:
        return await operation
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict()) from exc
    except BusinessConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_dict()) from exc
    except BusinessRuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.to_dict()) from exc
    except EnterprisePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict()) from exc
    except EnterpriseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.to_dict()) from exc
    except (RetryableEnterpriseError, ExternalServiceError) as exc:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE if exc.retryable else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=http_status, detail=exc.to_dict()) from exc
    except BusinessError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.to_dict()) from exc
    except EnterpriseError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.to_dict()) from exc
    except IntegrityError as exc:
        conflict = BusinessConflictError("数据已存在或违反唯一约束", code="ENTERPRISE_DATA_CONFLICT")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict.to_dict()) from exc


def _tenant_id(current_user: User) -> int:
    return int(current_user.department_id)


def _require_permission(current_user: User, action: EnterpriseAction) -> None:
    try:
        EnterprisePermissionService.require(current_user.role, action)
    except EnterprisePermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict()) from exc


def _trace_summary(detail: dict) -> dict:
    events = detail.get("events") or []
    latest_node = next((event for event in reversed(events) if event.get("node_name")), None)
    return {key: value for key, value in detail.items() if key != "events"} | {
        "current_node": latest_node.get("node_name") if latest_node else None,
        "current_agent": latest_node.get("agent_name") if latest_node else detail.get("agent_name"),
    }


@enterprise.get("/traces")
async def list_enterprise_traces(
    trace_status: str | None = Query(default=None, alias="status", max_length=32),
    risk_level: RiskLevel | None = Query(default=None),
    thread_id: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    repo = EnterpriseTraceRepository(db)
    tenant_id = _tenant_id(current_user)
    latest_events = await repo.list_latest_events(
        tenant_id,
        status=trace_status,
        risk_level=risk_level.value if risk_level else None,
        thread_id=thread_id,
        offset=offset,
        limit=limit,
    )
    events_by_trace = await repo.get_events_for_traces(
        tenant_id,
        [event.trace_id for event in latest_events],
    )
    items = []
    for latest_event in latest_events:
        detail = build_trace_detail(events_by_trace.get(latest_event.trace_id, []))
        if detail:
            items.append(_trace_summary(detail))
    total = await repo.count_traces(
        tenant_id,
        status=trace_status,
        risk_level=risk_level.value if risk_level else None,
        thread_id=thread_id,
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@enterprise.get("/traces/{trace_id}")
async def get_enterprise_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    detail = build_trace_detail(await EnterpriseTraceRepository(db).get_events(_tenant_id(current_user), trace_id))
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行追踪不存在")
    return detail


@enterprise.get("/threads/{thread_id}/trace")
async def get_enterprise_thread_trace(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    if current_user.role not in {"admin", "superadmin"}:
        conversation = await ConversationRepository(db).get_conversation_by_thread_id(thread_id)
        if conversation is None or conversation.user_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行追踪不存在")

    repo = EnterpriseTraceRepository(db)
    tenant_id = _tenant_id(current_user)
    trace_id = await repo.get_latest_trace_id_for_thread(tenant_id, thread_id)
    detail = build_trace_detail(await repo.get_events(tenant_id, trace_id)) if trace_id else None
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行追踪不存在")
    return detail


@enterprise.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    customer = await _execute(
        _service(db).create_customer(
            _tenant_id(current_user),
            actor_role=current_user.role,
            **payload.model_dump(),
        )
    )
    return customer.to_dict()


@enterprise.get("/customers")
async def list_customers(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    items = await _service(db).list_customers(_tenant_id(current_user), offset=offset, limit=limit)
    return {"items": [item.to_dict() for item in items]}


@enterprise.get("/customers/{customer_id}")
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    customer = await _execute(_service(db).get_customer(_tenant_id(current_user), customer_id))
    return customer.to_dict()


@enterprise.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    product = await _execute(
        _service(db).create_product(
            _tenant_id(current_user),
            actor_role=current_user.role,
            **payload.model_dump(),
        )
    )
    return product.to_dict()


@enterprise.get("/products")
async def list_products(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    items = await _service(db).list_products(_tenant_id(current_user), offset=offset, limit=limit)
    return {"items": [item.to_dict() for item in items]}


@enterprise.get("/products/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    product = await _execute(_service(db).get_product(_tenant_id(current_user), product_id))
    return product.to_dict()


@enterprise.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    order = await _execute(
        _service(db).create_order(
            _tenant_id(current_user),
            customer_id=payload.customer_id,
            order_no=payload.order_no,
            status=payload.status,
            items=[item.model_dump() for item in payload.items],
            logistics_company=payload.logistics_company,
            tracking_no=payload.tracking_no,
        )
    )
    return order.to_dict()


@enterprise.get("/orders")
async def list_orders(
    customer_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.ORDER_READ)
    items = await _service(db).list_orders(
        _tenant_id(current_user),
        customer_id=customer_id,
        offset=offset,
        limit=limit,
    )
    return {"items": [item.to_dict() for item in items]}


@enterprise.get("/orders/by-no/{order_no}")
async def get_order_by_no(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.ORDER_READ)
    order = await _execute(_service(db).get_order_by_no(_tenant_id(current_user), order_no))
    return order.to_dict()


@enterprise.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.ORDER_READ)
    order = await _execute(_service(db).get_order(_tenant_id(current_user), order_id))
    return order.to_dict()


@enterprise.get("/orders/{order_id}/logistics")
async def get_order_logistics(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.ORDER_READ)
    order = await _execute(_service(db).get_order(_tenant_id(current_user), order_id))
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "status": order.status.value,
        "logistics_company": order.logistics_company,
        "tracking_no": order.tracking_no,
        "shipped_at": order.to_dict(include_items=False)["shipped_at"],
        "delivered_at": order.to_dict(include_items=False)["delivered_at"],
    }


@enterprise.post("/refunds", status_code=status.HTTP_201_CREATED)
async def request_refund(
    payload: RefundCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    refund = await _execute(
        _service(db).request_refund(
            _tenant_id(current_user),
            **payload.model_dump(),
            requested_by=str(current_user.id),
            requester_role=current_user.role,
        )
    )
    return refund.to_dict()


@enterprise.get("/refunds")
async def list_refunds(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    items = await _service(db).list_refunds(_tenant_id(current_user), offset=offset, limit=limit)
    return {"items": [item.to_dict() for item in items]}


@enterprise.get("/refunds/{refund_id}")
async def get_refund(
    refund_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    refund = await _execute(_service(db).get_refund(_tenant_id(current_user), refund_id))
    return refund.to_dict()


@enterprise.post("/tickets", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    ticket = await _execute(
        _service(db).create_ticket(
            _tenant_id(current_user),
            requester_role=current_user.role,
            **payload.model_dump(),
        )
    )
    return ticket.to_dict()


@enterprise.get("/tickets")
async def list_tickets(
    customer_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    items = await _service(db).list_tickets(
        _tenant_id(current_user),
        customer_id=customer_id,
        offset=offset,
        limit=limit,
    )
    return {"items": [item.to_dict() for item in items]}


@enterprise.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    ticket = await _execute(_service(db).get_ticket(_tenant_id(current_user), ticket_id))
    return ticket.to_dict()


@enterprise.patch("/tickets/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    ticket = await _execute(
        _service(db).update_ticket_status(
            _tenant_id(current_user),
            ticket_id,
            payload.status,
            actor_role=current_user.role,
        )
    )
    return ticket.to_dict()


@enterprise.get("/approvals")
async def list_approval_tasks(
    approval_status: ApprovalStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.APPROVAL_REVIEW)
    service = _service(db)
    items = await service.list_approval_tasks(
        _tenant_id(current_user),
        status=approval_status,
        offset=offset,
        limit=limit,
    )
    resume_records = (
        list((await db.execute(select(ApprovalResume).where(
            ApprovalResume.tenant_id == _tenant_id(current_user),
            ApprovalResume.approval_task_id.in_([item.id for item in items]),
        ))).scalars())
        if items else []
    )
    resumes_by_task = {record.approval_task_id: record.to_dict() for record in resume_records}
    result = []
    for item in items:
        payload = item.to_dict()
        payload["resume"] = resumes_by_task.get(item.id)
        if item.business_type.value == "refund":
            try:
                payload["business"] = (await service.get_refund(_tenant_id(current_user), item.business_id)).to_dict()
            except EntityNotFoundError:
                payload["business"] = None
        result.append(payload)
    return {"items": result}


@enterprise.get("/approvals/{task_id}")
async def get_approval_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    _require_permission(current_user, EnterpriseAction.APPROVAL_REVIEW)
    task = await _execute(_service(db).get_approval_task(_tenant_id(current_user), task_id))
    resume = (
        await db.execute(select(ApprovalResume).where(
            ApprovalResume.tenant_id == _tenant_id(current_user),
            ApprovalResume.approval_task_id == task.id,
        ))
    ).scalar_one_or_none()
    return task.to_dict() | {"resume": resume.to_dict() if resume else None}


@enterprise.post("/approvals/{task_id}/review")
async def review_approval(
    task_id: int,
    payload: ApprovalReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    task = await _execute(
        _service(db).review_approval(
            _tenant_id(current_user),
            task_id=task_id,
            decision=ApprovalStatus(payload.decision),
            reviewer=current_user.user_id,
            reviewer_role=current_user.role,
            review_comment=payload.review_comment,
        )
    )
    await db.commit()
    resume_result = await attempt_approval_resume(task.id)
    if resume_result.get("attempted") and resume_result.get("status") != "finished":
        try:
            await enqueue_failed_approval_resume(task.id)
        except Exception as exc:
            logger.warning(f"Could not enqueue approval resume retry for task {task.id}: {exc}")
    return task.to_dict() | {"resume": resume_result}
