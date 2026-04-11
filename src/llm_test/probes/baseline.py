"""Probe 10: A/B baseline comparison (weight 4.0, high signal).

Direct side-by-side comparison of responses between baseline and target
on identical prompts. Measures semantic similarity and quality differential.
"""

from __future__ import annotations

import re
from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

COMPARISON_PROMPTS = [
    "Explain the halting problem in computer science. Be concise but thorough.",
    "Write a haiku about artificial intelligence.",
    "What are the three most important properties of a good hash function? Explain each briefly.",
    "Translate the following to French: 'The quick brown fox jumps over the lazy dog.'",
    "Write a Python one-liner that flattens a nested list of arbitrary depth.",
]


@register_probe
class BaselineProbe(BaseProbe):
    name = "baseline"
    description = "A/B comparison against known Opus baseline"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        if not baseline:
            return ProbeResult(
                probe_name=self.name,
                score=0.5,
                confidence=0.0,
                details={"error": "No baseline configured, skipping A/B comparison"},
            )

        num_comparisons = config.get("num_comparisons", 5)
        prompts = COMPARISON_PROMPTS[:num_comparisons]

        similarities: list[float] = []
        comparisons: list[dict[str, Any]] = []
        all_responses = []

        for prompt in prompts:
            messages = [{"role": "user", "content": prompt}]

            t_resp = await target.send_message(messages, max_tokens=512)
            b_resp = await baseline.send_message(messages, max_tokens=512)
            all_responses.extend([t_resp, b_resp])

            sim = _text_similarity(t_resp.content, b_resp.content)
            similarities.append(sim)

            comparisons.append({
                "prompt_preview": prompt[:60],
                "similarity": sim,
                "target_length": len(t_resp.content),
                "baseline_length": len(b_resp.content),
                "length_ratio": len(t_resp.content) / max(len(b_resp.content), 1),
            })

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0

        # Score: high similarity to baseline → likely same model
        # But we allow some variance (different runs produce slightly different output)
        if avg_similarity > 0.6:
            score = 1.0
        elif avg_similarity > 0.4:
            score = 0.7
        elif avg_similarity > 0.25:
            score = 0.5
        else:
            score = 0.2

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=min(0.8, 0.4 + len(prompts) * 0.08),
            details={
                "avg_similarity": avg_similarity,
                "comparisons": comparisons,
            },
            raw_responses=all_responses,
        )


def _text_similarity(a: str, b: str) -> float:
    """N-gram based similarity (Jaccard on word bigrams, unigram fallback)."""
    a_grams = _get_ngrams(a.lower(), 2)
    b_grams = _get_ngrams(b.lower(), 2)

    # If either text is too short for bigrams, fall back to unigrams
    if not a_grams or not b_grams:
        a_unigrams = _get_ngrams(a.lower(), 1)
        b_unigrams = _get_ngrams(b.lower(), 1)
        if not a_unigrams and not b_unigrams:
            return 1.0 if a.strip() == b.strip() else 0.0
        if not a_unigrams or not b_unigrams:
            return 0.0
        intersection = a_unigrams & b_unigrams
        union = a_unigrams | b_unigrams
        return len(intersection) / len(union) if union else 0.0

    intersection = a_grams & b_grams
    union = a_grams | b_grams
    return len(intersection) / len(union) if union else 0.0


def _get_ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = re.findall(r'\w+', text)
    return {tuple(words[i:i+n]) for i in range(len(words) - n + 1)}
