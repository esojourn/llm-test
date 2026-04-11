"""Weighted confidence aggregation and verdict classification."""

from __future__ import annotations

from dataclasses import dataclass

from .probes import ProbeResult


@dataclass
class Verdict:
    overall_score: float  # 0.0 to 1.0
    classification: str   # GENUINE_OPUS | LIKELY_OPUS | SUSPICIOUS | LIKELY_DOWNGRADE | DEFINITE_DOWNGRADE
    probe_scores: dict[str, float]
    explanation: str


@dataclass
class RunResult:
    """Full result for one target — verdict plus all probe data and endpoint info."""
    endpoint_info: dict[str, str]
    verdict: Verdict
    probe_results: list[ProbeResult]


def compute_verdict(
    results: list[ProbeResult],
    weights: dict[str, float],
    confidence_threshold: float = 0.0,
) -> Verdict:
    """
    Weighted average of probe scores, adjusted by per-probe confidence.

    Final score = sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)

    Probes with confidence below confidence_threshold are excluded from the
    aggregation (their scores are still recorded but do not affect the verdict).
    """
    numerator = 0.0
    denominator = 0.0
    probe_scores: dict[str, float] = {}

    for result in results:
        probe_scores[result.probe_name] = result.score
        if result.confidence < confidence_threshold:
            continue
        w = weights.get(result.probe_name, 1.0)
        numerator += result.score * w * result.confidence
        denominator += w * result.confidence

    overall = numerator / denominator if denominator > 0 else 0.5  # 0.5 = inconclusive
    classification = _classify(overall)
    explanation = _explain(overall, classification, results, weights, confidence_threshold)

    return Verdict(
        overall_score=overall,
        classification=classification,
        probe_scores=probe_scores,
        explanation=explanation,
    )


def _classify(score: float) -> str:
    if score >= 0.85:
        return "GENUINE_OPUS"
    elif score >= 0.70:
        return "LIKELY_OPUS"
    elif score >= 0.50:
        return "SUSPICIOUS"
    elif score >= 0.30:
        return "LIKELY_DOWNGRADE"
    else:
        return "DEFINITE_DOWNGRADE"


def _explain(
    score: float,
    classification: str,
    results: list[ProbeResult],
    weights: dict[str, float],
    confidence_threshold: float = 0.0,
) -> str:
    lines: list[str] = []

    if classification == "GENUINE_OPUS":
        lines.append("All probes are consistent with a genuine Opus model.")
    elif classification == "LIKELY_OPUS":
        lines.append("Most probes are consistent with Opus, minor anomalies detected.")
    elif classification == "SUSPICIOUS":
        lines.append("Mixed signals — some probes suggest this may not be Opus.")
    elif classification == "LIKELY_DOWNGRADE":
        lines.append("Multiple probes indicate this is likely a downgraded model.")
    else:
        lines.append("Strong evidence this is NOT an Opus model.")

    # Highlight the most impactful negative probes
    for result in sorted(results, key=lambda r: r.score):
        if result.confidence < confidence_threshold:
            continue
        if result.score < 0.5:
            w = weights.get(result.probe_name, 1.0)
            lines.append(
                f"  - {result.probe_name}: score={result.score:.2f} "
                f"(weight={w}, confidence={result.confidence:.2f})"
            )

    # Note probes excluded due to low confidence
    excluded = [r for r in results if r.confidence < confidence_threshold]
    if excluded:
        names = ", ".join(r.probe_name for r in excluded)
        lines.append(f"  (excluded due to low confidence: {names})")

    return "\n".join(lines)
