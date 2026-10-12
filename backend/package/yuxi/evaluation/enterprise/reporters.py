from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .metrics import _percentile
from .schemas import EnterpriseEvalReport


def _display_metric(value: int | float | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def render_markdown(report: EnterpriseEvalReport) -> str:
    lines = [
        "# Enterprise Agent Evaluation",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Dataset: `{report.dataset}`",
        f"- Model: `{report.model}`",
        f"- Cases: `{len(report.cases)}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {_display_metric(value)} |" for name, value in report.metrics.items())
    by_category = defaultdict(list)
    for result in report.cases:
        by_category[result.case.category].append(result.observation)
    lines.extend([
        "",
        "## Request Profile",
        "",
        "| Category | Cases | Avg LLM | Avg Tools | Avg RAG | Avg Quality | P50 (ms) | P95 (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for category, observations in by_category.items():
        count = len(observations)
        averages = [
            sum(getattr(item, field) for item in observations) / count
            for field in ("llm_call_count", "tool_call_count", "retrieval_call_count", "quality_call_count")
        ]
        latencies = [item.latency_ms for item in observations]
        lines.append(
            f"| {category} | {count} | "
            + " | ".join(f"{value:.2f}" for value in averages)
            + f" | {_percentile(latencies, 0.5):.2f} | {_percentile(latencies, 0.95):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Category | Intent | Status | Latency (ms) | Result |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for result in report.cases:
        observation = result.observation
        lines.append(
            "| {case_id} | {category} | {intent} | {status} | {latency:.2f} | {passed} |".format(
                case_id=result.case.id,
                category=result.case.category,
                intent=observation.actual_intent or "N/A",
                status=observation.final_status,
                latency=observation.latency_ms,
                passed="PASS" if result.passed else "FAIL",
            )
        )
    failed = [result for result in report.cases if not result.passed]
    if failed:
        lines.extend(["", "## Failed Checks", ""])
        for result in failed:
            failures = []
            for name, value in result.checks.items():
                if name == "forbidden_tool_violation":
                    if value is True:
                        failures.append(name)
                elif name.startswith("tool_selection_"):
                    if value != 1.0:
                        failures.append(name)
                elif name != "tool_execution_success_rate" and value is False:
                    failures.append(name)
            detail = ", ".join(failures) or result.observation.error or "unknown"
            lines.append(f"- `{result.case.id}`: {detail}")
    if report.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines) + "\n"


def write_reports(report: EnterpriseEvalReport, output_base: Path) -> tuple[Path, Path]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_base.with_suffix(".json")
    markdown_path = output_base.with_suffix(".md")
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
