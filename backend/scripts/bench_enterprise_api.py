"""Small, read-only HTTP load probe for enterprise APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


async def measure_route(
    client: httpx.AsyncClient, path: str, *, requests: int, concurrency: int
) -> dict:
    semaphore = asyncio.Semaphore(concurrency)

    async def request_once() -> tuple[int, float]:
        async with semaphore:
            started = perf_counter()
            response = await client.get(path)
            return response.status_code, (perf_counter() - started) * 1000

    for _ in range(min(3, requests)):
        response = await client.get(path)
        response.raise_for_status()

    started = perf_counter()
    results = await asyncio.gather(*(request_once() for _ in range(requests)))
    elapsed = perf_counter() - started
    statuses = Counter(status for status, _ in results)
    latencies = [latency for _, latency in results]
    return {
        "path": path,
        "requests": requests,
        "max_concurrency": concurrency,
        "status_counts": dict(statuses),
        "error_count": sum(count for status, count in statuses.items() if status >= 400),
        "elapsed_seconds": round(elapsed, 2),
        "requests_per_second": round(requests / elapsed, 2),
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
    }


async def main(args: argparse.Namespace) -> None:
    username = os.getenv("TEST_USERNAME")
    password = os.getenv("TEST_PASSWORD")
    if not username or not password:
        if os.getenv("YUXI_SEED_DEFAULT_ACCOUNTS", "").lower() not in {"true", "1"}:
            raise RuntimeError("Set TEST_USERNAME and TEST_PASSWORD for the load probe")
        from yuxi.services.identity_seed_service import DEFAULT_SEED_PASSWORD, DEFAULT_USERS

        username = next(item.user_id for item in DEFAULT_USERS if item.role == "superadmin")
        password = DEFAULT_SEED_PASSWORD

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        login = await client.post("/api/auth/token", data={"username": username, "password": password})
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

        paths = {
            "order_query": f"/api/enterprise/orders/by-no/{args.order_no}",
            "approval_list": "/api/enterprise/approvals?limit=20",
            "trace_list": "/api/enterprise/traces?limit=20",
        }
        results = {}
        for name, path in paths.items():
            results[name] = await measure_route(
                client, path, requests=args.requests, concurrency=args.concurrency
            )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:5050")
    parser.add_argument("--order-no", default="NM-DEMO-2026-0001")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=3)
    options = parser.parse_args()
    if options.requests < 1 or options.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    asyncio.run(main(options))
