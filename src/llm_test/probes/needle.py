"""Probe 4: Needle-in-a-haystack (weight 4.0, high signal).

Tests the model's ability to retrieve specific information from long contexts.
Opus handles 200K tokens; if the model fails at shorter lengths, it may be
a smaller model or a context-limited proxy.
"""

from __future__ import annotations

import hashlib
import random
import string
from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

# Filler text paragraphs (repeated/varied to build long contexts)
FILLER_PARAGRAPHS = [
    "The development of urban infrastructure has been a defining challenge of the modern era. Cities around the world have invested heavily in transportation systems, water treatment facilities, and communication networks to support growing populations.",
    "Marine biology research has revealed fascinating adaptations in deep-sea organisms. Species living near hydrothermal vents have developed unique metabolic pathways that allow them to thrive in extreme temperatures and pressures.",
    "The evolution of musical instruments spans thousands of years, from simple bone flutes discovered in archaeological sites to the sophisticated electronic synthesizers of the 21st century. Each innovation reflected the cultural values of its time.",
    "Agricultural practices have undergone dramatic transformations since the Green Revolution. Modern farming techniques incorporate precision agriculture, satellite imaging, and genetic research to maximize crop yields while minimizing environmental impact.",
    "The study of linguistics reveals how languages evolve, split, and merge over centuries. Proto-Indo-European, the reconstructed ancestor of most European and South Asian languages, offers insights into ancient human migration patterns.",
    "Advances in materials science have enabled the development of metamaterials with properties not found in nature. These engineered materials can bend light in unusual ways, leading to potential applications in stealth technology and super-resolution imaging.",
    "The philosophy of mind continues to grapple with the hard problem of consciousness. Despite advances in neuroscience, the subjective experience of qualia remains one of the most profound mysteries in human understanding.",
    "Renewable energy technologies have seen dramatic cost reductions over the past decade. Solar photovoltaic installations, in particular, have benefited from economies of scale and improvements in silicon wafer manufacturing processes.",
]


@register_probe
class NeedleProbe(BaseProbe):
    name = "needle"
    description = "Needle-in-a-haystack long context retrieval test"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        context_lengths = config.get("context_lengths", [10000, 50000])
        depths = config.get("depths", [0.1, 0.5, 0.9])

        results: list[dict[str, Any]] = []
        all_responses = []
        total_tests = 0
        total_found = 0

        for ctx_len in context_lengths:
            for depth in depths:
                needle_code = _generate_needle_code()
                haystack = _build_haystack(ctx_len, needle_code, depth)

                messages = [
                    {"role": "user", "content": (
                        f"{haystack}\n\n"
                        "Based on the text above, what is the secret verification code? "
                        "Reply with just the code, nothing else."
                    )},
                ]

                try:
                    resp = await target.send_message(messages, max_tokens=64)
                    all_responses.append(resp)

                    found = needle_code.lower() in resp.content.lower()
                    total_tests += 1
                    if found:
                        total_found += 1

                    results.append({
                        "context_length": ctx_len,
                        "depth": depth,
                        "needle": needle_code,
                        "found": found,
                        "response_preview": resp.content[:100],
                    })
                except Exception as e:
                    total_tests += 1
                    results.append({
                        "context_length": ctx_len,
                        "depth": depth,
                        "needle": needle_code,
                        "found": False,
                        "error": str(e),
                    })

        score = total_found / total_tests if total_tests > 0 else 0.0

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=min(0.9, 0.5 + total_tests * 0.05),
            details={
                "found": total_found,
                "total": total_tests,
                "accuracy": score,
                "tests": results,
            },
            raw_responses=all_responses,
        )


def _generate_needle_code() -> str:
    """Generate a random unique verification code."""
    parts = [
        ''.join(random.choices(string.ascii_uppercase, k=5)),
        ''.join(random.choices(string.digits, k=3)),
        ''.join(random.choices(string.ascii_uppercase, k=4)),
    ]
    return '-'.join(parts)


def _build_haystack(target_chars: int, needle_code: str, depth: float) -> str:
    """Build a text of approximately target_chars with the needle at the given depth."""
    needle_sentence = (
        f"The secret verification code for this document is: {needle_code}. "
        "This code is essential for authentication purposes."
    )

    # Build filler text
    paragraphs = []
    current_len = 0
    idx = 0
    while current_len < target_chars:
        para = FILLER_PARAGRAPHS[idx % len(FILLER_PARAGRAPHS)]
        # Add slight variation to avoid exact repetition
        para = f"[Section {idx + 1}] {para}"
        paragraphs.append(para)
        current_len += len(para) + 2  # +2 for newlines
        idx += 1

    # Insert needle at the specified depth
    insert_pos = max(0, min(int(len(paragraphs) * depth), len(paragraphs) - 1))
    paragraphs.insert(insert_pos, needle_sentence)

    return "\n\n".join(paragraphs)
