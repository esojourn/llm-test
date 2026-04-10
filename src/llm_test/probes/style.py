"""Probe 8: Output style fingerprinting (weight 3.0, medium-high signal).

Different Claude models have subtly different output characteristics
even on identical prompts at temperature 0.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

STYLE_PROMPTS = [
    "Explain what a Fourier transform is in simple terms.",
    "Write a short story about a robot discovering emotions. Exactly 200 words.",
    "List the pros and cons of remote work.",
    "Explain the difference between TCP and UDP protocols.",
    "Describe the process of photosynthesis step by step.",
]


@register_probe
class StyleProbe(BaseProbe):
    name = "style"
    description = "Fingerprint output style — length, vocabulary, structure patterns"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        num_samples = config.get("num_samples", 5)
        prompts = STYLE_PROMPTS[:num_samples]

        target_features: list[dict[str, float]] = []
        baseline_features: list[dict[str, float]] = []
        all_responses = []
        per_prompt: list[dict[str, Any]] = []

        for prompt in prompts:
            messages = [{"role": "user", "content": prompt}]

            t_resp = await target.send_message(messages, max_tokens=1024)
            all_responses.append(t_resp)
            t_feat = _extract_features(t_resp.content)
            target_features.append(t_feat)

            b_feat = None
            if baseline:
                b_resp = await baseline.send_message(messages, max_tokens=1024)
                all_responses.append(b_resp)
                b_feat = _extract_features(b_resp.content)
                baseline_features.append(b_feat)

            per_prompt.append({
                "prompt_preview": prompt[:60],
                "target_features": t_feat,
                "baseline_features": b_feat,
            })

        # Calculate similarity between target and baseline feature distributions
        if baseline_features:
            similarity = _feature_similarity(target_features, baseline_features)
            score = similarity
            confidence = min(0.8, 0.4 + len(prompts) * 0.08)
        else:
            # Without baseline, use absolute heuristics for Opus-like output
            avg_features = _average_features(target_features)
            score = _score_opus_heuristic(avg_features)
            confidence = 0.35

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=confidence,
            details={
                "target_avg": _average_features(target_features),
                "baseline_avg": _average_features(baseline_features) if baseline_features else None,
                "similarity": score if baseline_features else None,
                "per_prompt": per_prompt,
            },
            raw_responses=all_responses,
        )


def _extract_features(text: str) -> dict[str, float]:
    """Extract stylistic features from text."""
    words = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    word_count = len(words)
    char_count = len(text)
    sentence_count = max(len(sentences), 1)
    unique_words = len(set(w.lower() for w in words))

    # Type-token ratio (vocabulary richness)
    ttr = unique_words / word_count if word_count > 0 else 0

    # Average sentence length
    avg_sentence_len = word_count / sentence_count

    # Hedging language frequency
    hedging_words = ["perhaps", "maybe", "might", "could", "possibly", "likely",
                     "it's worth noting", "i think", "in my opinion", "arguably"]
    text_lower = text.lower()
    hedge_count = sum(text_lower.count(h) for h in hedging_words)
    hedge_ratio = hedge_count / word_count if word_count > 0 else 0

    # Formatting signals
    bullet_count = text.count("- ") + text.count("* ") + len(re.findall(r'^\d+\.', text, re.MULTILINE))
    has_headers = bool(re.search(r'^#+\s', text, re.MULTILINE))
    has_bold = bool(re.search(r'\*\*[^*]+\*\*', text))

    # Code block presence
    code_blocks = len(re.findall(r'```', text))

    return {
        "word_count": float(word_count),
        "char_count": float(char_count),
        "sentence_count": float(sentence_count),
        "ttr": ttr,
        "avg_sentence_len": avg_sentence_len,
        "hedge_ratio": hedge_ratio,
        "bullet_count": float(bullet_count),
        "has_headers": float(has_headers),
        "has_bold": float(has_bold),
        "code_blocks": float(code_blocks // 2),  # pairs
    }


def _average_features(features: list[dict[str, float]]) -> dict[str, float]:
    """Average feature vectors."""
    if not features:
        return {}
    keys = features[0].keys()
    return {
        k: statistics.mean(f[k] for f in features)
        for k in keys
    }


def _feature_similarity(
    target: list[dict[str, float]],
    baseline: list[dict[str, float]],
) -> float:
    """Compute similarity between feature distributions (0-1)."""
    t_avg = _average_features(target)
    b_avg = _average_features(baseline)

    if not t_avg or not b_avg:
        return 0.5

    # Normalized feature distance
    total_diff = 0.0
    count = 0
    for key in t_avg:
        if key in b_avg:
            t_val = t_avg[key]
            b_val = b_avg[key]
            max_val = max(abs(t_val), abs(b_val), 1.0)
            diff = abs(t_val - b_val) / max_val
            total_diff += diff
            count += 1

    avg_diff = total_diff / count if count > 0 else 0.5
    # Convert distance to similarity (0 diff → 1.0 similarity)
    return max(0.0, 1.0 - avg_diff)


def _score_opus_heuristic(features: dict[str, float]) -> float:
    """Heuristic scoring without baseline — Opus tends to be more verbose and structured."""
    if not features:
        return 0.5

    score = 0.5  # Start neutral

    # Opus typically gives longer, more detailed responses
    if features.get("word_count", 0) > 150:
        score += 0.1
    if features.get("ttr", 0) > 0.5:
        score += 0.1  # Rich vocabulary
    if features.get("avg_sentence_len", 0) > 15:
        score += 0.1  # Complex sentences

    return min(1.0, score)
