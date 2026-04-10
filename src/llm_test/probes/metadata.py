"""Probe 1: Response metadata check (weight 1.0, low signal)."""

from __future__ import annotations

from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient


@register_probe
class MetadataProbe(BaseProbe):
    name = "metadata"
    description = "Check response model field and HTTP headers"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        messages = [{"role": "user", "content": "Say hello in one word."}]
        resp = await target.send_message(messages, max_tokens=32)

        details: dict[str, Any] = {
            "model_reported": resp.model_reported,
            "model_expected": target.config.model,
            "interesting_headers": {},
        }

        score = 0.0

        # Check model field match
        model_match = _model_matches(resp.model_reported, target.config.model)
        details["model_field_match"] = model_match

        if model_match:
            score = 1.0
        else:
            score = 0.0
            details["mismatch_note"] = (
                f"Expected '{target.config.model}', got '{resp.model_reported}'"
            )

        # Check for suspicious headers that reveal proxy infrastructure
        suspicious_headers = [
            "x-forwarded-for", "via", "x-real-ip", "x-proxy",
            "x-powered-by", "server",
        ]
        for h in suspicious_headers:
            val = resp.raw_headers.get(h)
            if val:
                details["interesting_headers"][h] = val

        # Check response structure matches Anthropic format
        if target.config.provider in ("anthropic", "anthropic_compatible"):
            expected_fields = {"id", "type", "role", "content", "model", "usage"}
            actual_fields = set(resp.raw_json.keys())
            missing = expected_fields - actual_fields
            if missing:
                details["missing_fields"] = list(missing)
                score = max(0.0, score - 0.3)

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=0.6,  # Low confidence — easily spoofed
            details=details,
            raw_responses=[resp],
        )


def _model_matches(reported: str, expected: str) -> bool:
    """Fuzzy match model names (handles version suffixes, date stamps)."""
    reported = reported.lower().strip()
    expected = expected.lower().strip()
    if reported == expected:
        return True
    # Match base model name (e.g., "claude-opus-4-6" matches "claude-opus-4-6-20260301")
    if reported.startswith(expected) or expected.startswith(reported):
        return True
    return False
