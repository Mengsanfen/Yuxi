from __future__ import annotations

from types import SimpleNamespace

import pytest

from yuxi.services import tool_service


def test_get_tool_metadata_includes_config_guide(monkeypatch):
    tool_service._metadata_cache.clear()

    fake_tool = SimpleNamespace(
        name="demo_tool",
        description="demo description",
        metadata={},
        args_schema=None,
    )
    fake_extra = SimpleNamespace(
        category="buildin",
        tags=["demo"],
        display_name="演示工具",
        config_guide="请先配置 DEMO_API_KEY",
    )

    monkeypatch.setattr(
        "yuxi.agents.toolkits.registry.get_all_tool_instances",
        lambda: [fake_tool],
    )
    monkeypatch.setattr(
        "yuxi.agents.toolkits.registry.get_all_extra_metadata",
        lambda: {"demo_tool": fake_extra},
    )

    result = tool_service.get_tool_metadata()

    assert result == [
        {
            "id": "demo_tool",
            "name": "演示工具",
            "description": "demo description",
            "metadata": {},
            "args": [],
            "category": "buildin",
            "tags": ["demo"],
            "config_guide": "请先配置 DEMO_API_KEY",
        }
    ]

    tool_service._metadata_cache.clear()


def test_tool_metadata_uses_public_call_schema(monkeypatch):
    monkeypatch.setattr(tool_service, "_metadata_cache", [])
    fake_tool = SimpleNamespace(
        name="runtime_tool",
        description="runtime tool",
        metadata={},
        args_schema=SimpleNamespace(model_json_schema=lambda: pytest.fail("runtime schema must not be used")),
        tool_call_schema={
            "properties": {"query": {"type": "string", "description": "Search query"}},
        },
    )
    monkeypatch.setattr("yuxi.agents.toolkits.registry.get_all_tool_instances", lambda: [fake_tool])
    monkeypatch.setattr("yuxi.agents.toolkits.registry.get_all_extra_metadata", lambda: {})

    result = tool_service.get_tool_metadata()

    assert result[0]["args"] == [{"name": "query", "type": "string", "description": "Search query"}]


def test_tool_metadata_cache_is_not_partial_after_schema_error(monkeypatch):
    monkeypatch.setattr(tool_service, "_metadata_cache", [])
    valid_tool = SimpleNamespace(name="first", description="first", metadata={}, tool_call_schema=None)

    def invalid_schema():
        raise ValueError("invalid tool schema")

    broken_tool = SimpleNamespace(
        name="second",
        description="second",
        metadata={},
        tool_call_schema=SimpleNamespace(model_json_schema=invalid_schema),
    )
    monkeypatch.setattr("yuxi.agents.toolkits.registry.get_all_tool_instances", lambda: [valid_tool, broken_tool])
    monkeypatch.setattr("yuxi.agents.toolkits.registry.get_all_extra_metadata", lambda: {})

    with pytest.raises(ValueError, match="invalid tool schema"):
        tool_service.get_tool_metadata()

    assert tool_service._metadata_cache == []

    broken_tool.tool_call_schema = None
    assert [tool["id"] for tool in tool_service.get_tool_metadata()] == ["first", "second"]
