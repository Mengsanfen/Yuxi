from __future__ import annotations

import pytest

from yuxi.agents.toolkits.enterprise import tools as enterprise_tools
from yuxi.services.enterprise_errors import (
    BusinessRuleViolation,
    ExternalServiceError,
    RetryableEnterpriseError,
    enterprise_failure,
    run_retryable_enterprise_operation,
)


def test_enterprise_failure_has_stable_public_contract():
    result = enterprise_failure(
        BusinessRuleViolation(
            "订单已超过退款期限",
            code="REFUND_WINDOW_EXPIRED",
        )
    )

    assert result == {
        "ok": False,
        "error": {
            "code": "REFUND_WINDOW_EXPIRED",
            "type": "business_error",
            "message": "订单已超过退款期限",
            "retryable": False,
        },
    }


@pytest.mark.asyncio
async def test_retryable_operation_retries_at_most_two_attempts():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RetryableEnterpriseError("临时不可用")
        return "ok"

    result = await run_retryable_enterprise_operation(
        operation,
        max_attempts=2,
        base_delay_seconds=0,
    )

    assert result == "ok"
    assert attempts == 2


@pytest.mark.asyncio
async def test_business_error_is_not_retried():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise BusinessRuleViolation("不可重试")

    with pytest.raises(BusinessRuleViolation):
        await run_retryable_enterprise_operation(
            operation,
            max_attempts=2,
            base_delay_seconds=0,
        )

    assert attempts == 1


@pytest.mark.asyncio
async def test_non_retryable_external_error_is_not_retried():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise ExternalServiceError("外部服务拒绝请求", retryable=False)

    with pytest.raises(ExternalServiceError):
        await run_retryable_enterprise_operation(
            operation,
            max_attempts=2,
            base_delay_seconds=0,
        )

    assert attempts == 1


@pytest.mark.asyncio
async def test_tool_masks_unexpected_internal_error():
    async def operation():
        raise RuntimeError("postgresql://admin:secret@database/internal")

    result = await enterprise_tools._run_service(operation)

    assert result["ok"] is False
    assert result["error"]["code"] == "ENTERPRISE_OPERATION_FAILED"
    assert result["error"]["message"] == "企业服务暂时不可用，请稍后重试"
    assert "postgresql" not in str(result)
    assert "secret" not in str(result)
