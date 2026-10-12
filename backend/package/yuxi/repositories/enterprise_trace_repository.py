from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import EnterpriseTraceEvent


class EnterpriseTraceRepository:
    """Tenant-scoped persistence for sanitized enterprise execution traces."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create_event(self, **data) -> EnterpriseTraceEvent:
        event = EnterpriseTraceEvent(**data)
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_latest_events(
        self,
        tenant_id: int,
        *,
        status: str | None = None,
        risk_level: str | None = None,
        thread_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[EnterpriseTraceEvent]:
        latest_ids = (
            select(func.max(EnterpriseTraceEvent.id).label("event_id"))
            .where(EnterpriseTraceEvent.tenant_id == tenant_id)
            .group_by(EnterpriseTraceEvent.trace_id)
            .subquery()
        )
        stmt = select(EnterpriseTraceEvent).where(EnterpriseTraceEvent.id.in_(select(latest_ids.c.event_id)))
        if status:
            stmt = stmt.where(EnterpriseTraceEvent.status == status)
        if risk_level:
            stmt = stmt.where(EnterpriseTraceEvent.risk_level == risk_level)
        if thread_id:
            stmt = stmt.where(EnterpriseTraceEvent.thread_id == thread_id)
        result = await self.db.execute(
            stmt.order_by(EnterpriseTraceEvent.created_at.desc(), EnterpriseTraceEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_traces(
        self,
        tenant_id: int,
        *,
        status: str | None = None,
        risk_level: str | None = None,
        thread_id: str | None = None,
    ) -> int:
        latest_ids = (
            select(func.max(EnterpriseTraceEvent.id).label("event_id"))
            .where(EnterpriseTraceEvent.tenant_id == tenant_id)
            .group_by(EnterpriseTraceEvent.trace_id)
            .subquery()
        )
        stmt = (
            select(func.count())
            .select_from(EnterpriseTraceEvent)
            .where(EnterpriseTraceEvent.id.in_(select(latest_ids.c.event_id)))
        )
        if status:
            stmt = stmt.where(EnterpriseTraceEvent.status == status)
        if risk_level:
            stmt = stmt.where(EnterpriseTraceEvent.risk_level == risk_level)
        if thread_id:
            stmt = stmt.where(EnterpriseTraceEvent.thread_id == thread_id)
        result = await self.db.execute(stmt)
        return int(result.scalar_one())

    async def get_events(self, tenant_id: int, trace_id: str) -> list[EnterpriseTraceEvent]:
        result = await self.db.execute(
            select(EnterpriseTraceEvent)
            .where(
                EnterpriseTraceEvent.tenant_id == tenant_id,
                EnterpriseTraceEvent.trace_id == trace_id,
            )
            .order_by(EnterpriseTraceEvent.created_at.asc(), EnterpriseTraceEvent.id.asc())
        )
        return list(result.scalars().all())

    async def get_events_for_traces(
        self,
        tenant_id: int,
        trace_ids: list[str],
    ) -> dict[str, list[EnterpriseTraceEvent]]:
        if not trace_ids:
            return {}
        result = await self.db.execute(
            select(EnterpriseTraceEvent)
            .where(
                EnterpriseTraceEvent.tenant_id == tenant_id,
                EnterpriseTraceEvent.trace_id.in_(trace_ids),
            )
            .order_by(
                EnterpriseTraceEvent.trace_id.asc(),
                EnterpriseTraceEvent.created_at.asc(),
                EnterpriseTraceEvent.id.asc(),
            )
        )
        grouped = {trace_id: [] for trace_id in trace_ids}
        for event in result.scalars().all():
            grouped[event.trace_id].append(event)
        return grouped

    async def get_latest_trace_id_for_thread(self, tenant_id: int, thread_id: str) -> str | None:
        result = await self.db.execute(
            select(EnterpriseTraceEvent.trace_id)
            .where(
                EnterpriseTraceEvent.tenant_id == tenant_id,
                EnterpriseTraceEvent.thread_id == thread_id,
            )
            .order_by(EnterpriseTraceEvent.created_at.desc(), EnterpriseTraceEvent.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
