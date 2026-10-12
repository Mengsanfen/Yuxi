from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from yuxi.services import enterprise_approval_recovery
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import ApprovalResume, ApprovalStatus, ApprovalTask, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_failed_resume_is_retried_by_worker_and_becomes_success(monkeypatch):
    if not pg_manager._initialized:
        pg_manager.initialize()
    await pg_manager.async_engine.dispose()
    await pg_manager.create_business_tables()
    async with pg_manager.get_async_session_context() as db:
        actor = (
            await db.execute(select(User).where(User.role == "superadmin", User.is_deleted == 0).limit(1))
        ).scalar_one()
        task = ApprovalTask(
            tenant_id=actor.department_id,
            business_type="refund",
            business_id=999999,
            requested_by=str(actor.id),
            status=ApprovalStatus.APPROVED,
            idempotency_key=f"resume-test-{uuid.uuid4().hex}",
            thread_id=f"resume-test-{uuid.uuid4().hex}",
            agent_id="EnterpriseServiceAgent",
            agent_config_id=1,
        )
        db.add(task)
        await db.flush()
        task_id = task.id
        db.add(ApprovalResume(approval_task_id=task_id, tenant_id=actor.department_id))

    attempts = []

    async def fake_resume_reviewed_approval(**kwargs):
        attempts.append(kwargs["task"].id)
        if len(attempts) == 1:
            return {"attempted": True, "status": "error", "error": "temporary graph outage"}
        return {"attempted": True, "status": "finished"}

    monkeypatch.setattr(enterprise_approval_recovery, "resume_reviewed_approval", fake_resume_reviewed_approval)
    async def graph_not_finished(task):
        return False

    monkeypatch.setattr(enterprise_approval_recovery, "_graph_already_resumed", graph_not_finished)

    try:
        first = await enterprise_approval_recovery.attempt_approval_resume(task_id)
        assert first["status"] == "error"
        async with pg_manager.get_async_session_context() as db:
            record = (await db.execute(select(ApprovalResume).where(
                ApprovalResume.approval_task_id == task_id
            ))).scalar_one()
            assert record.status == "failed"
            assert record.attempts == 1

        enqueued = []

        class _Queue:
            async def enqueue_job(self, *args, **kwargs):
                enqueued.append((args, kwargs))

        await enterprise_approval_recovery.reconcile_approval_resumes({"redis": _Queue()})
        assert any(args == ("retry_approval_resume", task_id) for args, _ in enqueued)

        await enterprise_approval_recovery.retry_approval_resume({}, task_id)
        replay = await enterprise_approval_recovery.attempt_approval_resume(task_id)
        assert replay == {"attempted": False, "status": "finished"}
        assert attempts == [task_id, task_id]
        async with pg_manager.get_async_session_context() as db:
            record = (await db.execute(select(ApprovalResume).where(
                ApprovalResume.approval_task_id == task_id
            ))).scalar_one()
            assert record.status == "success"
            assert record.attempts == 2
            assert record.last_error is None
            assert record.resumed_at is not None

        async with pg_manager.get_async_session_context() as db:
            record = (await db.execute(select(ApprovalResume).where(
                ApprovalResume.approval_task_id == task_id
            ))).scalar_one()
            record.status = "failed"

        async def graph_finished(task):
            return True

        monkeypatch.setattr(enterprise_approval_recovery, "_graph_already_resumed", graph_finished)
        replay_after_crash = await enterprise_approval_recovery.attempt_approval_resume(task_id)
        assert replay_after_crash == {"attempted": False, "status": "finished"}
        assert attempts == [task_id, task_id]
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(ApprovalResume).where(ApprovalResume.approval_task_id == task_id))
            await db.execute(delete(ApprovalTask).where(ApprovalTask.id == task_id))
        await pg_manager.async_engine.dispose()
