from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from yuxi.agents.toolkits.enterprise import tools as enterprise_tools
from yuxi.services.enterprise_permission_service import (
    EnterpriseAction,
    EnterprisePermissionError,
    EnterprisePermissionService,
)
from yuxi.services.enterprise_service import EnterpriseService, EntityNotFoundError
from yuxi.storage.postgres.models_business import (
    ApprovalBusinessType,
    ApprovalStatus,
    OrderStatus,
    RefundStatus,
    TicketStatus,
)


def test_user_permission_matrix_allows_requests_but_denies_privileged_actions():
    assert EnterprisePermissionService.can("user", EnterpriseAction.ORDER_READ)
    assert EnterprisePermissionService.can("user", EnterpriseAction.REFUND_REQUEST)
    assert EnterprisePermissionService.can("user", EnterpriseAction.TICKET_CREATE)

    with pytest.raises(EnterprisePermissionError):
        EnterprisePermissionService.require("user", EnterpriseAction.APPROVAL_REVIEW)
    with pytest.raises(EnterprisePermissionError):
        EnterprisePermissionService.require("user", EnterpriseAction.TICKET_CLOSE)


@pytest.mark.asyncio
async def test_service_denies_user_closing_ticket_before_repository_access():
    repository = SimpleNamespace(get_ticket=AsyncMock())
    service = EnterpriseService(repository)

    with pytest.raises(EnterprisePermissionError, match="ticket.close"):
        await service.update_ticket_status(
            7,
            19,
            TicketStatus.CLOSED,
            actor_role="user",
        )

    repository.get_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_approve_refund():
    task = SimpleNamespace(
        status=ApprovalStatus.PENDING,
        business_type=ApprovalBusinessType.REFUND,
        business_id=23,
        reviewer=None,
        review_comment=None,
        reviewed_at=None,
        updated_at=None,
        thread_id=None,
        agent_id=None,
        requested_by=None,
    )
    refund = SimpleNamespace(
        status=RefundStatus.PENDING_APPROVAL,
        approved_by=None,
        updated_at=None,
        order_id=29,
    )
    order = SimpleNamespace(status=OrderStatus.DELIVERED, updated_at=None)
    repository = SimpleNamespace(
        get_approval_task=AsyncMock(return_value=task),
        get_refund=AsyncMock(return_value=refund),
        get_order=AsyncMock(return_value=order),
    )

    result = await EnterpriseService(repository).review_approval(
        7,
        task_id=11,
        decision=ApprovalStatus.APPROVED,
        reviewer="admin-1",
        reviewer_role="admin",
        review_comment="同意退款",
    )

    assert result is task
    assert task.status == ApprovalStatus.APPROVED
    assert refund.status == RefundStatus.APPROVED
    assert order.status == OrderStatus.REFUNDED


@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenant_order():
    repository = SimpleNamespace(get_order=AsyncMock(return_value=None))

    with pytest.raises(EntityNotFoundError, match="订单不存在"):
        await EnterpriseService(repository).get_order(tenant_id=7, order_id=29)

    repository.get_order.assert_awaited_once_with(7, 29)


@pytest.mark.asyncio
async def test_tool_returns_permission_error_for_denied_role():
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            tenant_id=7,
            user_id="42",
            user_role="user",
            agent_id="EnterpriseServiceAgent",
            agent_config_id=11,
            thread_id="thread-enterprise",
        )
    )

    result = await enterprise_tools.enterprise_close_ticket.coroutine(ticket_id=19, runtime=runtime)

    assert result == {
        "ok": False,
        "error": {
            "code": "ENTERPRISE_PERMISSION_DENIED",
            "type": "permission_error",
            "message": "角色 'user' 无权执行企业操作 'ticket.close'",
            "retryable": False,
        },
    }
