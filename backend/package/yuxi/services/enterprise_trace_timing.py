from __future__ import annotations

from contextvars import ContextVar
from time import perf_counter


active_tool_timings: ContextVar[list[dict] | None] = ContextVar("enterprise_tool_timings", default=None)


def measured_tool_timing(name: str, started_at: float, *, retrieval: bool = False) -> dict:
    return {
        "tool_name": name,
        "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        "retrieval": retrieval,
    }


def record_tool_timing(name: str, started_at: float, *, retrieval: bool = False) -> None:
    timings = active_tool_timings.get()
    if timings is not None:
        timings.append(measured_tool_timing(name, started_at, retrieval=retrieval))
