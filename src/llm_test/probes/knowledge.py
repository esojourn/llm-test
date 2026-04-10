"""Probe 7: Knowledge cutoff verification (weight 3.0, medium-high signal).

Different model versions have different training data cutoffs.
Testing boundary events can reveal which model is actually running.
"""

from __future__ import annotations

from typing import Any

from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

# Facts organized by date, with expected knowledge per model generation
KNOWLEDGE_FACTS = [
    {
        "id": "early_2024",
        "question": "Who won the 2024 US Presidential election?",
        "expected_answer_contains": ["trump", "donald trump"],
        "date": "2024-11-05",
        "should_know": ["claude-opus-4-6", "claude-sonnet-4-6"],
        "might_not_know": ["claude-3-opus-20240229"],
        "category": "politics",
    },
    {
        "id": "ai_2024",
        "question": "What is Claude 3.5 Sonnet? When was it released?",
        "expected_answer_contains": ["2024", "anthropic"],
        "date": "2024-06-20",
        "should_know": ["claude-opus-4-6", "claude-sonnet-4-6"],
        "might_not_know": [],
        "category": "tech",
    },
    {
        "id": "recent_2025",
        "question": "What major AI models were released in early 2025?",
        "expected_answer_contains": [],  # Open-ended, check for recency
        "date": "2025-03-01",
        "should_know": ["claude-opus-4-6"],
        "might_not_know": ["claude-3-opus-20240229"],
        "category": "tech",
    },
    {
        "id": "verifiable_fact",
        "question": "What is the current population of Earth as of the latest estimates?",
        "expected_answer_contains": ["8 billion", "8.1 billion", "8.2 billion"],
        "date": "2024-01-01",
        "should_know": ["claude-opus-4-6", "claude-sonnet-4-6"],
        "might_not_know": [],
        "category": "general",
    },
    {
        "id": "cutoff_boundary",
        "question": (
            "What is the latest event you have knowledge of? "
            "Give the approximate date of your training data cutoff."
        ),
        "expected_answer_contains": [],  # Parse the date
        "date": "N/A",
        "should_know": [],
        "might_not_know": [],
        "category": "meta",
    },
]


@register_probe
class KnowledgeProbe(BaseProbe):
    name = "knowledge"
    description = "Test knowledge cutoff to identify model version"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        results: list[dict[str, Any]] = []
        all_responses = []
        matches = 0
        total_checkable = 0

        for fact in KNOWLEDGE_FACTS:
            messages = [{"role": "user", "content": fact["question"]}]
            resp = await target.send_message(messages, max_tokens=512)
            all_responses.append(resp)

            # Check if response contains expected information
            resp_lower = resp.content.lower()

            if fact["expected_answer_contains"]:
                total_checkable += 1
                found = any(
                    ans.lower() in resp_lower
                    for ans in fact["expected_answer_contains"]
                )
                if found:
                    matches += 1
            else:
                found = None  # Open-ended, not scored

            # Compare with baseline if available
            baseline_match = None
            if baseline and fact["expected_answer_contains"]:
                b_resp = await baseline.send_message(messages, max_tokens=512)
                all_responses.append(b_resp)
                b_lower = b_resp.content.lower()
                baseline_match = any(
                    ans.lower() in b_lower
                    for ans in fact["expected_answer_contains"]
                )

            results.append({
                "fact_id": fact["id"],
                "category": fact["category"],
                "found_expected": found,
                "baseline_found": baseline_match,
                "response_preview": resp.content[:200],
            })

        # Score based on knowledge consistency
        if total_checkable > 0:
            score = matches / total_checkable
        else:
            score = 0.5  # Inconclusive

        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=0.6,
            details={
                "matches": matches,
                "total_checkable": total_checkable,
                "facts": results,
            },
            raw_responses=all_responses,
        )
