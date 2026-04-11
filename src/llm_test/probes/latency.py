"""Probe 2: Latency/throughput profiling (weight 3.0, medium-high signal).

Key insight: a target that is FASTER than the known Opus baseline is suspicious.
Slower is normal (proxy overhead). Faster means a cheaper/smaller model.
"""

from __future__ import annotations

import statistics
from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient


PROMPT_TEMPLATES = {
    100: "Write a brief paragraph about the history of computing.",
    1000: (
        "Write a detailed essay about the history of computing, covering the "
        "evolution from mechanical calculators through modern quantum computers. "
        "Include key figures, major milestones, and discuss the social impact of "
        "each era. " * 5
    ),
    5000: (
        "Write an extremely comprehensive and detailed analysis of the entire "
        "history of computing from ancient abacuses through modern AI systems. "
        "Cover every major era, key inventions, important researchers, theoretical "
        "breakthroughs, commercial developments, and societal impacts. "
        "Be as thorough as possible. " * 20
    ),
}


@register_probe
class LatencyProbe(BaseProbe):
    name = "latency"
    description = "Profile latency and throughput, flag suspiciously fast responses"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        num_samples = config.get("num_samples", 5)
        prompt_lengths = config.get("prompt_lengths", [100, 1000])

        target_tps_all: list[float] = []
        target_latencies: list[float] = []
        baseline_tps_all: list[float] = []
        baseline_latencies: list[float] = []
        all_responses = []
        details: dict[str, Any] = {"per_length": {}}

        for length in prompt_lengths:
            prompt = PROMPT_TEMPLATES.get(length, PROMPT_TEMPLATES[100])
            messages = [{"role": "user", "content": prompt}]

            t_tps: list[float] = []
            t_lat: list[float] = []
            b_tps: list[float] = []
            b_lat: list[float] = []

            for _ in range(num_samples):
                resp = await target.send_message(messages, max_tokens=256)
                all_responses.append(resp)
                if resp.tokens_per_sec > 0:
                    t_tps.append(resp.tokens_per_sec)
                t_lat.append(resp.latency_ms)

                if baseline:
                    b_resp = await baseline.send_message(messages, max_tokens=256)
                    all_responses.append(b_resp)
                    if b_resp.tokens_per_sec > 0:
                        b_tps.append(b_resp.tokens_per_sec)
                    b_lat.append(b_resp.latency_ms)

            target_tps_all.extend(t_tps)
            target_latencies.extend(t_lat)
            baseline_tps_all.extend(b_tps)
            baseline_latencies.extend(b_lat)

            details["per_length"][length] = {
                "target_median_tps": statistics.median(t_tps) if t_tps else 0,
                "target_median_latency_ms": statistics.median(t_lat) if t_lat else 0,
                "baseline_median_tps": statistics.median(b_tps) if b_tps else None,
                "baseline_median_latency_ms": statistics.median(b_lat) if b_lat else None,
            }

        # Score: compare target vs baseline throughput
        if baseline and baseline_tps_all and target_tps_all:
            target_median = statistics.median(target_tps_all)
            baseline_median = statistics.median(baseline_tps_all)

            details["target_median_tps"] = target_median
            details["baseline_median_tps"] = baseline_median
            details["speed_ratio"] = target_median / baseline_median if baseline_median > 0 else 0

            score = _score_latency(target_median, baseline_median)
            confidence = min(0.9, 0.5 + len(target_tps_all) * 0.05)
        else:
            # No baseline — use absolute heuristics for Opus
            target_median = statistics.median(target_tps_all) if target_tps_all else 0
            details["target_median_tps"] = target_median
            details["note"] = "No baseline available, using absolute heuristics"

            # Opus typically outputs 20-50 tok/s. >80 is Sonnet territory, >120 is Haiku.
            if target_median > 120:
                score = 0.1
            elif target_median > 80:
                score = 0.4
            elif target_median > 50:
                score = 0.7
            else:
                score = 1.0
            confidence = 0.4  # Lower confidence without baseline

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=confidence,
            details=details,
            raw_responses=all_responses,
        )


def _score_latency(target_tps: float, baseline_tps: float) -> float:
    """Score based on throughput comparison. Faster than baseline is suspicious.

    Uses linear interpolation: ratio 1.0 → 1.0, ratio 2.0 → 0.1, >2.0 clamped at 0.1.
    Smooth curve avoids noise-sensitive threshold jumps.
    """
    if baseline_tps <= 0:
        return 0.5

    ratio = target_tps / baseline_tps

    if ratio <= 1.0:
        return 1.0  # Same speed or slower — consistent with Opus
    elif ratio >= 2.0:
        return 0.1  # >2x faster — almost certainly a smaller model
    else:
        # Linear interpolation: (1.0, 1.0) → (2.0, 0.1)
        return 1.0 - (ratio - 1.0) * 0.9
