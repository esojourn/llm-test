"""Async test orchestrator — runs probes against targets."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn

from .client import EndpointClient
from .config import AppConfig, ProbeConfig
from .probes import BaseProbe, ProbeResult, get_all_probes, get_probe
from .scoring import Verdict, compute_verdict


async def run_probes(
    config: AppConfig,
    probe_names: list[str] | None = None,
    target_names: list[str] | None = None,
    quick: bool = False,
) -> dict[str, Verdict]:
    """Run probes against all configured targets. Returns {target_name: Verdict}."""
    # Build baseline client
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
                progress.update(task, description=f"[{target_config.name}] Running {probe_name}...")
                probe_cfg = config.probes.get(probe_name, ProbeConfig())
                extra = probe_cfg.model_dump(exclude={"enabled", "weight"})

                try:
                    result = await probe.run(target, baseline, extra)
                    results.append(result)
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
