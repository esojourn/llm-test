"""Report generation — Rich terminal and JSON output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .client import APIResponse
from .probes import ProbeResult
from .scoring import RunResult, Verdict

CLASSIFICATION_COLORS = {
    "GENUINE_OPUS": "bold green",
    "LIKELY_OPUS": "green",
    "SUSPICIOUS": "yellow",
    "LIKELY_DOWNGRADE": "red",
    "DEFINITE_DOWNGRADE": "bold red",
    "ERROR": "bold magenta",
}


def print_report(results: dict[str, RunResult], console: Console | None = None) -> None:
    """Print a rich terminal report."""
    console = console or Console()

    console.print()
    console.print(Panel.fit(
        "[bold]LLM-TEST: Model Verification Report[/bold]",
        border_style="blue",
    ))
    console.print()

    for target_name, run_result in results.items():
        verdict = run_result.verdict
        color = CLASSIFICATION_COLORS.get(verdict.classification, "white")

        # Summary
        console.print(f"[bold]Target:[/bold] {target_name}")
        if run_result.endpoint_info:
            ep = run_result.endpoint_info
            console.print(f"[bold]Provider:[/bold] {ep.get('provider', '?')}  [bold]Model:[/bold] {ep.get('model', '?')}  [bold]URL:[/bold] {ep.get('base_url', '?')}")
        console.print(f"[bold]Verdict:[/bold] [{color}]{verdict.classification}[/{color}] ({verdict.overall_score:.2f})")
        console.print()

        # Probe scores table with confidence column
        table = Table(title="Probe Scores", show_header=True, header_style="bold cyan")
        table.add_column("Probe", style="dim", width=18)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Confidence", justify="right", width=12)

        # Build confidence lookup from probe_results
        confidence_map = {pr.probe_name: pr.confidence for pr in run_result.probe_results}

        for probe_name, score in sorted(verdict.probe_scores.items()):
            if score >= 0.7:
                s_color = "green"
            elif score >= 0.5:
                s_color = "yellow"
            else:
                s_color = "red"
            conf = confidence_map.get(probe_name)
            conf_str = f"{conf:.2f}" if conf is not None else "-"
            table.add_row(probe_name, f"[{s_color}]{score:.2f}[/{s_color}]", conf_str)

        console.print(table)
        console.print()

        # Explanation
        console.print(f"[dim]{verdict.explanation}[/dim]")
        console.print()
        console.rule()
        console.print()


def _serialize_api_response(resp: APIResponse) -> dict:
    """Serialize an APIResponse, excluding raw_json and raw_headers to keep size manageable."""
    return {
        "model_reported": resp.model_reported,
        "content": resp.content,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "stop_reason": resp.stop_reason,
        "latency_ms": resp.latency_ms,
        "ttfb_ms": resp.ttfb_ms,
        "tokens_per_sec": resp.tokens_per_sec,
    }


def _serialize_probe_result(result: ProbeResult) -> dict:
    """Serialize a ProbeResult with full details and API call data."""
    return {
        "probe_name": result.probe_name,
        "score": result.score,
        "confidence": result.confidence,
        "details": result.details,
        "api_calls": [_serialize_api_response(r) for r in result.raw_responses],
    }


def save_json_report(
    results: dict[str, RunResult],
    output_dir: str | Path = "results",
) -> Path:
    """Save report as JSON. Returns the output path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"report_{timestamp}.json"

    report_data: dict = {
        "version": 2,
        "timestamp": timestamp,
        "targets": {},
        "detailed_results": {},
    }

    for target_name, run_result in results.items():
        verdict = run_result.verdict

        # Backwards-compatible summary section
        report_data["targets"][target_name] = {
            "overall_score": verdict.overall_score,
            "classification": verdict.classification,
            "probe_scores": verdict.probe_scores,
            "explanation": verdict.explanation,
        }

        # Detailed results section
        report_data["detailed_results"][target_name] = {
            "endpoint": run_result.endpoint_info,
            "probes": [_serialize_probe_result(pr) for pr in run_result.probe_results],
        }

    with open(output_path, "w") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    # Also save as "latest"
    latest_path = output_dir / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    return output_path
