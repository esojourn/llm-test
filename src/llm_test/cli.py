"""CLI entry point for llm-test."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from .config import load_config
from .report import print_report, save_json_report
from .runner import run_probes


@click.group()
def main() -> None:
    """LLM-Test: Model verification toolkit for detecting API proxy downgrades."""
    pass


@main.command()
@click.option("--config", "config_path", default="config/default.yaml", help="Test configuration file")
@click.option("--endpoints", "endpoints_path", default="config/endpoints.yaml", help="Endpoint configuration file")
@click.option("--probe", "probe_names", multiple=True, help="Run specific probes only (repeatable)")
@click.option("--target", "target_names", multiple=True, help="Test specific targets only (repeatable)")
@click.option("--quick", is_flag=True, help="Quick mode: metadata + identity + latency only")
@click.option("--output", "output_formats", multiple=True, type=click.Choice(["terminal", "json"]), default=["terminal"])
def run(
    config_path: str,
    endpoints_path: str,
    probe_names: tuple[str, ...],
    target_names: tuple[str, ...],
    quick: bool,
    output_formats: tuple[str, ...],
) -> None:
    """Run verification probes against configured targets."""
    console = Console()

    try:
        cfg = load_config(config_path, endpoints_path)
    except FileNotFoundError as e:
        console.print(f"[red]Config file not found: {e}[/red]")
        console.print("Copy config/endpoints.yaml.example to config/endpoints.yaml and fill in your API keys.")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Config error: {e}[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Baseline:[/bold] {cfg.baseline.model} @ {cfg.baseline.base_url}")
    console.print(f"[bold]Targets:[/bold] {len(cfg.targets)} endpoint(s)")
    if quick:
        console.print("[yellow]Quick mode: running metadata + identity + latency only[/yellow]")
    console.print()

    verdicts = asyncio.run(run_probes(
        cfg,
        probe_names=list(probe_names) if probe_names else None,
        target_names=list(target_names) if target_names else None,
        quick=quick,
    ))

    if "terminal" in output_formats:
        print_report(verdicts, console)

    if "json" in output_formats:
        output_dir = cfg.output.results_dir
        path = save_json_report(verdicts, output_dir)
        console.print(f"[dim]JSON report saved to: {path}[/dim]")


@main.command()
@click.argument("report_path", type=click.Path(exists=True))
def report(report_path: str) -> None:
    """Re-display a previously saved JSON report."""
    import json
    from .scoring import Verdict

    console = Console()
    with open(report_path) as f:
        data = json.load(f)

    verdicts: dict[str, Verdict] = {}
    for name, v in data.get("targets", {}).items():
        verdicts[name] = Verdict(
            overall_score=v["overall_score"],
            classification=v["classification"],
            probe_scores=v["probe_scores"],
            explanation=v["explanation"],
        )

    print_report(verdicts, console)


if __name__ == "__main__":
    main()
