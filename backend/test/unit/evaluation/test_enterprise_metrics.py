from pathlib import Path

from yuxi.evaluation.enterprise.metrics import build_case_result, calculate_metrics
from yuxi.evaluation.enterprise.reporters import render_markdown, write_reports
from yuxi.evaluation.enterprise.schemas import (
    EnterpriseEvalCase,
    EnterpriseEvalObservation,
    EnterpriseEvalReport,
    EnterpriseToolExecution,
)


def _case(**overrides) -> EnterpriseEvalCase:
    payload = {
        "id": "refund-high-001",
        "category": "高额退款",
        "query": "订单 A 退款 299 元",
        "expected_intent": "refund_request",
        "expected_tools": ["enterprise_get_order_by_no", "enterprise_request_refund"],
        "forbidden_tools": ["enterprise_create_ticket"],
        "expected_approval": True,
        "expected_escalation": True,
        "expected_final_status": "pending_approval",
        "must_not_contain": ["退款已成功完成"],
    }
    payload.update(overrides)
    return EnterpriseEvalCase.model_validate(payload)


def test_case_result_scores_deterministic_checks():
    observation = EnterpriseEvalObservation(
        actual_intent="refund_request",
        tool_executions=[
            EnterpriseToolExecution(name="enterprise_get_order_by_no", status="success"),
            EnterpriseToolExecution(name="enterprise_request_refund", status="success"),
        ],
        approval_required=True,
        escalated=True,
        final_status="pending_approval",
        latency_ms=120,
    )

    result = build_case_result(_case(), observation)

    assert result.passed is True
    assert result.checks["intent_match"] is True
    assert result.checks["tool_selection_precision"] == 1
    assert result.checks["tool_selection_recall"] == 1
    assert result.checks["forbidden_tool_violation"] is False


def test_aggregate_metrics_include_latency_tokens_and_violations():
    passing = build_case_result(
        _case(),
        EnterpriseEvalObservation(
            actual_intent="refund_request",
            tool_executions=[
                EnterpriseToolExecution(name="enterprise_get_order_by_no", status="success"),
                EnterpriseToolExecution(name="enterprise_request_refund", status="success"),
            ],
            approval_required=True,
            escalated=True,
            final_status="pending_approval",
            latency_ms=100,
            prompt_tokens=10,
            completion_tokens=5,
        ),
    )
    failing = build_case_result(
        _case(id="refund-high-002"),
        EnterpriseEvalObservation(
            actual_intent="refund_request",
            tool_executions=[EnterpriseToolExecution(name="enterprise_create_ticket", status="error")],
            approval_required=False,
            escalated=False,
            final_status="failed",
            latency_ms=300,
            prompt_tokens=20,
            completion_tokens=10,
            error="tool failed",
        ),
    )

    metrics = calculate_metrics([passing, failing])

    assert metrics["case_count"] == 2
    assert metrics["case_pass_rate"] == 0.5
    assert metrics["intent_accuracy"] == 1
    assert metrics["forbidden_tool_violation_rate"] == 0.5
    assert metrics["tool_execution_success_rate"] == 0.6667
    assert metrics["approval_accuracy"] == 0.5
    assert metrics["p50_latency_ms"] == 200
    assert metrics["p95_latency_ms"] == 290
    assert metrics["prompt_tokens"] == 30
    assert metrics["completion_tokens"] == 15
    assert metrics["faithfulness"] is None


def test_completed_case_requires_passing_quality_gate():
    case = _case(expected_final_status="completed", expected_approval=False, expected_escalation=False)
    observation = EnterpriseEvalObservation(
        actual_intent="refund_request",
        tool_executions=[
            EnterpriseToolExecution(name="enterprise_get_order_by_no", status="success"),
            EnterpriseToolExecution(name="enterprise_request_refund", status="success"),
        ],
        final_status="completed",
        quality_passed=False,
        quality_issues=["Citation missing from retrieved sources"],
    )

    result = build_case_result(case, observation)

    assert result.passed is False
    assert result.checks["task_completed"] is False
    assert result.observation.quality_issues == ["Citation missing from retrieved sources"]


def test_ticket_creation_checks_domain_action_and_type_when_labeled():
    case = _case(
        expected_intent="ticket_query",
        expected_domain="ticket",
        expected_action="create",
        expected_ticket_type="after_sale",
        expected_tools=["enterprise_create_ticket"],
        forbidden_tools=[],
        expected_approval=False,
        expected_escalation=True,
        expected_final_status="completed",
    )
    observation = EnterpriseEvalObservation(
        actual_intent="ticket_query",
        actual_domain="ticket",
        actual_action="query",
        actual_ticket_type="unknown",
        tool_executions=[EnterpriseToolExecution(name="enterprise_create_ticket", status="success")],
        escalated=True,
        final_status="completed",
        quality_passed=True,
    )

    result = build_case_result(case, observation)

    assert result.passed is False
    assert result.checks["domain_match"] is True
    assert result.checks["action_match"] is False
    assert result.checks["ticket_type_match"] is False
    assert calculate_metrics([result])["action_accuracy"] == 0


def test_reporters_write_json_and_markdown(tmp_path: Path):
    result = build_case_result(
        _case(),
        EnterpriseEvalObservation(
            actual_intent="refund_request",
            tool_executions=[
                EnterpriseToolExecution(name="enterprise_get_order_by_no", status="success"),
                EnterpriseToolExecution(name="enterprise_request_refund", status="success"),
            ],
            approval_required=True,
            escalated=True,
            final_status="pending_approval",
            latency_ms=50,
        ),
    )
    report = EnterpriseEvalReport(
        generated_at="2026-10-02T00:00:00+00:00",
        dataset="customer_service_v1.jsonl",
        model="test:model",
        metrics=calculate_metrics([result]),
        cases=[result],
    )

    json_path, markdown_path = write_reports(report, tmp_path / "enterprise_eval")

    assert json_path.exists()
    assert markdown_path.exists()
    markdown = render_markdown(report)
    assert "Enterprise Agent Evaluation" in markdown
    assert "refund-high-001" in markdown
    assert "PASS" in markdown
