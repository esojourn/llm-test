"""Probe 9: Logprob analysis (weight 2.0, high signal if available).

Most APIs don't expose logprobs, so this is disabled by default.
When available (some OpenAI-compatible proxies), logprob distributions
can fingerprint models very reliably.
"""

from __future__ import annotations

from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient


@register_probe
class LogprobsProbe(BaseProbe):
    name = "logprobs"
    description = "Analyze token probability distributions (requires logprob support)"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        # This probe is a placeholder — logprobs require special API support
        # Most Anthropic-compatible APIs don't expose logprobs
        return ProbeResult(
            probe_name=self.name,
            score=0.5,
            confidence=0.0,  # Zero confidence = doesn't affect final score
            details={
                "note": "Logprobs not available for this endpoint type. "
                        "This probe requires an OpenAI-compatible API with logprobs enabled.",
            },
        )
