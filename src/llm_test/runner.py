"""Async test orchestrator — runs probes against targets."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .cache import CacheMissError
from .client import CachedEndpointClient, EndpointClient, RecordingEndpointClient
from .config import AppConfig, ProbeConfig
from .probes import BaseProbe, ProbeResult, get_all_probes, get_probe
from .scoring import Verdict, compute_verdict


async def run_probes(
    config: AppConfig,
    probe_names: list[str] | None = None,
    target_names: list[str] | None = None,
    quick: bool = False,
    baseline_cache_path: str | None = None,
) -> dict[str, Verdict]:
    """Run probes against all configured targets. Returns {target_name: Verdict}."""
    console = Console()
    cache = None

    if baseline_cache_path:
        from .cache import compute_config_hash, load_cache

        cache = load_cache(Path(baseline_cache_path))
        expected_hash = compute_config_hash(config.baseline)
        if cache.config_hash != expected_hash:
            console.print(
                "[yellow]Warning: cache was created for a different baseline config. "
                "Consider re-running 'llm-test baseline'.[/yellow]"
            )
        console.print(f"[dim]Using cached baseline from {cache.created_at}[/dim]")
        baseline = CachedEndpointClient(cache)
    else:
        baseline = EndpointClient(config.baseline)

    # Select targets
    targets = config.targets
    if target_names:
        targets = [t for t in targets if t.name in target_names]

    # Select probes
    available_probes = get_all_probes()
    if quick:
        probe_names = ["metadata", "identity", "latency"]

    if probe_names:
        probes = {n: available_probes[n] for n in probe_names if n in available_probes}
    else:
        probes = {
            name: probe
            for name, probe in available_probes.items()
            if config.probes.get(name, ProbeConfig()).enabled
        }

    # Get weights
    weights = {
        name: config.probes.get(name, ProbeConfig()).weight
        for name in probes
    }

    verdicts: dict[str, Verdict] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        for target_config in targets:
            target = EndpointClient(target_config)
            task = progress.add_task(f"Testing {target_config.name}...", total=len(probes))

            results: list[ProbeResult] = []
            for probe_name, probe in probes.items():
                cache_tag = " (cached baseline)" if cache and probe_name not in (cache.excluded_probes if cache else []) else ""
                progress.update(task, description=f"[{target_config.name}] Running {probe_name}{cache_tag}...")
                probe_cfg = config.probes.get(probe_name, ProbeConfig())
                extra = probe_cfg.model_dump(exclude={"enabled", "weight"})

                try:
                    # If using cache and this probe was excluded, pass baseline=None
                    probe_baseline = baseline
                    if cache and probe_name in cache.excluded_probes:
                        probe_baseline = None
                    result = await probe.run(target, probe_baseline, extra)
                    results.append(result)
                except CacheMissError as e:
                    console.print(f"[yellow]  Warning: {probe_name}: cache miss — {e}[/yellow]")
                    results.append(ProbeResult(
                        probe_name=probe_name,
                        score=0.5,
                        confidence=0.1,
                        details={"error": f"Cache miss: {e}"},
                    ))
                except Exception as e:
                    results.append(ProbeResult(
                        probe_name=probe_name,
                        score=0.5,  # Inconclusive on error
                        confidence=0.1,
                        details={"error": str(e)},
                    ))

                progress.advance(task)

            verdict = compute_verdict(results, weights)
            verdicts[target_config.name] = verdict

    return verdicts


async def collect_baseline(
    config: AppConfig,
    exclude_latency: bool = True,
) -> RecordingEndpointClient:
    """Run baseline-using probes to collect and record baseline responses."""
    real_baseline = EndpointClient(config.baseline)
    recorder = RecordingEndpointClient(real_baseline)

    # Probes that use baseline for content comparison
    cacheable = ["baseline", "style", "knowledge"]
    if not exclude_latency:
        cacheable.append("latency")

    available = get_all_probes()
    probes = {n: available[n] for n in cacheable if n in available}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Collecting baseline responses...", total=len(probes))

        for probe_name, probe in probes.items():
            progress.update(task, description=f"Collecting baseline for {probe_name}...")
            probe_cfg = config.probes.get(probe_name, ProbeConfig())
            extra = probe_cfg.model_dump(exclude={"enabled", "weight"})
            # Use real baseline as target too; we only care about recorded baseline responses
            await probe.run(real_baseline, recorder, extra)
            progress.advance(task)

    return recorder
