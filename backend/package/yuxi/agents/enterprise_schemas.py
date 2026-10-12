from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class EnterpriseIntent(StrEnum):
    PRODUCT_QUESTION = "product_question"
    POLICY_QUESTION = "policy_question"
    ORDER_QUERY = "order_query"
    LOGISTICS_QUERY = "logistics_query"
    REFUND_REQUEST = "refund_request"
    TICKET_QUERY = "ticket_query"
    COMPLAINT = "complaint"
    UNKNOWN = "unknown"


class EnterpriseIntentDecision(BaseModel):
    domain: Literal["knowledge", "order", "refund", "ticket", "unknown"]
    action: Literal["query", "create", "request", "status", "logistics", "policy", "product", "unknown"]
    ticket_type: Literal["after_sale", "complaint", "unknown"] = "unknown"
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"]
    security_signals: list[str] = Field(default_factory=list)
    requires_order_context: bool = False
    requires_knowledge: bool = False

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_intent(cls, value):
        if not isinstance(value, dict) or "domain" in value:
            return value
        legacy_routes = {
            EnterpriseIntent.PRODUCT_QUESTION: ("knowledge", "product", "unknown"),
            EnterpriseIntent.POLICY_QUESTION: ("knowledge", "policy", "unknown"),
            EnterpriseIntent.ORDER_QUERY: ("order", "query", "unknown"),
            EnterpriseIntent.LOGISTICS_QUERY: ("order", "logistics", "unknown"),
            EnterpriseIntent.REFUND_REQUEST: ("refund", "request", "unknown"),
            EnterpriseIntent.TICKET_QUERY: ("ticket", "query", "unknown"),
            EnterpriseIntent.COMPLAINT: ("ticket", "create", "complaint"),
        }
        domain, action, ticket_type = legacy_routes.get(value.get("intent"), ("unknown", "unknown", "unknown"))
        return {**value, "domain": domain, "action": action, "ticket_type": ticket_type}

    @model_validator(mode="after")
    def enforce_business_context(self):
        if self.domain != "ticket" or self.action != "create":
            self.ticket_type = "unknown"
        if self.domain in {"order", "refund"}:
            self.requires_order_context = True
        if self.domain == "knowledge":
            self.requires_knowledge = True
        if self.domain == "ticket" and self.action == "create" and self.ticket_type == "complaint":
            self.risk_level = "high"
        return self

    @computed_field(return_type=EnterpriseIntent)
    @property
    def intent(self) -> EnterpriseIntent:
        if self.domain == "knowledge":
            return {
                "product": EnterpriseIntent.PRODUCT_QUESTION,
                "policy": EnterpriseIntent.POLICY_QUESTION,
            }.get(self.action, EnterpriseIntent.UNKNOWN)
        if self.domain == "order":
            if self.action == "logistics":
                return EnterpriseIntent.LOGISTICS_QUERY
            return EnterpriseIntent.ORDER_QUERY if self.action in {"query", "status"} else EnterpriseIntent.UNKNOWN
        if self.domain == "refund" and self.action == "request":
            return EnterpriseIntent.REFUND_REQUEST
        if self.domain == "ticket":
            if self.action == "create" and self.ticket_type == "complaint":
                return EnterpriseIntent.COMPLAINT
            if self.action in {"query", "status", "create"}:
                return EnterpriseIntent.TICKET_QUERY
        return EnterpriseIntent.UNKNOWN


class EnterpriseEntities(BaseModel):
    """Business identifiers explicitly present in the latest user request."""

    order_no: str | None = None
    customer_id: int | None = None
    refund_amount: Decimal | None = None
    refund_reason: str | None = None
    ticket_id: int | None = None


class EnterpriseQualityResult(BaseModel):
    passed: bool
    risk: Literal["low", "medium", "high"]
    issues: list[str] = Field(default_factory=list)
