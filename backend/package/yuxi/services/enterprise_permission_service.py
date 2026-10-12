from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .enterprise_errors import EnterprisePermissionError, EnterpriseValidationError


class EnterpriseAction(StrEnum):
    ORDER_READ = "order.read"
    REFUND_REQUEST = "refund.request"
    TICKET_CREATE = "ticket.create"
    TICKET_UPDATE = "ticket.update"
    TICKET_CLOSE = "ticket.close"
    APPROVAL_REVIEW = "approval.review"
    CUSTOMER_MANAGE = "customer.manage"
    PRODUCT_MANAGE = "product.manage"


class EnterprisePermissionService:
    _USER_ACTIONS = frozenset(
        {
            EnterpriseAction.ORDER_READ,
            EnterpriseAction.REFUND_REQUEST,
            EnterpriseAction.TICKET_CREATE,
        }
    )
    _ADMIN_ACTIONS = _USER_ACTIONS | frozenset(
        {
            EnterpriseAction.TICKET_UPDATE,
            EnterpriseAction.TICKET_CLOSE,
            EnterpriseAction.APPROVAL_REVIEW,
            EnterpriseAction.CUSTOMER_MANAGE,
            EnterpriseAction.PRODUCT_MANAGE,
        }
    )
    _ROLE_ACTIONS = {
        "user": _USER_ACTIONS,
        "admin": _ADMIN_ACTIONS,
        "superadmin": _ADMIN_ACTIONS,
    }

    @classmethod
    def can(cls, role: str, action: EnterpriseAction) -> bool:
        return action in cls._ROLE_ACTIONS.get(role.casefold(), frozenset())

    @classmethod
    def require(cls, role: str, action: EnterpriseAction) -> None:
        normalized_role = role.casefold()
        if not cls.can(normalized_role, action):
            raise EnterprisePermissionError(
                f"角色 {normalized_role!r} 无权执行企业操作 {action.value!r}",
                role=normalized_role,
                action=action.value,
            )


@dataclass(frozen=True)
class EnterpriseRuntimeIdentity:
    tenant_id: int
    user_id: str
    user_role: str
    agent_id: str
    agent_config_id: int | None
    thread_id: str

    @classmethod
    def from_context(cls, context: object) -> EnterpriseRuntimeIdentity:
        tenant_id = getattr(context, "tenant_id", None)
        user_id = getattr(context, "user_id", None)
        thread_id = getattr(context, "thread_id", None)
        if tenant_id is None:
            raise EnterpriseValidationError("当前运行上下文缺少 tenant_id", code="TENANT_CONTEXT_REQUIRED")
        if not user_id or not thread_id:
            raise EnterpriseValidationError("当前运行上下文缺少用户或线程信息", code="RUNTIME_IDENTITY_REQUIRED")
        return cls(
            tenant_id=int(tenant_id),
            user_id=str(user_id),
            user_role=str(getattr(context, "user_role", None) or "user").casefold(),
            agent_id=str(getattr(context, "agent_id", None) or "EnterpriseServiceAgent"),
            agent_config_id=getattr(context, "agent_config_id", None),
            thread_id=str(thread_id),
        )
