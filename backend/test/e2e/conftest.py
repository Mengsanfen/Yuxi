from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(PROJECT_ROOT / "test/.env.test", override=False)

from yuxi.services.identity_seed_service import DEFAULT_SEED_PASSWORD, DEFAULT_USERS  # noqa: E402

E2E_BASE_URL = os.getenv("TEST_BASE_URL", os.getenv("API_BASE_URL", "http://localhost:5050")).rstrip("/")
DEFAULT_DEMO_ACCOUNTS_FLAG = "true" if os.getenv("RUNNING_IN_DOCKER") == "true" else "false"
DEMO_ACCOUNTS_ENABLED = os.getenv("YUXI_SEED_DEFAULT_ACCOUNTS", DEFAULT_DEMO_ACCOUNTS_FLAG).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEMO_SUPERADMIN = next(item for item in DEFAULT_USERS if item.role == "superadmin")
E2E_USERNAME = (
    os.getenv("E2E_USERNAME")
    or os.getenv("TEST_USERNAME")
    or (DEMO_SUPERADMIN.user_id if DEMO_ACCOUNTS_ENABLED else None)
)
E2E_PASSWORD = (
    os.getenv("E2E_PASSWORD")
    or os.getenv("TEST_PASSWORD")
    or (DEFAULT_SEED_PASSWORD if DEMO_ACCOUNTS_ENABLED else None)
)
E2E_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _require_e2e_credentials() -> tuple[str, str]:
    if not E2E_USERNAME or not E2E_PASSWORD:
        pytest.skip(
            "E2E credentials are not configured. Set E2E_USERNAME / E2E_PASSWORD, TEST_USERNAME / "
            "TEST_PASSWORD, or enable the local seeded demo account with YUXI_DEFAULT_ACCOUNT_PASSWORD."
        )
    return E2E_USERNAME, E2E_PASSWORD


@pytest.fixture(scope="session")
def e2e_base_url() -> str:
    return E2E_BASE_URL


@pytest_asyncio.fixture(scope="function")
async def e2e_client(e2e_base_url: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=e2e_base_url, timeout=E2E_TIMEOUT, follow_redirects=True) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def e2e_headers(e2e_client: httpx.AsyncClient) -> dict[str, str]:
    username, password = _require_e2e_credentials()
    response = await e2e_client.post("/api/auth/token", data={"username": username, "password": password})
    if response.status_code != 200:
        pytest.fail(f"E2E login failed (status={response.status_code}): {response.text}")

    access_token = response.json().get("access_token")
    if not access_token:
        pytest.fail("E2E login succeeded but no access token was returned.")
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture(scope="function")
async def e2e_agent_context(e2e_client: httpx.AsyncClient, e2e_headers: dict[str, str]) -> dict[str, str | int]:
    me_response = await e2e_client.get("/api/auth/me", headers=e2e_headers)
    if me_response.status_code != 200:
        pytest.fail(
            f"Failed to fetch current user for E2E tests (status={me_response.status_code}): {me_response.text}"
        )
    user_id = me_response.json().get("id")
    if user_id is None:
        pytest.fail("Current user payload missing id field for E2E tests.")

    default_response = await e2e_client.get("/api/chat/default_agent", headers=e2e_headers)
    default_agent_id = None
    if default_response.status_code == 200:
        default_agent_id = default_response.json().get("default_agent_id")

    if default_agent_id:
        agent_id = str(default_agent_id)
    else:
        response = await e2e_client.get("/api/chat/agent", headers=e2e_headers)
        if response.status_code != 200:
            pytest.fail(f"Failed to list agents for E2E tests (status={response.status_code}): {response.text}")
        agents = response.json().get("agents") or []
        if not agents:
            pytest.fail("No agents are available for E2E tests.")
        agent_id = str(agents[0]["id"])

    config_response = await e2e_client.get(f"/api/chat/agent/{agent_id}/configs", headers=e2e_headers)
    if config_response.status_code != 200:
        pytest.fail(
            f"Failed to list agent configs for E2E tests (status={config_response.status_code}): {config_response.text}"
        )

    configs = config_response.json().get("configs") or []
    if not configs:
        pytest.fail(f"No agent configs are available for E2E tests under agent {agent_id}.")

    config_id = configs[0].get("id")
    if not config_id:
        pytest.fail(f"Agent config payload missing id field for agent {agent_id}.")

    return {"agent_id": agent_id, "agent_config_id": int(config_id), "user_id": int(user_id)}
