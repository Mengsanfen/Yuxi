from datetime import timedelta
from decimal import Decimal

import pytest

from yuxi.services.enterprise_service import (
    BusinessConflictError,
    BusinessRuleViolation,
    RefundPolicyService,
    TicketStateMachine,
)
from yuxi.storage.postgres.models_business import (
    OrderStatus,
    RefundStatus,
    RiskLevel,
    TicketStatus,
)
from yuxi.utils.datetime_utils import utc_now_naive


def test_refund_policy_auto_approves_low_value_request():
    decision = RefundPolicyService.evaluate(
        amount=Decimal("99.00"),
        paid_amount=Decimal("99.00"),
        order_status=OrderStatus.DELIVERED,
        customer_risk_level=RiskLevel.LOW,
        reason="不符合预期",
    )

    assert decision.status == RefundStatus.APPROVED
    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_approval is False


def test_refund_policy_rejects_partial_refund():
    with pytest.raises(BusinessRuleViolation) as error:
        RefundPolicyService.evaluate(
            amount=Decimal("20.00"),
            paid_amount=Decimal("129.00"),
            order_status=OrderStatus.PAID,
            customer_risk_level=RiskLevel.LOW,
            reason="不再需要",
        )

    assert error.value.code == "PARTIAL_REFUND_NOT_SUPPORTED"
    assert "仅支持整单退款" in error.value.message


@pytest.mark.parametrize(
    ("amount", "customer_risk", "reason", "expected_risk"),
    [
        (Decimal("100.01"), RiskLevel.LOW, "正常退货", RiskLevel.MEDIUM),
        (Decimal("50.00"), RiskLevel.HIGH, "正常退货", RiskLevel.HIGH),
        (Decimal("50.00"), RiskLevel.LOW, "投诉疑似欺诈", RiskLevel.HIGH),
    ],
)
def test_refund_policy_routes_risky_requests_to_approval(amount, customer_risk, reason, expected_risk):
    decision = RefundPolicyService.evaluate(
        amount=amount,
        paid_amount=amount,
        order_status=OrderStatus.PAID,
        customer_risk_level=customer_risk,
        reason=reason,
    )

    assert decision.status == RefundStatus.PENDING_APPROVAL
    assert decision.risk_level == expected_risk
    assert decision.requires_approval is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": Decimal("0.00")},
        {"amount": Decimal("301.00")},
        {"order_status": OrderStatus.PENDING},
        {"delivered_at": utc_now_naive() - timedelta(days=31)},
    ],
)
def test_refund_policy_rejects_ineligible_requests(overrides):
    arguments = {
        "amount": Decimal("100.00"),
        "paid_amount": Decimal("100.00"),
        "order_status": OrderStatus.DELIVERED,
        "customer_risk_level": RiskLevel.LOW,
        "reason": "普通退款",
    }
    arguments.update(overrides)

    with pytest.raises(BusinessRuleViolation):
        RefundPolicyService.evaluate(**arguments)


def test_refund_policy_rejects_already_refunded_order():
    with pytest.raises(BusinessConflictError) as error:
        RefundPolicyService.evaluate(
            amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            order_status=OrderStatus.REFUNDED,
            customer_risk_level=RiskLevel.LOW,
            reason="不再需要",
        )

    assert error.value.code == "ORDER_ALREADY_REFUNDED"


def test_ticket_state_machine_accepts_supported_workflow():
    TicketStateMachine.validate(TicketStatus.OPEN, TicketStatus.PROCESSING)
    TicketStateMachine.validate(TicketStatus.PROCESSING, TicketStatus.WAITING_CUSTOMER)
    TicketStateMachine.validate(TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED)
    TicketStateMachine.validate(TicketStatus.RESOLVED, TicketStatus.CLOSED)


def test_ticket_state_machine_rejects_illegal_transition():
    with pytest.raises(BusinessRuleViolation, match="open -> closed"):
        TicketStateMachine.validate(TicketStatus.OPEN, TicketStatus.CLOSED)
