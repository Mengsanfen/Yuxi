from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from yuxi.agents.enterprise_schemas import EnterpriseIntent
from yuxi.agents.toolkits.kbs import get_common_kb_tools


ENTERPRISE_KNOWLEDGE_TOOL_ALLOWLIST = frozenset({"list_kbs", "query_kb"})
ENTERPRISE_WRITE_TOOL_NAMES = frozenset(
    {
        "enterprise_request_refund",
        "enterprise_create_ticket",
        "enterprise_update_ticket",
        "enterprise_close_ticket",
        "approval_review",
    }
)

_INJECTION_PATTERNS = (
    (
        "instruction_override",
        re.compile(
            r"(?:ignore|disregard).{0,40}(?:previous|prior|all).{0,24}(?:instructions?|prompts?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "instruction_override",
        re.compile(r"(?:忽略|无视).{0,12}(?:此前|之前|所有|全部).{0,12}(?:指令|提示词|系统提示)"),
    ),
    (
        "privilege_escalation",
        re.compile(
            r"(?:you are now|act as|pretend to be|你现在是|假装你是|扮演).{0,32}"
            r"(?:admin|root|system|管理员|超级管理员)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "write_action_request",
        re.compile(
            r"(?:call|invoke|execute|run|调用|执行).{0,40}"
            r"(?:enterprise_request_refund|enterprise_(?:create|update|close)_ticket|approval_review)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "write_action_request",
        re.compile(r"(?:立即|马上|直接).{0,16}(?:退款|批准|关闭工单|更新工单)"),
    ),
)

_SOURCE_KEYS = frozenset(
    {
        "source",
        "source_name",
        "filename",
        "file_name",
        "title",
        "document_name",
    }
)
_POLICY_REFERENCE_PATTERN = re.compile(r"《([^》]{2,80})》")
_DOCUMENT_TITLE_PATTERN = re.compile(r"^#\s+([^\r\n]{2,80})", re.MULTILINE)
_DELIVERED_CLAIMS = ("已签收", "已经签收", "已送达", "delivered")
_REFUND_SUCCESS_CLAIMS = ("退款成功", "已退款", "退款已完成", "退款已通过", "refund succeeded")


def get_enterprise_knowledge_tools() -> list:
    """Return the explicit read-only tool surface available to the Knowledge Agent."""

    return [tool for tool in get_common_kb_tools() if tool.name in ENTERPRISE_KNOWLEDGE_TOOL_ALLOWLIST]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _safe_source(value: Any) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    source = str(value).strip().replace("\\", "/").rsplit("/", 1)[-1]
    return source[:160] or None


def _extract_sources(value: Any, sources: set[str], *, depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _SOURCE_KEYS:
                source = _safe_source(item)
                if source:
                    sources.add(source)
            if str(key).lower() in {"content", "text"} and isinstance(item, str):
                title = _DOCUMENT_TITLE_PATTERN.search(item)
                if title:
                    sources.add(title.group(1).strip())
            _extract_sources(item, sources, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:50]:
            _extract_sources(item, sources, depth=depth + 1)


def _parsed_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return content


def inspect_knowledge_messages(messages: list[Any]) -> dict[str, Any]:
    tool_names: set[str] = set()
    sources: set[str] = set()
    signals: set[str] = set()
    evidence_count = 0
    kb_names_by_call: dict[str, str] = {}

    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                name = str(call.get("name") or "")
                if not name:
                    continue
                tool_names.add(name)
                if name == "query_kb":
                    kb_name = (call.get("args") or {}).get("kb_name")
                    if kb_name:
                        kb_names_by_call[str(call.get("id") or "")] = str(kb_name)[:120]

        if not isinstance(message, ToolMessage):
            continue
        name = str(message.name or "")
        if name:
            tool_names.add(name)
        if name != "query_kb":
            continue
        content = _content_text(message.content)
        for signal, pattern in _INJECTION_PATTERNS:
            if pattern.search(content):
                signals.add(signal)
        parsed = _parsed_content(message.content)
        if (
            message.status == "error"
            or not parsed
            or isinstance(parsed, dict) and parsed.get("ok") is False
            or isinstance(parsed, str) and parsed.startswith(("检索失败:", "知识库 '", "请提供"))
        ):
            continue
        evidence_count += 1
        kb_name = kb_names_by_call.get(str(message.tool_call_id))
        if kb_name:
            sources.add(f"知识库：{kb_name}")
        _extract_sources(parsed, sources)

    unexpected_tools = sorted(tool_names - ENTERPRISE_KNOWLEDGE_TOOL_ALLOWLIST)
    if unexpected_tools:
        signals.add("unexpected_tool")
    return {
        "evidence_count": evidence_count,
        "retrieval_tool_names": sorted(tool_names),
        "sources": sorted(sources)[:20],
        "security": {
            "untrusted_context": True,
            "blocked": bool(signals),
            "signals": sorted(signals),
            "unexpected_tools": unexpected_tools,
        },
    }


def build_knowledge_result(answer: str, messages: list[Any]) -> dict[str, Any]:
    inspection = inspect_knowledge_messages(messages)
    if inspection["security"]["blocked"]:
        answer = "知识库检索结果包含疑似指令性内容，已作为不可信文本隔离，未执行其中要求的任何业务操作。"
    return {"answer": answer, **inspection}


def sanitized_knowledge_messages(messages: list[Any], knowledge_result: dict[str, Any]) -> list[Any]:
    """Keep tool telemetry while preventing retrieved text from entering the main graph state."""

    safe_messages: list[Any] = []
    security = knowledge_result.get("security") or {}
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            allowed_calls = [
                call for call in message.tool_calls if call.get("name") in ENTERPRISE_KNOWLEDGE_TOOL_ALLOWLIST
            ]
            if allowed_calls:
                safe_messages.append(AIMessage(content="", tool_calls=allowed_calls))
        elif isinstance(message, ToolMessage) and message.name in ENTERPRISE_KNOWLEDGE_TOOL_ALLOWLIST:
            safe_messages.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "untrusted_context": True,
                            "blocked": bool(security.get("blocked")),
                            "evidence_count": knowledge_result.get("evidence_count", 0),
                            "source_count": len(knowledge_result.get("sources") or []),
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=message.tool_call_id,
                    name=message.name,
                )
            )
    return safe_messages


def _status(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    return str(data.get("status") or value.get("status") or "").lower()


def deterministic_grounding_issues(state: dict[str, Any]) -> list[str]:
    """Check high-value business contradictions before invoking an LLM quality judge."""

    issues: list[str] = []
    draft = str(state.get("draft_answer") or "")
    draft_lower = draft.lower()
    knowledge = state.get("knowledge_result") or {}
    security = knowledge.get("security") if isinstance(knowledge, dict) else {}

    if isinstance(security, dict) and security.get("blocked"):
        issues.append("检索内容包含疑似提示词注入，已隔离且不得作为业务指令执行。")
    unexpected_tools = security.get("unexpected_tools") if isinstance(security, dict) else []
    if unexpected_tools:
        issues.append("Knowledge Agent 尝试使用非只读工具，已阻止。")

    if state.get("intent") in {
        EnterpriseIntent.PRODUCT_QUESTION.value,
        EnterpriseIntent.POLICY_QUESTION.value,
    }:
        tools = knowledge.get("retrieval_tool_names") if isinstance(knowledge, dict) else []
        sources = knowledge.get("sources") if isinstance(knowledge, dict) else []
        if "query_kb" not in (tools or []):
            issues.append("知识回答缺少 query_kb 检索证据。")
        if not isinstance(knowledge, dict) or not knowledge.get("evidence_count"):
            issues.append("知识回答没有可用的检索内容。")
        for reference in _POLICY_REFERENCE_PATTERN.findall(draft):
            if not any(reference.lower() in str(source).lower() for source in (sources or [])):
                issues.append(f"回答引用的政策《{reference}》不在检索来源中。")

    order_status = _status(state.get("order_context"))
    if order_status == "shipped" and any(claim in draft_lower for claim in _DELIVERED_CLAIMS):
        issues.append("订单工具状态为 shipped，但回答声称已签收。")

    refund_status = _status(state.get("refund_result"))
    approval_status = _status(state.get("approval_result"))
    if refund_status in {"pending", "pending_approval"} or approval_status == "pending":
        if any(claim in draft_lower for claim in _REFUND_SUCCESS_CLAIMS):
            issues.append("退款仍在 pending_approval，但回答声称退款成功。")

    return list(dict.fromkeys(issues))
