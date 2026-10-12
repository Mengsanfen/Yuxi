from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class EnterpriseError(Exception):
    code = "ENTERPRISE_ERROR"
    error_type = "enterprise_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or type(self).code
        self.retryable = type(self).retryable if retryable is None else retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "type": self.error_type,
            "message": self.message,
            "retryable": self.retryable,
        }


class BusinessError(EnterpriseError):
    code = "BUSINESS_ERROR"
    error_type = "business_error"


class EntityNotFoundError(BusinessError):
    code = "ENTITY_NOT_FOUND"
    error_type = "not_found_error"


class BusinessRuleViolation(BusinessError):
    code = "BUSINESS_RULE_VIOLATION"


class BusinessConflictError(BusinessError):
    code = "BUSINESS_CONFLICT"
    error_type = "conflict_error"


class EnterprisePermissionError(EnterpriseError, PermissionError):
    code = "ENTERPRISE_PERMISSION_DENIED"
    error_type = "permission_error"

    def __init__(
        self,
        message: str,
        *,
        role: str | None = None,
        action: str | None = None,
        code: str | None = None,
    ):
        super().__init__(message, code=code)
        self.role = role
        self.action = action


class EnterpriseValidationError(EnterpriseError, ValueError):
    code = "ENTERPRISE_VALIDATION_ERROR"
    error_type = "validation_error"


class RetryableEnterpriseError(EnterpriseError):
    code = "ENTERPRISE_TEMPORARILY_UNAVAILABLE"
    error_type = "retryable_error"
    retryable = True


class ExternalServiceError(EnterpriseError):
    code = "EXTERNAL_SERVICE_ERROR"
    error_type = "external_service_error"


def enterprise_success(data: Any, **metadata: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, **metadata}


def enterprise_failure(error: EnterpriseError) -> dict[str, Any]:
    return {"ok": False, "error": error.to_dict()}


def enterprise_error_message(result: dict[str, Any], fallback: str) -> str:
    error = result.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or fallback)
    if error:
        return str(error)
    return fallback


async def run_retryable_enterprise_operation[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 2,
    base_delay_seconds: float = 0.05,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts 必须大于等于 1")

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except (RetryableEnterpriseError, ExternalServiceError) as exc:
            if not exc.retryable or attempt >= max_attempts:
                raise
            await asyncio.sleep(base_delay_seconds * (2 ** (attempt - 1)))

    raise RuntimeError("unreachable")
