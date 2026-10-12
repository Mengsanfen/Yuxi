from __future__ import annotations

import hashlib
from decimal import Decimal

from langgraph.types import interrupt

from yuxi.repositories.enterprise_repository import EnterpriseRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import ApprovalStatus

from .enterprise_permission_service import EnterpriseRuntimeIdentity
from .enterprise_service import EnterpriseService


def build_enterprise_idempotency_key(prefix: str, *parts: object) -> str:
    raw = ":".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def build_refund_approval_payload(*, task, refund) -> dict:
    return {
        "source": "enterprise_refund_approval",
        "approval_task_id": task.id,
        "business_type": "refund",
        "business_id": refund.id,
        "risk_level": refund.risk_level.value,
        "amount": format(refund.amount, ".2f"),
        "questions": [
            {
                "question_id": f"approval-{task.id}",
                "question": f"退款 ¥{refund.amount:.2f} 已提交管理员审批，请等待审批中心处理。",
                "options": [],
                "multi_select": False,
                "allow_other": False,
                "operation": f"审批任务 #{task.id}",
            }
        ],
    }


async def execute_enterprise_refund(
    *,
    identity: EnterpriseRuntimeIdentity,
    order_no: str,
    amount: Decimal,
    reason: str,
    idempotency_key: str | None = None,
) -> dict:
    """Execute one idempotent refund and suspend the graph for human review when required."""

    request_key = idempotency_key or build_enterprise_idempotency_key(
        "agent-refund",
        identity.tenant_id,
        identity.thread_id,
        order_no,
        amount,
        reason,
    )

    async with pg_manager.get_async_session_context() as session:
        service = EnterpriseService(EnterpriseRepository(session))
        order = await service.get_order_by_no(identity.tenant_id, order_no)
        refund = await service.request_refund(
            identity.tenant_id,
            order_id=order.id,
            amount=amount,
            reason=reason,
            idempotency_key=request_key,
            requested_by=identity.user_id,
            requester_role=identity.user_role,
            thread_id=identity.thread_id,
            agent_id=identity.agent_id,
            agent_config_id=identity.agent_config_id,
        )
        if not refund.requires_approval:
            return {
                "ok": True,
                "data": refund.to_dict(),
                "order": order.to_dict(),
                "workflow": "auto_approved",
            }
        task = await service.get_refund_approval_task(identity.tenant_id, refund.id)
        payload = build_refund_approval_payload(task=task, refund=refund)
        task_id = task.id
        refund_id = refund.id

    while True:
        interrupt(payload)
        async with pg_manager.get_async_session_context() as session:
            service = EnterpriseService(EnterpriseRepository(session))
            task = await service.get_approval_task(identity.tenant_id, task_id)
            refund = await service.get_refund(identity.tenant_id, refund_id)
            if task.status != ApprovalStatus.PENDING:
                order = await service.get_order(identity.tenant_id, refund.order_id)
                return {
                    "ok": task.status == ApprovalStatus.APPROVED,
                    "data": refund.to_dict(),
                    "order": order.to_dict(),
                    "approval": task.to_dict(),
                    "workflow": "human_reviewed",
                }
