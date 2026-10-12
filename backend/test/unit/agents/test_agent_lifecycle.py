from __future__ import annotations

import pytest

from yuxi.agents.base import BaseAgent
from yuxi.agents.buildin import AgentManager


class _TestAgent(BaseAgent):
    async def get_graph(self, **kwargs):
        return None


_TestAgent.__module__ = "yuxi.agents.tests.fake"


class _FakeConnection:
    def __init__(self):
        self.close_count = 0

    async def close(self):
        self.close_count += 1


@pytest.mark.asyncio
async def test_agent_close_releases_sqlite_connection_and_cached_checkpoint():
    agent = _TestAgent()
    connection = _FakeConnection()
    agent._async_conn = connection
    agent.checkpointer = object()
    agent.graph = object()

    await agent.close()
    await agent.close()

    assert connection.close_count == 1
    assert agent._async_conn is None
    assert agent.checkpointer is None
    assert agent.graph is None


@pytest.mark.asyncio
async def test_agent_manager_closes_instantiated_agents(monkeypatch):
    manager = AgentManager()
    first = _TestAgent()
    second = _TestAgent()
    first_connection = _FakeConnection()
    second_connection = _FakeConnection()
    first._async_conn = first_connection
    second._async_conn = second_connection
    monkeypatch.setattr(manager, "_instances", {"first": first, "second": second})

    await manager.close_all()

    assert first_connection.close_count == 1
    assert second_connection.close_count == 1


@pytest.mark.asyncio
async def test_agent_reload_keeps_live_checkpoint_connection(monkeypatch):
    manager = AgentManager()
    agent = _TestAgent()
    connection = _FakeConnection()
    agent._async_conn = connection
    agent.checkpointer = object()
    agent.graph = object()
    monkeypatch.setattr(manager, "_instances", {"test": agent})

    await manager.reload_all()

    assert manager.get_agent("test") is agent
    assert agent.graph is None
    assert agent.checkpointer is not None
    assert agent._async_conn is connection
    assert connection.close_count == 0
