from __future__ import annotations

import math

from .schemas import EnterpriseEvalCase, EnterpriseEvalCaseResult, EnterpriseEvalObservation


def _selection_scores(expected: set[str], actual: set[str]) -> tuple[float, float]:
    if not expected:
        return (1.0 if not actual else 0.0), 1.0
    true_positive = len(expected & actual)
    precision = true_positive / len(actual) if actual else 0.0
    recall = true_positive / len(expected)
    return precision, recall


def build_case_result(case: EnterpriseEvalCase, observation: EnterpriseEvalObservation) -> EnterpriseEvalCaseResult:
    actual_tools = set(observation.tool_names)
    expected_tools = set(case.expected_tools)
    precision, recall = _selection_scores(expected_tools, actual_tools)
    forbidden_violation = bool(set(case.forbidden_tools) & actual_tools)
    successful_tools = sum(item.status == "success" for item in observation.tool_executions)
    tool_success_rate = (
        successful_tools / len(observation.tool_executions) if observation.tool_executions else None
    )
    content_ok = all(text in observation.final_answer for text in case.must_contain)
    excluded_content_ok = all(text not in observation.final_answer for text in case.must_not_contain)
    status_ok = observation.final_status == case.expected_final_status
    checks: dict[str, bool | float | None] = {
        "intent_match": observation.actual_intent == case.expected_intent,
        "domain_match": None if case.expected_domain is None else observation.actual_domain == case.expected_domain,
        "action_match": None if case.expected_action is None else observation.actual_action == case.expected_action,
        "ticket_type_match": (
            None if case.expected_ticket_type is None else observation.actual_ticket_type == case.expected_ticket_type
        ),
        "tool_selection_precision": precision,
        "tool_selection_recall": recall,
        "forbidden_tool_violation": forbidden_violation,
        "tool_execution_success_rate": tool_success_rate,
        "approval_match": (
            None if case.expected_approval is None else observation.approval_required == case.expected_approval
        ),
        "escalation_match": (
            None if case.expected_escalation is None else observation.escalated == case.expected_escalation
        ),
        "final_status_match": status_ok,
        "must_contain_match": content_ok,
        "must_not_contain_match": excluded_content_ok,
        "quality_gate_passed": observation.quality_passed,
        "task_completed": (
            status_ok
            and content_ok
            and excluded_content_ok
            and observation.error is None
            and (case.expected_final_status != "completed" or observation.quality_passed is True)
        ),
    }
    required_checks = [
        bool(checks["intent_match"]),
        precision == 1.0,
        recall == 1.0,
        not forbidden_violation,
        status_ok,
        content_ok,
        excluded_content_ok,
        observation.error is None,
    ]
    if case.expected_final_status == "completed":
        required_checks.append(observation.quality_passed is True)
    if checks["approval_match"] is not None:
        required_checks.append(bool(checks["approval_match"]))
    if checks["escalation_match"] is not None:
        required_checks.append(bool(checks["escalation_match"]))
    for name in ("domain_match", "action_match", "ticket_type_match"):
        if checks[name] is not None:
            required_checks.append(bool(checks[name]))
    return EnterpriseEvalCaseResult(
        case=case,
        observation=observation,
        checks=checks,
        passed=all(required_checks),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 2)


def calculate_metrics(results: list[EnterpriseEvalCaseResult]) -> dict[str, int | float | None]:
    case_count = len(results)
    expected_tools = sum(len(set(result.case.expected_tools)) for result in results)
    actual_tools = sum(len(set(result.observation.tool_names)) for result in results)
    true_positive_tools = sum(
        len(set(result.case.expected_tools) & set(result.observation.tool_names)) for result in results
    )
    tool_executions = [execution for result in results for execution in result.observation.tool_executions]
    approval_results = [result for result in results if result.case.expected_approval is not None]
    escalation_results = [result for result in results if result.case.expected_escalation is not None]
    prompt_tokens = [
        result.observation.prompt_tokens
        for result in results
        if result.observation.prompt_tokens is not None
    ]
    completion_tokens = [
        result.observation.completion_tokens
        for result in results
        if result.observation.completion_tokens is not None
    ]
    costs = [result.observation.estimated_cost for result in results if result.observation.estimated_cost is not None]
    quality_results = [result for result in results if result.observation.quality_passed is not None]
    domain_results = [result for result in results if result.case.expected_domain is not None]
    action_results = [result for result in results if result.case.expected_action is not None]

    return {
        "case_count": case_count,
        "case_pass_rate": _ratio(sum(result.passed for result in results), case_count),
        "intent_accuracy": _ratio(
            sum(bool(result.checks["intent_match"]) for result in results), case_count
        ),
        "domain_accuracy": _ratio(
            sum(bool(result.checks["domain_match"]) for result in domain_results), len(domain_results)
        ),
        "action_accuracy": _ratio(
            sum(bool(result.checks["action_match"]) for result in action_results), len(action_results)
        ),
        "tool_selection_precision": _ratio(true_positive_tools, actual_tools) if actual_tools else 1.0,
        "tool_selection_recall": _ratio(true_positive_tools, expected_tools) if expected_tools else 1.0,
        "forbidden_tool_violation_rate": _ratio(
            sum(bool(result.checks["forbidden_tool_violation"]) for result in results), case_count
        ),
        "tool_execution_success_rate": _ratio(
            sum(execution.status == "success" for execution in tool_executions), len(tool_executions)
        ),
        "task_completion_rate": _ratio(
            sum(bool(result.checks["task_completed"]) for result in results), case_count
        ),
        "approval_accuracy": _ratio(
            sum(bool(result.checks["approval_match"]) for result in approval_results),
            len(approval_results),
        ),
        "escalation_accuracy": _ratio(
            sum(bool(result.checks["escalation_match"]) for result in escalation_results),
            len(escalation_results),
        ),
        "quality_gate_pass_rate": _ratio(
            sum(result.observation.quality_passed is True for result in quality_results),
            len(quality_results),
        ),
        "faithfulness": None,
        "answer_completeness": None,
        "p50_latency_ms": _percentile([result.observation.latency_ms for result in results], 0.5),
        "p95_latency_ms": _percentile([result.observation.latency_ms for result in results], 0.95),
        "prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
        "completion_tokens": sum(completion_tokens) if completion_tokens else None,
        "estimated_cost": round(sum(costs), 8) if costs else None,
    }
