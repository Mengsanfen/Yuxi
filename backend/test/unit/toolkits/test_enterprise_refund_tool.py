from decimal import Decimal
from types import SimpleNamespace

import pytest

from yuxi.agents.toolkits.enterprise import tools as enterprise_tools
from yuxi.services.enterprise_errors import BusinessRuleViolation


@pytest.mark.asyncio
async def test_refund_tool_preserves_partial_refund_business_error(monkeypatch):
    async def reject_partial_refund(**kwargs):
        raise BusinessRuleViolation(
            "当前 Demo 仅支持整单退款，请按订单实际可退款金额提交退款。",
            code="PARTIAL_REFUND_NOT_SUPPORTED",
        )

    monkeypatch.setattr(enterprise_tools, "execute_enterprise_refund", reject_partial_refund)
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

    result = await enterprise_tools.enterprise_request_refund.coroutine(
        order_no="ORDER-123",
        amount=Decimal("20.00"),
        reason="不再需要",
        runtime=runtime,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "PARTIAL_REFUND_NOT_SUPPORTED"
    assert result["error"]["type"] == "business_error"
    assert result["error"]["retryable"] is False
