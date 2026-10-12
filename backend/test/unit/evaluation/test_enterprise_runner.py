from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from yuxi.evaluation.enterprise.runner import (
    DEFAULT_DATASET,
    EvaluationFixtureData,
    _tool_executions,
    _final_status,
    _ticket_was_created,
    _resolve_knowledge_names,
    EnterpriseAgentEvaluator,
    load_dataset,
    select_cases,
)


def test_customer_service_dataset_has_required_coverage():
    cases = load_dataset(DEFAULT_DATASET)
    categories = {case.category for case in cases}

    assert len(cases) == 50
    assert len({case.id for case in cases}) == 50
    assert {
        "产品问题",
        "政策问题",
        "订单查询",
        "物流查询",
        "普通退款",
        "部分退款",
        "高额退款",
        "高风险投诉",
        "工单查询",
        "工单创建",
        "信息不足",
        "不存在订单",
        "重复退款",
        "跨租户",
        "越权操作",
        "Prompt Injection",
    }.issubset(categories)
    assert all(
        "query_kb" in case.expected_tools
        for case in cases
        if case.category in {"产品问题", "政策问题"}
    )
    partial = next(case for case in cases if case.id == "refund-partial-001")
    assert partial.fixture.product_price == Decimal("129.00")
    assert partial.expected_final_status == "failed"
    assert "整单退款" in partial.must_contain
    generic_create = next(case for case in cases if case.id == "ticket-create-002")
    assert (generic_create.expected_intent, generic_create.expected_domain, generic_create.expected_action) == (
        "ticket_query", "ticket", "create"
    )
    assert generic_create.expected_ticket_type == "after_sale"


def test_select_cases_supports_case_id_and_limit():
    cases = load_dataset(DEFAULT_DATASET)

    selected = select_cases(cases, case_ids=["order-001,refund-high-001"], limit=1)

    assert [case.id for case in selected] == ["order-001"]


def test_select_cases_rejects_unknown_id():
    cases = load_dataset(DEFAULT_DATASET)

    with pytest.raises(ValueError, match="Unknown case ids"):
        select_cases(cases, case_ids=["missing-case"], limit=None)


def test_load_dataset_rejects_duplicate_ids(tmp_path: Path):
    dataset = tmp_path / "duplicate.jsonl"
    line = '{"id":"same","category":"test","query":"query","expected_intent":"unknown"}'
    dataset.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate evaluation case id"):
        load_dataset(dataset)


def test_fixture_render_rejects_unresolved_placeholder():
    fixture = EvaluationFixtureData({"customer_id": "17"}, {})

    with pytest.raises(ValueError, match="Unresolved evaluation fixture placeholder"):
        fixture.render("查询订单 {{order_no}} 和客户 {{customer_id}}")


def test_tool_executions_distinguish_business_failure_from_plain_text_success():
    messages = [
        ToolMessage(
            content='{"ok": false, "error": {"code": "ORDER_NOT_FOUND"}}',
            tool_call_id="failed",
            name="enterprise_get_order_by_no",
        ),
        ToolMessage(content="No relevant documents", tool_call_id="plain", name="query_kb"),
    ]

    executions = _tool_executions(messages, [])

    assert [(item.name, item.status) for item in executions] == [
        ("enterprise_get_order_by_no", "error"),
        ("query_kb", "success"),
    ]
    assert executions[0].error == "ORDER_NOT_FOUND"


def test_failed_quality_does_not_report_completed_status():
    assert _final_status({"quality_result": {"passed": False}}, [], None) == "failed"
    assert _final_status(
        {"quality_result": {"passed": False}, "knowledge_result": {"security": {"blocked": True}}},
        [],
        None,
    ) == "blocked"


def test_ticket_escalation_uses_create_action_and_persisted_result():
    created = {"domain": "ticket", "action": "create", "intent": "ticket_query", "ticket_result": {"id": 17}}
    queried = {"domain": "ticket", "action": "query", "intent": "ticket_query", "ticket_result": {"id": 17}}

    assert _ticket_was_created(created) is True
    assert _ticket_was_created(queried) is False


@pytest.mark.asyncio
async def test_evaluation_knowledge_override_requires_actor_access(monkeypatch):
    async def fake_databases(user_id):
        assert user_id == "agent-user"
        return {"databases": [{"name": "Policy"}, {"name": "Other"}]}

    monkeypatch.setattr(
        "yuxi.evaluation.enterprise.runner.knowledge_base.get_databases_by_user_id",
        fake_databases,
    )
    actor = SimpleNamespace(user_id="agent-user")

    assert await _resolve_knowledge_names(actor, [" Policy ", "Policy"]) == ["Policy"]
    with pytest.raises(ValueError, match="unavailable"):
        await _resolve_knowledge_names(actor, ["Foreign tenant"])


def test_evaluation_context_overrides_knowledge_without_mutating_agent_config():
    actor = SimpleNamespace(user_id="agent-user", department_id=7, role="admin")
    agent_config = SimpleNamespace(id=3, config_json={"context": {
        "knowledges": ["Configured"], "model": "test:model"
    }})
    evaluator = EnterpriseAgentEvaluator(
        actor=actor,
        agent_config=agent_config,
        knowledge_names=["Policy"],
    )

    context = evaluator._context("eval-thread")

    assert context.knowledges == ["Policy"]
    assert context.tenant_id == 7
    assert context.thread_id == "eval-thread"
    assert context.model == "test:model"
    assert agent_config.config_json["context"]["knowledges"] == ["Configured"]
