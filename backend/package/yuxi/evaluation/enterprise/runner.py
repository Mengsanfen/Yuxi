from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import case as sql_case
from sqlalchemy import delete, select

from yuxi import config as sys_config
from yuxi import knowledge_base
from yuxi.agents.buildin.enterprise_service.graph import EnterpriseServiceAgent, build_enterprise_workflow
from yuxi.repositories.agent_config_repository import AgentConfigRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import (
    AgentConfig,
    ApprovalTask,
    Customer,
    CustomerLevel,
    Department,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductStatus,
    Refund,
    RiskLevel,
    Ticket,
    TicketPriority,
    TicketSource,
    TicketStatus,
    TicketType,
    User,
)
from yuxi.utils.datetime_utils import utc_now_naive

from .metrics import build_case_result, calculate_metrics
from .reporters import write_reports
from .schemas import (
    EnterpriseEvalCase,
    EnterpriseEvalFixture,
    EnterpriseEvalObservation,
    EnterpriseEvalReport,
    EnterpriseToolExecution,
)


BACKEND_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = BACKEND_DIR / "eval" / "enterprise" / "datasets" / "customer_service_v1.jsonl"
DEFAULT_REPORT_DIR = BACKEND_DIR / "eval" / "enterprise" / "reports"
AGENT_ID = "EnterpriseServiceAgent"


class TokenUsageCollector(BaseCallbackHandler):
    def __init__(self) -> None:
        self.llm_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seen_usage = False

    def on_llm_end(self, response, **kwargs: Any) -> None:
        del kwargs
        self.llm_calls += 1
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        if not usage:
            for generations in getattr(response, "generations", []) or []:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None) or {}
                    if usage:
                        break
                if usage:
                    break
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if prompt is not None or completion is not None:
            self.seen_usage = True
            self.prompt_tokens += int(prompt or 0)
            self.completion_tokens += int(completion or 0)


def load_dataset(path: Path) -> list[EnterpriseEvalCase]:
    cases: list[EnterpriseEvalCase] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                case = EnterpriseEvalCase.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"Invalid evaluation case at {path}:{line_number}: {exc}") from exc
            if case.id in seen_ids:
                raise ValueError(f"Duplicate evaluation case id at {path}:{line_number}: {case.id}")
            seen_ids.add(case.id)
            cases.append(case)
    if not cases:
        raise ValueError(f"No evaluation cases found in {path}")
    return cases


def select_cases(
    cases: list[EnterpriseEvalCase],
    *,
    case_ids: list[str] | None,
    limit: int | None,
) -> list[EnterpriseEvalCase]:
    selected = cases
    if case_ids:
        requested = {item for value in case_ids for item in value.split(",") if item}
        selected = [case for case in cases if case.id in requested]
        missing = requested - {case.id for case in selected}
        if missing:
            raise ValueError(f"Unknown case ids: {', '.join(sorted(missing))}")
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be greater than zero")
        selected = selected[:limit]
    return selected


async def _resolve_actor(user_id: str | None) -> User:
    async with pg_manager.get_async_session_context() as session:
        stmt = select(User).where(User.is_deleted == 0, User.department_id.is_not(None))
        if user_id:
            stmt = stmt.where(User.user_id == user_id)
        else:
            stmt = stmt.order_by(
                sql_case(
                    (User.role == "superadmin", 0),
                    (User.role == "admin", 1),
                    else_=2,
                ),
                User.id,
            )
        actor = (await session.execute(stmt.limit(1))).scalar_one_or_none()
        if actor is None:
            raise RuntimeError("No active evaluation user with a department was found")
        session.expunge(actor)
        return actor


async def _resolve_agent_config(actor: User) -> AgentConfig:
    async with pg_manager.get_async_session_context() as session:
        repository = AgentConfigRepository(session)
        config = await repository.get_or_create_default(
            department_id=int(actor.department_id),
            agent_id=AGENT_ID,
            created_by=actor.user_id,
        )
        session.expunge(config)
        return config


async def _resolve_knowledge_names(actor: User, requested: list[str] | None) -> list[str] | None:
    if not requested:
        return None
    names = list(dict.fromkeys(name.strip() for name in requested if name.strip()))
    databases = (await knowledge_base.get_databases_by_user_id(actor.user_id)).get("databases") or []
    accessible = {str(item.get("name") or "") for item in databases}
    unknown = set(names) - accessible
    if unknown:
        raise ValueError(f"Knowledge bases unavailable to evaluation user: {', '.join(sorted(unknown))}")
    return names


class EvaluationFixtureData:
    def __init__(self, values: dict[str, str], ids: dict[str, int | None]) -> None:
        self.values = values
        self.ids = ids

    def render(self, query: str) -> str:
        for name, value in self.values.items():
            query = query.replace(f"{{{{{name}}}}}", value)
        if "{{" in query or "}}" in query:
            raise ValueError(f"Unresolved evaluation fixture placeholder: {query}")
        return query


@asynccontextmanager
async def evaluation_fixture(
    fixture: EnterpriseEvalFixture | None,
    *,
    tenant_id: int,
) -> AsyncIterator[EvaluationFixtureData]:
    if fixture is None:
        yield EvaluationFixtureData({}, {})
        return

    suffix = uuid.uuid4().hex[:12].upper()
    ids: dict[str, int | None] = {
        "tenant_id": tenant_id,
        "customer_id": None,
        "product_id": None,
        "order_id": None,
        "ticket_id": None,
        "department_id": None,
    }
    values: dict[str, str] = {}
    target_tenant_id = tenant_id
    async with pg_manager.get_async_session_context() as session:
        if fixture.foreign_tenant:
            department = Department(name=f"enterprise-eval-{suffix}", description="Temporary evaluation tenant")
            session.add(department)
            await session.flush()
            target_tenant_id = int(department.id)
            ids["department_id"] = target_tenant_id
            ids["tenant_id"] = target_tenant_id

        customer = Customer(
            tenant_id=target_tenant_id,
            name=f"Eval Customer {suffix}",
            email=f"enterprise-eval-{suffix.lower()}@local.invalid",
            phone=None,
            level=CustomerLevel.STANDARD,
            risk_level=RiskLevel(fixture.customer_risk),
        )
        session.add(customer)
        await session.flush()
        ids["customer_id"] = int(customer.id)
        values["customer_id"] = str(customer.id)

        if fixture.order_status is not None:
            product = Product(
                tenant_id=target_tenant_id,
                sku=f"EVAL-{suffix}",
                name="Enterprise Evaluation Product",
                category="evaluation",
                price=fixture.product_price,
                status=ProductStatus.ACTIVE,
            )
            session.add(product)
            await session.flush()
            ids["product_id"] = int(product.id)

            status = OrderStatus(fixture.order_status)
            paid = status in {OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}
            shipped = status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}
            delivered = status in {OrderStatus.DELIVERED, OrderStatus.REFUNDED}
            now = utc_now_naive()
            order = Order(
                tenant_id=target_tenant_id,
                customer_id=customer.id,
                order_no=f"EVAL-{suffix}",
                status=status,
                total_amount=fixture.product_price,
                paid_amount=fixture.product_price if paid else Decimal("0.00"),
                logistics_company="顺丰速运" if shipped else None,
                tracking_no=f"SF-EVAL-{suffix}" if shipped else None,
                paid_at=now if paid else None,
                shipped_at=now if shipped else None,
                delivered_at=now if delivered else None,
            )
            order.items = [
                OrderItem(
                    tenant_id=target_tenant_id,
                    product_id=product.id,
                    quantity=1,
                    unit_price=fixture.product_price,
                )
            ]
            session.add(order)
            await session.flush()
            ids["order_id"] = int(order.id)
            values["order_no"] = order.order_no

        if fixture.create_ticket:
            ticket = Ticket(
                tenant_id=target_tenant_id,
                customer_id=customer.id,
                order_id=ids["order_id"],
                type=TicketType.AFTER_SALE,
                priority=TicketPriority.MEDIUM,
                status=TicketStatus.OPEN,
                summary="Enterprise evaluation fixture ticket",
                assignee=None,
                source=TicketSource.API,
                idempotency_key=f"enterprise-eval:{suffix}",
            )
            session.add(ticket)
            await session.flush()
            ids["ticket_id"] = int(ticket.id)
            values["ticket_id"] = str(ticket.id)

    try:
        yield EvaluationFixtureData(values, ids)
    finally:
        async with pg_manager.get_async_session_context() as session:
            order_id = ids.get("order_id")
            if order_id is not None:
                refund_ids = list(
                    (await session.execute(select(Refund.id).where(Refund.order_id == order_id))).scalars().all()
                )
                if refund_ids:
                    await session.execute(
                        delete(ApprovalTask).where(
                            ApprovalTask.business_type == "refund",
                            ApprovalTask.business_id.in_(refund_ids),
                        )
                    )
                    await session.execute(delete(Refund).where(Refund.id.in_(refund_ids)))
                await session.execute(delete(Ticket).where(Ticket.order_id == order_id))
                await session.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
                await session.execute(delete(Order).where(Order.id == order_id))
            ticket_id = ids.get("ticket_id")
            if ticket_id is not None:
                await session.execute(delete(Ticket).where(Ticket.id == ticket_id))
            product_id = ids.get("product_id")
            if product_id is not None:
                await session.execute(delete(Product).where(Product.id == product_id))
            customer_id = ids.get("customer_id")
            if customer_id is not None:
                await session.execute(delete(Ticket).where(Ticket.customer_id == customer_id))
                await session.execute(delete(Customer).where(Customer.id == customer_id))
            department_id = ids.get("department_id")
            if department_id is not None:
                await session.execute(delete(Department).where(Department.id == department_id))


def _interrupt_values(snapshot) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                values.append(value)
    return values


def _tool_executions(messages: list[Any], interrupts: list[dict[str, Any]]) -> list[EnterpriseToolExecution]:
    executions: list[EnterpriseToolExecution] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        name = str(message.name or "unknown")
        status = "error" if message.status == "error" else "success"
        error = None
        try:
            payload = json.loads(str(message.content))
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and (payload.get("ok") is False or payload.get("status") == "error"):
            status = "error"
            failure = payload.get("error")
            if isinstance(failure, dict):
                error = str(failure.get("code") or failure.get("message") or "tool error")
            else:
                error = str(failure or "tool error")
        elif status == "error":
            error = str(message.content)
        executions.append(EnterpriseToolExecution(name=name, status=status, error=error))
    if any(value.get("source") == "enterprise_refund_approval" for value in interrupts):
        if not any(item.name == "enterprise_request_refund" for item in executions):
            executions.append(EnterpriseToolExecution(name="enterprise_request_refund", status="success"))
    return executions


def _final_answer(state: dict[str, Any]) -> str:
    if state.get("final_answer"):
        return str(state["final_answer"])
    for message in reversed(state.get("messages") or []):
        if isinstance(message, AIMessage) and str(message.content).strip():
            return str(message.content)
    return ""


def _interrupt_answer(interrupts: list[dict[str, Any]]) -> str:
    questions = [
        str(question.get("question") or "").strip()
        for value in interrupts
        for question in value.get("questions") or []
        if isinstance(question, dict)
    ]
    return "\n".join(question for question in questions if question)


def _business_error_code(state: dict[str, Any]) -> str | None:
    for name in ("refund_result", "ticket_result", "order_context", "knowledge_result"):
        value = state.get(name)
        if not isinstance(value, dict) or value.get("ok") is not False:
            continue
        error = value.get("error") or {}
        return str(error.get("code") or "ENTERPRISE_OPERATION_FAILED")
    return None


def _final_status(state: dict[str, Any], interrupts: list[dict[str, Any]], error: str | None):
    if interrupts:
        return "pending_approval"
    if error:
        return "failed"
    if state.get("intent") == "unknown":
        return "needs_information"
    quality = state.get("quality_result") or {}
    if quality.get("passed") is False:
        security = (state.get("knowledge_result") or {}).get("security") or {}
        return "blocked" if security.get("blocked") else "failed"
    code = _business_error_code(state)
    if code:
        if "NOT_FOUND" in code:
            return "not_found"
        if "REQUIRED" in code or "INFORMATION" in code:
            return "needs_information"
        if "PERMISSION" in code or "TENANT" in code:
            return "blocked"
        return "failed"
    return "completed"


def _ticket_was_created(state: dict[str, Any]) -> bool:
    result = state.get("ticket_result")
    create_requested = (
        state.get("domain") == "ticket" and state.get("action") == "create"
    ) or state.get("intent") == "complaint"
    return (
        create_requested
        and isinstance(result, dict)
        and result.get("ok") is not False
        and result.get("id") is not None
    )


class EnterpriseAgentEvaluator:
    def __init__(
        self,
        *,
        actor: User,
        agent_config: AgentConfig,
        model: str | None = None,
        knowledge_names: list[str] | None = None,
    ) -> None:
        self.actor = actor
        self.agent_config = agent_config
        self.knowledge_names = knowledge_names
        configured_model = ((agent_config.config_json or {}).get("context") or {}).get("model")
        self.model = model or configured_model or sys_config.default_model

    def _context(self, thread_id: str):
        context = EnterpriseServiceAgent.context_schema()
        context.update((self.agent_config.config_json or {}).get("context") or {})
        if self.knowledge_names is not None:
            context.update({"knowledges": self.knowledge_names})
        context.update(
            {
                "thread_id": thread_id,
                "user_id": self.actor.user_id,
                "account_user_id": self.actor.user_id,
                "tenant_id": int(self.actor.department_id),
                "user_role": self.actor.role,
                "agent_id": AGENT_ID,
                "agent_config_id": self.agent_config.id,
                "model": self.model,
                "subagents_model": self.model,
            }
        )
        return context

    async def evaluate(self, case: EnterpriseEvalCase) -> EnterpriseEvalObservation:
        thread_id = f"enterprise-eval-{case.id}-{uuid.uuid4().hex[:12]}"
        collector = TokenUsageCollector()
        started = perf_counter()
        state: dict[str, Any] = {}
        interrupts: list[dict[str, Any]] = []
        run_error: str | None = None
        async with evaluation_fixture(case.fixture, tenant_id=int(self.actor.department_id)) as fixture:
            query = fixture.render(case.query)
            context = self._context(thread_id)
            graph = build_enterprise_workflow(EnterpriseServiceAgent.context_schema).compile(
                checkpointer=InMemorySaver()
            )
            langgraph_config = {
                "configurable": {"thread_id": thread_id, "user_id": self.actor.user_id},
                "callbacks": [collector],
                "recursion_limit": 100,
            }
            try:
                for _ in range(case.repeat):
                    result = await graph.ainvoke(
                        {"messages": [HumanMessage(content=query)]},
                        context=context,
                        config=langgraph_config,
                    )
                    state = dict(result or {})
                snapshot = await graph.aget_state(langgraph_config)
                if snapshot and snapshot.values:
                    state = dict(snapshot.values)
                interrupts = _interrupt_values(snapshot)
            except Exception as exc:
                run_error = f"{type(exc).__name__}: {exc}"

        executions = _tool_executions(state.get("messages") or [], interrupts)
        approval_required = any(
            value.get("source") == "enterprise_refund_approval" for value in interrupts
        )
        escalated = approval_required or _ticket_was_created(state)
        quality = state.get("quality_result") or {}
        final_answer = _final_answer(state) or _interrupt_answer(interrupts)
        return EnterpriseEvalObservation(
            actual_intent=state.get("intent"),
            actual_domain=state.get("domain"),
            actual_action=state.get("action"),
            actual_ticket_type=state.get("ticket_type"),
            tool_executions=executions,
            approval_required=approval_required,
            escalated=escalated,
            final_status=_final_status(state, interrupts, run_error),
            final_answer=final_answer,
            quality_passed=quality.get("passed") if quality else None,
            quality_issues=[str(issue) for issue in quality.get("issues") or []],
            latency_ms=(perf_counter() - started) * 1000,
            llm_call_count=collector.llm_calls,
            tool_call_count=len(executions),
            retrieval_call_count=sum(item.name == "query_kb" for item in executions),
            quality_call_count=int(state.get("quality_call_count") or 0),
            prompt_tokens=collector.prompt_tokens if collector.seen_usage else None,
            completion_tokens=collector.completion_tokens if collector.seen_usage else None,
            estimated_cost=None,
            error=run_error,
        )


def _output_base(output: str | None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if not output:
        return DEFAULT_REPORT_DIR / f"enterprise_eval_{stamp}"
    path = Path(output)
    if path.suffix in {".json", ".md"}:
        return path.with_suffix("")
    if path.exists() and path.is_dir() or not path.suffix:
        return path / f"enterprise_eval_{stamp}"
    return path


async def run_evaluation(args: argparse.Namespace) -> EnterpriseEvalReport:
    dataset_path = Path(args.dataset).resolve()
    cases = select_cases(load_dataset(dataset_path), case_ids=args.case_id, limit=args.limit)
    if not pg_manager._initialized:
        pg_manager.initialize()
    actor = await _resolve_actor(args.user_id)
    agent_config = await _resolve_agent_config(actor)
    knowledge_names = await _resolve_knowledge_names(actor, args.knowledge_base)
    evaluator = EnterpriseAgentEvaluator(
        actor=actor,
        agent_config=agent_config,
        model=args.model,
        knowledge_names=knowledge_names,
    )
    results = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case.id}", flush=True)
        observation = await evaluator.evaluate(case)
        results.append(build_case_result(case, observation))

    report = EnterpriseEvalReport(
        generated_at=datetime.now(UTC).isoformat(),
        dataset=str(dataset_path),
        model=evaluator.model,
        metrics=calculate_metrics(results),
        cases=results,
        notes=[
            "Faithfulness and answer completeness remain N/A until an explicit LLM judge is configured.",
            "Estimated cost remains N/A because this run has no verified model pricing configuration.",
        ],
    )
    json_path, markdown_path = write_reports(report, _output_base(args.output))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the enterprise service agent with real graph runs")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to a JSONL dataset")
    parser.add_argument("--limit", type=int, help="Run only the first N selected cases")
    parser.add_argument("--case-id", action="append", help="Run one case id; repeat or comma-separate values")
    parser.add_argument("--model", help="Override both supervisor and subagent model specs")
    parser.add_argument("--output", help="Output directory or report file stem")
    parser.add_argument("--user-id", help="Run as this active application user")
    parser.add_argument("--knowledge-base", action="append", help="Enable an accessible KB for this run")
    return parser


async def _async_main(args: argparse.Namespace) -> None:
    try:
        await run_evaluation(args)
    finally:
        if pg_manager._initialized:
            await pg_manager.close()


def main() -> None:
    asyncio.run(_async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
