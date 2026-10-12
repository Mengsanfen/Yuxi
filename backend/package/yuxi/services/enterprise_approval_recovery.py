from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from yuxi.services.enterprise_approval_runtime import resume_reviewed_approval
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import ApprovalResume, ApprovalStatus, ApprovalTask
from yuxi.utils.datetime_utils import utc_now_naive

MAX_RESUME_ATTEMPTS = 5


async def _graph_already_resumed(task: ApprovalTask) -> bool:
    from yuxi.agents.buildin import agent_manager

    graph = await agent_manager.get_agent(task.agent_id).get_graph()
    snapshot = await graph.aget_state({
        "configurable": {"thread_id": task.thread_id, "user_id": task.requested_by}
    })
    if not snapshot or snapshot.next:
        return False
    approval = (snapshot.values or {}).get("approval_result") or {}
    return approval.get("id") == task.id and approval.get("status") == task.status.value


async def attempt_approval_resume(task_id: int) -> dict:
    """Serialize retries for one approval while keeping business review immutable."""
    async with pg_manager.get_async_session_context() as state_db:
        record = (
            await state_db.execute(
                select(ApprovalResume).where(ApprovalResume.approval_task_id == task_id).with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            return {"attempted": False, "status": "not_linked"}
        if record.status == "success":
            return {"attempted": False, "status": "finished"}
        if record.attempts >= MAX_RESUME_ATTEMPTS:
            return {"attempted": False, "status": "exhausted"}

        task = (
            await state_db.execute(
                select(ApprovalTask).where(
                    ApprovalTask.id == task_id,
                    ApprovalTask.tenant_id == record.tenant_id,
                )
            )
        ).scalar_one()
        if task.status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            return {"attempted": False, "status": "approval_pending"}

        record.attempts += 1
        record.updated_at = utc_now_naive()
        try:
            if await _graph_already_resumed(task):
                result = {"attempted": False, "status": "finished"}
            else:
                async with pg_manager.get_async_session_context() as runtime_db:
                    result = await resume_reviewed_approval(task=task, decision=task.status, db=runtime_db)
        except Exception as exc:
            result = {"attempted": True, "status": "error", "error": str(exc)}

        if result.get("status") == "finished":
            record.status = "success"
            record.last_error = None
            record.resumed_at = utc_now_naive()
        else:
            record.status = "failed"
            record.last_error = str(result.get("error") or result.get("status") or "unknown")[:500]
        record.updated_at = utc_now_naive()
        return result


async def enqueue_failed_approval_resume(task_id: int) -> None:
    from yuxi.services.run_queue_service import get_arq_pool

    queue = await get_arq_pool()
    await queue.enqueue_job(
        "retry_approval_resume",
        task_id,
        _job_id=f"approval-resume:{task_id}",
        _defer_by=timedelta(seconds=15),
    )


async def retry_approval_resume(ctx, task_id: int) -> None:
    del ctx
    await attempt_approval_resume(task_id)


async def reconcile_approval_resumes(ctx) -> None:
    async with pg_manager.get_async_session_context() as db:
        task_ids = list(
            (
                await db.execute(
                    select(ApprovalResume.approval_task_id)
                    .where(
                        ApprovalResume.status.in_(["pending", "failed"]),
                        ApprovalResume.attempts < MAX_RESUME_ATTEMPTS,
                    )
                    .order_by(ApprovalResume.updated_at, ApprovalResume.approval_task_id)
                    .limit(100)
                )
            ).scalars()
        )
    for task_id in task_ids:
        await ctx["redis"].enqueue_job(
            "retry_approval_resume",
            task_id,
            _job_id=f"approval-resume:{task_id}",
        )
