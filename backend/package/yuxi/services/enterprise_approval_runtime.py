from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.chat_service import stream_agent_resume
from yuxi.storage.postgres.models_business import ApprovalStatus, ApprovalTask, User
from yuxi.utils import logger


async def resume_reviewed_approval(
    *,
    task: ApprovalTask,
    decision: ApprovalStatus,
    db: AsyncSession,
) -> dict:
    """Resume an interrupted enterprise graph after an administrator review."""
    if not task.thread_id or not task.agent_id or not task.requested_by:
        return {"attempted": False, "status": "not_linked"}

    try:
        requester_id = int(task.requested_by)
    except (TypeError, ValueError):
        return {"attempted": False, "status": "invalid_requester"}

    result = await db.execute(select(User).where(User.id == requester_id, User.is_deleted == 0))
    requester = result.scalar_one_or_none()
    if requester is None:
        return {"attempted": False, "status": "requester_not_found"}

    last_status = "unknown"
    error_message = None
    try:
        stream = stream_agent_resume(
            agent_id=task.agent_id,
            thread_id=task.thread_id,
            resume_input=decision.value,
            meta={
                "request_id": str(uuid.uuid4()),
                "approval_task_id": task.id,
                "thread_id": task.thread_id,
                "agent_id": task.agent_id,
                "review_decision": decision.value,
            },
            config={"agent_config_id": task.agent_config_id},
            current_user=requester,
            db=db,
        )
        async for chunk_bytes in stream:
            for line in chunk_bytes.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                last_status = str(payload.get("status") or last_status)
                error_message = payload.get("error_message") or payload.get("message") or error_message
    except Exception as exc:
        logger.error(f"Failed to resume approval task {task.id}: {exc}")
        return {"attempted": True, "status": "error", "error": str(exc)}

    response = {"attempted": True, "status": last_status}
    if error_message and last_status == "error":
        response["error"] = error_message
    return response
