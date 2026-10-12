from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


EnterpriseFinalStatus = Literal[
    "completed",
    "pending_approval",
    "needs_information",
    "not_found",
    "blocked",
    "failed",
]


class EnterpriseEvalFixture(BaseModel):
    """Disposable business data required by one evaluation case."""

    order_status: Literal["pending", "paid", "shipped", "delivered", "refunded"] | None = None
    product_price: Decimal = Field(default=Decimal("499.00"), gt=0)
    customer_risk: Literal["low", "medium", "high"] = "low"
    create_ticket: bool = False
    foreign_tenant: bool = False


class EnterpriseEvalCase(BaseModel):
    id: str
    category: str
    query: str
    expected_intent: str
    expected_domain: str | None = None
    expected_action: str | None = None
    expected_ticket_type: str | None = None
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_approval: bool | None = None
    expected_escalation: bool | None = None
    expected_final_status: EnterpriseFinalStatus = "completed"
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    fixture: EnterpriseEvalFixture | None = None
    repeat: int = Field(default=1, ge=1, le=2)

    @field_validator("id", "category", "query", "expected_intent")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class EnterpriseToolExecution(BaseModel):
    name: str
    status: Literal["success", "error", "unknown"] = "unknown"
    error: str | None = None


class EnterpriseEvalObservation(BaseModel):
    actual_intent: str | None = None
    actual_domain: str | None = None
    actual_action: str | None = None
    actual_ticket_type: str | None = None
    tool_executions: list[EnterpriseToolExecution] = Field(default_factory=list)
    approval_required: bool = False
    escalated: bool = False
    final_status: EnterpriseFinalStatus = "failed"
    final_answer: str = ""
    quality_passed: bool | None = None
    quality_issues: list[str] = Field(default_factory=list)
    latency_ms: float = Field(default=0, ge=0)
    llm_call_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    retrieval_call_count: int = Field(default=0, ge=0)
    quality_call_count: int = Field(default=0, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    error: str | None = None

    @property
    def tool_names(self) -> list[str]:
        return [execution.name for execution in self.tool_executions]


class EnterpriseEvalCaseResult(BaseModel):
    case: EnterpriseEvalCase
    observation: EnterpriseEvalObservation
    checks: dict[str, bool | float | None]
    passed: bool


class EnterpriseEvalReport(BaseModel):
    generated_at: str
    dataset: str
    model: str
    metrics: dict[str, int | float | None]
    cases: list[EnterpriseEvalCaseResult]
    notes: list[str] = Field(default_factory=list)
