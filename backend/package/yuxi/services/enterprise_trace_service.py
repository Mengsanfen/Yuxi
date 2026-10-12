from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from yuxi.repositories.enterprise_trace_repository import EnterpriseTraceRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.utils.logging_config import logger

REDACTED = "***"
SENSITIVE_KEY_PARTS = {
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
}
EMAIL_PATTERN = re.compile(r"(?P<name>[A-Z0-9._%+-])[^@\s]*@(?P<domain>[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)")

NODE_EVENT_TYPES = {
    "classify": "intent",
    "extract_entities": "entities",
    "knowledge": "retrieval",
    "order": "business_query",
    "refund_order": "business_query",
    "refund": "business_action",
    "ticket": "business_action",
    "quality": "quality",
    "repair": "repair",
    "finalize": "final",
}

NODE_AGENT_NAMES = {
    "knowledge": "knowledge-agent",
}


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _mask_text(value: str, *, max_length: int = 240) -> str:
    masked = EMAIL_PATTERN.sub(lambda match: f"{match.group('name')}***@{match.group('domain')}", value)
    masked = PHONE_PATTERN.sub(r"\1****\2", masked)
    if len(masked) > max_length:
        return f"{masked[:max_length]}..."
    return masked


def sanitize_trace_payload(value: Any, *, depth: int = 0) -> Any:
    """Bound and redact trace payloads before they are persisted."""

    if depth >= 6:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _mask_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                result["_truncated"] = True
                break
            key_text = str(key)
            normalized = _normalized_key(key_text)
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                result[key_text] = REDACTED
            else:
                result[key_text] = sanitize_trace_payload(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [sanitize_trace_payload(item, depth=depth + 1) for item in items[:20]]
        if len(items) > 20:
            result.append("[truncated]")
        return result
    return _mask_text(str(value))


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        try:
            return message.model_dump(mode="json")
        except TypeError:
            return message.model_dump()
    return {}


def _result_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"present": value is not None}

    summary: dict[str, Any] = {}
    for key in ("ok", "code", "type", "workflow", "status", "id", "order_no", "risk_level", "requires_approval"):
        if value.get(key) is not None:
            summary[key] = value[key]

    data = value.get("data")
    if isinstance(data, dict):
        summary["data"] = {
            key: data[key]
            for key in ("id", "order_no", "status", "risk_level", "requires_approval", "priority", "type")
            if data.get(key) is not None
        }
    elif isinstance(data, list):
        summary["result_count"] = len(data)

    error = value.get("error")
    if isinstance(error, dict):
        summary["error"] = {key: error[key] for key in ("code", "type", "retryable") if error.get(key) is not None}

    security = value.get("security")
    if isinstance(security, dict):
        summary["security"] = {
            "blocked": bool(security.get("blocked")),
            "signals": list(security.get("signals") or [])[:10],
            "unexpected_tools": list(security.get("unexpected_tools") or [])[:10],
        }
    sources = value.get("sources")
    if isinstance(sources, list):
        summary["source_count"] = len(sources)
    return summary or {"present": True}


def _tool_summaries(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []

    summaries: list[dict[str, Any]] = []
    for message in messages:
        payload = _message_dict(message)
        for call in payload.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
            summaries.append(
                {
                    "tool_name": call.get("name") or "unknown",
                    "tool_call_id": call.get("id"),
                    "argument_names": sorted(str(key) for key in arguments),
                    "status": "called",
                }
            )

        message_type = payload.get("type")
        if message_type != "tool" and not payload.get("tool_call_id"):
            continue
        result: Any = payload.get("content")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                result = {"present": bool(result)}
        summaries.append(
            {
                "tool_name": payload.get("name") or "unknown",
                "tool_call_id": payload.get("tool_call_id"),
                "status": "success" if not isinstance(result, dict) or result.get("ok", True) else "failed",
                "result": _result_summary(result),
            }
        )
    return summaries[:20]


def _usage_summary(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {}
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    model = None
    for message in messages:
        payload = _message_dict(message)
        usage = payload.get("usage_metadata") or {}
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        response_metadata = payload.get("response_metadata") or {}
        model = model or response_metadata.get("model_name") or response_metadata.get("model")
    result: dict[str, Any] = {}
    if input_tokens or output_tokens or total_tokens:
        result.update(
            {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": total_tokens or input_tokens + output_tokens,
            }
        )
    if model:
        result["model"] = model
    return result


def summarize_graph_update(node_name: str, update: Any) -> dict[str, Any]:
    """Extract operational facts while excluding prompts, answers and full tool output."""

    if not isinstance(update, dict):
        return {"updated": True}

    summary: dict[str, Any] = {}
    scalar_fields = (
        "intent",
        "domain",
        "action",
        "ticket_type",
        "intent_confidence",
        "risk_level",
        "requires_order_context",
        "requires_knowledge",
        "order_no",
        "customer_id",
        "refund_amount",
        "ticket_id",
        "repair_count",
    )
    for key in scalar_fields:
        if update.get(key) is not None:
            summary[key] = update[key]
    if update.get("security_signals"):
        summary["security_signals"] = update["security_signals"][:10]

    for key in ("order_context", "knowledge_result", "refund_result", "ticket_result", "approval_result"):
        if update.get(key) is not None:
            summary[key] = _result_summary(update[key])

    quality = update.get("quality_result")
    if isinstance(quality, dict):
        summary["quality_result"] = {
            "passed": quality.get("passed"),
            "risk": quality.get("risk"),
            "issues": quality.get("issues") or [],
        }

    tools = _tool_summaries(update.get("messages"))
    if tools:
        summary["tool_calls"] = tools
    summary.update(_usage_summary(update.get("messages")))

    if update.get("draft_answer") is not None:
        summary["draft_length"] = len(str(update["draft_answer"]))
    if update.get("final_answer") is not None:
        summary["final_length"] = len(str(update["final_answer"]))
    summary["updated_fields"] = sorted(str(key) for key in update if key != "messages")
    return sanitize_trace_payload(summary)


def _business_reference(update: dict[str, Any]) -> tuple[str | None, str | None]:
    candidates = (
        ("refund", update.get("refund_result")),
        ("ticket", update.get("ticket_result")),
        ("order", update.get("order_context")),
        ("approval", update.get("approval_result")),
    )
    for business_type, value in candidates:
        if not isinstance(value, dict):
            continue
        data = value.get("data") if isinstance(value.get("data"), dict) else value
        business_id = data.get("id") if isinstance(data, dict) else None
        if business_id is not None:
            return business_type, str(business_id)
    return None, None


def _node_status(summary: dict[str, Any]) -> str:
    quality = summary.get("quality_result")
    if isinstance(quality, dict) and quality.get("passed") is False:
        return "warning"
    knowledge = summary.get("knowledge_result")
    if isinstance(knowledge, dict) and (knowledge.get("security") or {}).get("blocked"):
        return "warning"
    for key in ("refund_result", "ticket_result", "order_context", "approval_result"):
        result = summary.get(key)
        if isinstance(result, dict) and result.get("ok") is False:
            return "failed"
    return "completed"


@dataclass
class EnterpriseTraceRecorder:
    trace_id: str
    thread_id: str
    tenant_id: int
    user_id: str
    run_id: str | None = None
    agent_name: str = "EnterpriseServiceAgent"
    risk_level: str | None = None
    business_type: str | None = None
    business_id: str | None = None
    _started_at: float = field(default_factory=time.perf_counter)
    _last_event_at: float = field(default_factory=time.perf_counter)

    @classmethod
    async def for_resume(
        cls,
        *,
        thread_id: str,
        tenant_id: int,
        user_id: str,
        fallback_trace_id: str,
        agent_name: str,
    ) -> EnterpriseTraceRecorder:
        trace_id = None
        try:
            async with pg_manager.get_async_session_context() as db:
                trace_id = await EnterpriseTraceRepository(db).get_latest_trace_id_for_thread(tenant_id, thread_id)
        except Exception as exc:
            logger.warning(f"Failed to resolve enterprise trace for thread {thread_id}: {exc}")
        return cls(
            trace_id=trace_id or fallback_trace_id,
            thread_id=thread_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=agent_name,
        )

    async def _record(
        self,
        *,
        event_type: str,
        status: str,
        payload_summary: dict[str, Any] | None = None,
        node_name: str | None = None,
        agent_name: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        try:
            async with pg_manager.get_async_session_context() as db:
                await EnterpriseTraceRepository(db).create_event(
                    trace_id=self.trace_id,
                    thread_id=self.thread_id,
                    run_id=self.run_id,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    event_type=event_type,
                    node_name=node_name,
                    agent_name=agent_name or self.agent_name,
                    business_type=self.business_type,
                    business_id=self.business_id,
                    risk_level=self.risk_level,
                    status=status,
                    latency_ms=latency_ms,
                    payload_summary=sanitize_trace_payload(payload_summary or {}),
                )
        except Exception as exc:
            logger.warning(f"Failed to persist enterprise trace event {event_type}: {exc}")

    async def start(self, *, model: str | None, has_image: bool, agent_config_id: int | None) -> None:
        await self._record(
            event_type="input",
            status="running",
            payload_summary={
                "model": model,
                "has_image": has_image,
                "agent_config_id": agent_config_id,
            },
        )

    async def record_resume(self, payload: dict[str, Any]) -> None:
        await self._record(event_type="resume", status="running", payload_summary=payload)

    async def record_graph_update(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        for node_name, update in payload.items():
            if not isinstance(update, dict):
                update = {}
            now = time.perf_counter()
            latency_ms = max(0, round((now - self._last_event_at) * 1000))
            self._last_event_at = now
            summary = summarize_graph_update(str(node_name), update)
            self.risk_level = str(update.get("risk_level") or self.risk_level or "") or None
            business_type, business_id = _business_reference(update)
            self.business_type = business_type or self.business_type
            self.business_id = business_id or self.business_id
            event_type = NODE_EVENT_TYPES.get(str(node_name), "node")
            await self._record(
                event_type=event_type,
                status=_node_status(summary),
                payload_summary=summary,
                node_name=str(node_name),
                agent_name=NODE_AGENT_NAMES.get(str(node_name), self.agent_name),
                latency_ms=latency_ms,
            )

            tool_calls = summary.get("tool_calls") or []
            completed_tools = [item for item in tool_calls if item.get("status") in {"success", "failed"}]
            timings = list(update.get("tool_timings") or [])
            for item in completed_tools:
                timing = next(
                    (entry for entry in timings if entry.get("tool_name") == item.get("tool_name")),
                    None,
                )
                if timing is not None:
                    timings.remove(timing)
                tool_payload = item | (
                    {"timing_source": "measured", "retrieval": bool(timing.get("retrieval"))}
                    if timing is not None else {}
                )
                await self._record(
                    event_type="tool_call",
                    status="completed" if item.get("status") == "success" else "failed",
                    payload_summary=tool_payload,
                    node_name=str(node_name),
                    agent_name=NODE_AGENT_NAMES.get(str(node_name), self.agent_name),
                    latency_ms=timing.get("duration_ms") if timing is not None else None,
                )

    async def finish(self, status: str, payload_summary: dict[str, Any] | None = None) -> None:
        total_latency_ms = max(0, round((time.perf_counter() - self._started_at) * 1000))
        await self._record(
            event_type="result",
            status=status,
            payload_summary={"total_latency_ms": total_latency_ms} | (payload_summary or {}),
            latency_ms=total_latency_ms,
        )


def build_trace_detail(events: list[Any]) -> dict[str, Any] | None:
    if not events:
        return None
    serialized = [event.to_dict() for event in events]
    latest = serialized[-1]
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    node_latency = 0
    tool_latency = 0
    retrieval_latency = 0
    unmeasured_tool_calls = False
    unmeasured_retrieval = False
    lifecycle_latency = 0
    model = None
    for event in serialized:
        payload = event.get("payload_summary") or {}
        prompt_tokens += int(payload.get("prompt_tokens") or 0)
        completion_tokens += int(payload.get("completion_tokens") or 0)
        total_tokens += int(payload.get("total_tokens") or 0)
        model = model or payload.get("model")
        if event.get("event_type") == "result":
            lifecycle_latency += int(payload.get("total_latency_ms") or 0)
        latency = int(event.get("latency_ms") or 0)
        if event.get("event_type") == "tool_call":
            if payload.get("timing_source") == "measured":
                tool_latency += latency
                if payload.get("retrieval"):
                    retrieval_latency += latency
            else:
                unmeasured_tool_calls = True
                if event.get("node_name") == "knowledge":
                    unmeasured_retrieval = True
        elif event.get("event_type") == "retrieval":
            node_latency += latency
        elif event.get("node_name"):
            node_latency += latency
    return {
        "trace_id": latest["trace_id"],
        "thread_id": latest["thread_id"],
        "run_id": latest["run_id"],
        "tenant_id": latest["tenant_id"],
        "user_id": latest["user_id"],
        "agent_name": latest["agent_name"],
        "business_type": latest["business_type"],
        "business_id": latest["business_id"],
        "risk_level": latest["risk_level"],
        "status": latest["status"],
        "started_at": serialized[0]["created_at"],
        "finished_at": latest["created_at"],
        "event_count": len(serialized),
        "metrics": {
            "latency_ms": lifecycle_latency or node_latency,
            "tool_latency_ms": None if unmeasured_tool_calls else tool_latency,
            "retrieval_latency_ms": None if unmeasured_retrieval else retrieval_latency,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens or prompt_tokens + completion_tokens,
            "model": model,
        },
        "events": serialized,
    }
