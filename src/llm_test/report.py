"""Report generation — Rich terminal and JSON output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .scoring import Verdict

CLASSIFICATION_COLORS = {
    "GENUINE_OPUS": "bold green",
    "LIKELY_OPUS": "green",
    "SUSPICIOUS": "yellow",
    "LIKELY_DOWNGRADE": "red",
    "DEFINITE_DOWNGRADE": "bold red",
}


def print_report(verdicts: dict[str, Verdict], console: Console | None = None) -> None:
    """Print a rich terminal report."""
    console = console or Console()

    console.print()
    console.print(Panel.fit(
        "[bold]LLM-TEST: Model Verification Report[/bold]",
        border_style="blue",
    ))
    console.print()

    for target_name, verdict in verdicts.items():
        color = CLASSIFICATION_COLORS.get(verdict.classification, "white")

        # Summary
        console.print(f"[bold]Target:[/bold] {target_name}")
        console.print(f"[bold]Verdict:[/bold] [{color}]{verdict.classification}[/{color}] ({verdict.overall_score:.2f})")
        console.print()

        # Probe scores table
        table = Table(title="Probe Scores", show_header=True, header_style="bold cyan")
        table.add_column("Probe", style="dim", width=18)
        table.add_column("Score", justify="right", width=8)

        for probe_name, score in sorted(verdict.probe_scores.items()):
            if score >= 0.7:
                s_color = "green"
            elif score >= 0.5:
                s_color = "yellow"
            else:
                s_color = "red"
            table.add_row(probe_name, f"[{s_color}]{score:.2f}[/{s_color}]")

        console.print(table)
        console.print()

        # Explanation
        console.print(f"[dim]{verdict.explanation}[/dim]")
        console.print()
        console.rule()
        console.print()


def save_json_report(
    verdicts: dict[str, Verdict],
    output_dir: str | Path = "results",
) -> Path:
    """Save report as JSON. Returns the output path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"report_{timestamp}.json"

    report_data = {
        "timestamp": timestamp,
        "targets": {},
    }

    for target_name, verdict in verdicts.items():
        report_data["targets"][target_name] = {
            "overall_score": verdict.overall_score,
            "classification": verdict.classification,
            "probe_scores": verdict.probe_scores,
            "explanation": verdict.explanation,
        }

    with open(output_path, "w") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    # Also save as "latest"
    latest_path = output_dir / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    return output_path
