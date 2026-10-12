from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import Department, EnterpriseTraceEvent

pytestmark = [pytest.mark.integration, pytest.mark.auth]


@pytest.mark.asyncio
async def test_enterprise_trace_endpoints_are_tenant_scoped(test_client, admin_headers):
    suffix = uuid.uuid4().hex[:10]
    trace_id = f"pytest-trace-{suffix}"
    foreign_trace_id = f"pytest-foreign-trace-{suffix}"
    thread_id = f"pytest-thread-{suffix}"
    created_event_ids: list[int] = []
    foreign_department_id = None

    me_response = await test_client.get("/api/auth/me", headers=admin_headers)
    assert me_response.status_code == 200, me_response.text
    current_user = me_response.json()
    if not pg_manager._initialized:
        pg_manager.initialize()

    try:
        async with pg_manager.get_async_session_context() as session:
            foreign_department = Department(name=f"pytest-trace-tenant-{suffix}")
            session.add(foreign_department)
            await session.flush()
            foreign_department_id = foreign_department.id

            events = [
                EnterpriseTraceEvent(
                    trace_id=trace_id,
                    thread_id=thread_id,
                    tenant_id=current_user["department_id"],
                    user_id=str(current_user["id"]),
                    event_type="input",
                    agent_name="EnterpriseServiceAgent",
                    risk_level="low",
                    status="running",
                    payload_summary={"model": "pytest-model"},
                ),
                EnterpriseTraceEvent(
                    trace_id=trace_id,
                    thread_id=thread_id,
                    tenant_id=current_user["department_id"],
                    user_id=str(current_user["id"]),
                    event_type="result",
                    agent_name="EnterpriseServiceAgent",
                    business_type="order",
                    business_id="42",
                    risk_level="low",
                    status="completed",
                    latency_ms=180,
                    payload_summary={"total_latency_ms": 180},
                ),
                EnterpriseTraceEvent(
                    trace_id=foreign_trace_id,
                    thread_id=f"foreign-{thread_id}",
                    tenant_id=foreign_department.id,
                    user_id="foreign-user",
                    event_type="result",
                    agent_name="EnterpriseServiceAgent",
                    status="completed",
                    payload_summary={"total_latency_ms": 99},
                ),
            ]
            session.add_all(events)
            await session.flush()
            created_event_ids.extend(event.id for event in events)

        list_response = await test_client.get(
            "/api/enterprise/traces?status=completed&limit=100",
            headers=admin_headers,
        )
        assert list_response.status_code == 200, list_response.text
        listed_ids = {item["trace_id"] for item in list_response.json()["items"]}
        assert trace_id in listed_ids
        assert foreign_trace_id not in listed_ids

        detail_response = await test_client.get(
            f"/api/enterprise/traces/{trace_id}",
            headers=admin_headers,
        )
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["business_type"] == "order"
        assert detail["business_id"] == "42"
        assert detail["metrics"]["latency_ms"] == 180
        assert detail["event_count"] == 2

        thread_response = await test_client.get(
            f"/api/enterprise/threads/{thread_id}/trace",
            headers=admin_headers,
        )
        assert thread_response.status_code == 200, thread_response.text
        assert thread_response.json()["trace_id"] == trace_id

        isolated_response = await test_client.get(
            f"/api/enterprise/traces/{foreign_trace_id}",
            headers=admin_headers,
        )
        assert isolated_response.status_code == 404
    finally:
        async with pg_manager.get_async_session_context() as session:
            if created_event_ids:
                await session.execute(
                    delete(EnterpriseTraceEvent).where(EnterpriseTraceEvent.id.in_(created_event_ids))
                )
            if foreign_department_id:
                await session.execute(delete(Department).where(Department.id == foreign_department_id))
