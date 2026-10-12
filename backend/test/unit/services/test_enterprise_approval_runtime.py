from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yuxi.services import enterprise_approval_runtime
from yuxi.storage.postgres.models_business import ApprovalStatus, ApprovalTask, User


class _Result:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class _Db:
    def __init__(self, user):
        self.user = user

    async def execute(self, statement):
        return _Result(self.user)


@pytest.mark.asyncio
async def test_reviewed_approval_resumes_original_graph(monkeypatch):
    task = ApprovalTask(
        id=17,
        tenant_id=2,
        business_type="refund",
        business_id=8,
        requested_by="42",
        status="approved",
        idempotency_key="refund:8",
        thread_id="thread-approval",
        agent_id="EnterpriseServiceAgent",
        agent_config_id=9,
    )
    requester = User(id=42, department_id=2, role="user", user_id="requester")
    captured = {}

    async def fake_stream_agent_resume(**kwargs):
        captured.update(kwargs)
        for status in ("init", "finished"):
            yield (json.dumps({"status": status}) + "\n").encode()

    monkeypatch.setattr(
        enterprise_approval_runtime,
        "stream_agent_resume",
        fake_stream_agent_resume,
    )

    result = await enterprise_approval_runtime.resume_reviewed_approval(
        task=task,
        decision=ApprovalStatus.APPROVED,
        db=_Db(requester),
    )

    assert result == {"attempted": True, "status": "finished"}
    assert captured["thread_id"] == "thread-approval"
    assert captured["agent_id"] == "EnterpriseServiceAgent"
    assert captured["resume_input"] == "approved"
    assert captured["config"] == {"agent_config_id": 9}
    assert captured["current_user"] is requester


@pytest.mark.asyncio
async def test_unlinked_approval_does_not_attempt_resume():
    task = SimpleNamespace(
        thread_id=None,
        agent_id=None,
        requested_by="42",
    )

    result = await enterprise_approval_runtime.resume_reviewed_approval(
        task=task,
        decision=ApprovalStatus.REJECTED,
        db=_Db(None),
    )

    assert result == {"attempted": False, "status": "not_linked"}
