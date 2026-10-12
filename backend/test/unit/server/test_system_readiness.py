import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.routers import system_router


@pytest.mark.parametrize(
    ("postgres_ready", "redis_ready", "expected_status"),
    [(True, True, 200), (False, True, 503), (True, False, 503)],
)
def test_readiness_reflects_critical_dependencies(monkeypatch, postgres_ready, redis_ready, expected_status):
    async def check_postgres():
        return postgres_ready

    async def check_redis():
        return redis_ready

    monkeypatch.setattr(system_router, "_check_postgres_ready", check_postgres)
    monkeypatch.setattr(system_router, "_check_redis_ready", check_redis)

    response = TestClient(app).get("/api/system/ready")

    assert response.status_code == expected_status
    expected_body = {
        "status": "ok" if expected_status == 200 else "not_ready",
        "checks": {"postgres": postgres_ready, "redis": redis_ready},
    }
    if expected_status == 503:
        expected_body["message"] = "后端依赖服务暂不可用"
    assert response.json() == expected_body


@pytest.mark.asyncio
async def test_postgres_probe_fails_when_manager_is_not_initialized(monkeypatch):
    monkeypatch.setattr(system_router.pg_manager, "_initialized", False)

    assert await system_router._check_postgres_ready() is False


@pytest.mark.asyncio
async def test_redis_probe_reports_connection_failure(monkeypatch):
    async def unavailable_redis():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(system_router, "get_redis_client", unavailable_redis)

    assert await system_router._check_redis_ready() is False
