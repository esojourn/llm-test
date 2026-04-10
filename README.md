# llm-test

Model verification toolkit for detecting API proxy downgrades.

When you pay for Claude Opus through a third-party API proxy, how do you know you're actually getting Opus — and not a cheaper model like Sonnet, Haiku, or even a quantized open-source substitute? **llm-test** answers this question by running a battery of 10 independent probes against your API endpoint and producing a confidence score.

## How it works

llm-test compares a **target** endpoint (the proxy you want to verify) against a **baseline** (the official Anthropic API). Each probe tests a different dimension — latency, reasoning ability, long-context retrieval, output style, and more. The results are combined using a weighted confidence formula into a single verdict:

```
>= 0.85  GENUINE_OPUS       All probes consistent with Opus
>= 0.70  LIKELY_OPUS         Minor anomalies, probably fine
>= 0.50  SUSPICIOUS          Mixed signals, investigate further
>= 0.30  LIKELY_DOWNGRADE    Multiple red flags
<  0.30  DEFINITE_DOWNGRADE  Strong evidence of a different model
```

The core insight: **no single probe is decisive, but faking all 10 simultaneously is nearly impossible.** A proxy can spoof the model name in the response. It can add artificial latency to look slower. But it cannot make a Sonnet-class model pass Opus-level reasoning tasks while also matching Opus output style, knowledge cutoff, and long-context retrieval.

## Quick start

```bash
# 1. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure endpoints
cp config/endpoints.yaml.example config/endpoints.yaml
# Edit config/endpoints.yaml — fill in API keys and proxy URLs

# 3. Run
llm-test run              # Full test suite
llm-test run --quick      # Fast mode (metadata + identity + latency)
```

## Installation

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# For development
pip install -e ".[dev]"
```

## Configuration

### Endpoints (`config/endpoints.yaml`)

Define a baseline (official Anthropic API) and one or more targets to verify:

```yaml
baseline:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY       # reads from this env var
  base_url: https://api.anthropic.com
  model: claude-opus-4-6

targets:
  - name: "my-proxy"
    provider: anthropic_compatible     # or "openai_compatible"
    api_key_env: MY_PROXY_API_KEY
    base_url: https://my-proxy.example.com
    model: claude-opus-4-6
```

Three provider types are supported:

| Provider | Protocol | Auth header | Use when |
|---|---|---|---|
| `anthropic` | Anthropic Messages API via official SDK | `x-api-key` | Official API (baseline) |
| `anthropic_compatible` | Anthropic Messages API via httpx | `x-api-key` | Proxies that mirror the Anthropic API |
| `openai_compatible` | OpenAI Chat Completions API via httpx | `Authorization: Bearer` | Proxies that expose Claude via the OpenAI format |

### Test config (`config/default.yaml`)

Controls which probes are enabled, their weights, and parameters like sample counts and context lengths. The defaults are sensible for most use cases; see the file for all options.

## CLI usage

```bash
# Full test — all enabled probes against all targets
llm-test run

# Quick mode — only metadata, identity, and latency (fast, cheap)
llm-test run --quick

# Run specific probes
llm-test run --probe reasoning --probe latency

# Test a specific target only
llm-test run --target my-proxy

# Output JSON report alongside terminal output
llm-test run --output terminal --output json

# Re-display a saved report
llm-test report results/latest.json
```

## The 10 probes

Each probe produces a score from 0.0 (definitely not Opus) to 1.0 (consistent with Opus), plus a confidence value. Probes are weighted by signal strength — harder-to-fake probes get higher weights.

### High signal

| Probe | Weight | What it tests |
|---|---|---|
| **reasoning** | 5.0 | Multi-step math, logic puzzles, edge-case code generation. Opus solves problems that Sonnet/Haiku cannot. This is the single hardest thing for a proxy to fake. |
| **needle** | 4.0 | Needle-in-a-haystack: embeds a random code at various depths in long documents (10K-100K chars) and asks the model to retrieve it. Tests real context window capability. |
| **baseline** | 4.0 | Sends identical prompts to both baseline and target, compares response similarity via n-gram overlap. Same model should produce structurally similar output. |

### Medium-high signal

| Probe | Weight | What it tests |
|---|---|---|
| **latency** | 3.0 | Measures tokens/second and latency. Opus is fundamentally slower than smaller models — a proxy that responds at Haiku speed (>120 tok/s) while claiming Opus is suspicious. **Asymmetric scoring**: slower than baseline is fine (network overhead); faster is the red flag. |
| **knowledge** | 3.0 | Asks about events near training data cutoff boundaries. Different model versions have different knowledge cutoffs, so a model answering wrong about events it should know (or right about events it shouldn't) reveals its true version. |
| **style** | 3.0 | Extracts stylistic features (response length, vocabulary richness, sentence complexity, hedging language frequency, formatting habits) and compares distributions between target and baseline. |

### Medium signal

| Probe | Weight | What it tests |
|---|---|---|
| **identity** | 2.0 | 8 creative prompts to make the model reveal its identity — direct asks, role-play scenarios, reverse spelling, completion traps. Can be overridden by system prompts, hence medium signal. |
| **sysprompt** | 2.0 | Attempts to extract injected system prompts. Many proxies add a hidden system prompt like "You are Claude Opus" — if this leaks, it's evidence of manipulation. Disabled by default. |
| **logprobs** | 2.0 | Compares token probability distributions (requires API logprob support). Highly reliable when available, but most Anthropic-compatible APIs don't expose logprobs. Disabled by default. |

### Low signal

| Probe | Weight | What it tests |
|---|---|---|
| **metadata** | 1.0 | Checks the `model` field in the API response and inspects HTTP headers for proxy fingerprints. Trivially spoofable, but a mismatch is a strong negative signal. |

## Scoring formula

```
final_score = sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)
```

Each probe's contribution is scaled by both its weight (how important the dimension is) and its confidence (how reliable this particular measurement was). A probe that errors out gets confidence=0.1 and score=0.5, effectively removing it from the final calculation.

## Extending with custom probes

Adding a new probe requires one file:

```python
# src/llm_test/probes/my_probe.py

from typing import Any
from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

@register_probe
class MyProbe(BaseProbe):
    name = "my_probe"
    description = "What this probe tests"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        resp = await target.send_message(
            [{"role": "user", "content": "test prompt"}],
            max_tokens=256,
        )
        score = 1.0  # your scoring logic
        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=0.7,
            details={"info": "..."},
            raw_responses=[resp],
        )
```

Then add an import in `src/llm_test/probes/__init__.py` inside `_load_probes()` and optionally configure it in `config/default.yaml`.

## Project structure

```
src/llm_test/
  __init__.py
  cli.py          Click CLI entry point
  config.py       YAML + Pydantic config loading
  client.py       Unified API client (anthropic SDK + httpx)
  runner.py       Async probe orchestrator with progress display
  scoring.py      Weighted confidence aggregation + verdict
  report.py       Rich terminal tables + JSON output
  probes/
    __init__.py   BaseProbe, ProbeResult, @register_probe, registry
    metadata.py   Response metadata check
    latency.py    Latency/throughput profiling
    reasoning.py  Complex multi-step reasoning tasks
    needle.py     Needle-in-a-haystack long context test
    identity.py   Model identity probing
    knowledge.py  Knowledge cutoff verification
    style.py      Output style fingerprinting
    baseline.py   A/B comparison against baseline
    sysprompt.py  System prompt extraction (optional)
    logprobs.py   Logprob analysis (optional)

config/
  default.yaml            Probe weights, parameters, output settings
  endpoints.yaml.example  Endpoint config template

results/                  Runtime output (git-ignored)
```

## Related tools

This toolkit is self-contained but draws on ideas from these projects:

- **[Promptfoo](https://github.com/promptfoo/promptfoo)** -- CLI for LLM output evaluation and comparison. Useful as an external cross-check.
- **[LLMTest_NeedleInAHaystack](https://github.com/gkamradt/LLMTest_NeedleInAHaystack)** -- The original needle-in-a-haystack test by Gregory Kamradt. Our `needle` probe implements a similar methodology.
- **[lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)** -- Academic benchmark framework with hundreds of datasets. Can complement llm-test for deep capability profiling.

## Cost considerations

A full test run makes many API calls to both the baseline and each target. Approximate per-target costs at default settings:

- **Quick mode** (`--quick`): ~15 API calls, minimal cost
- **Full run**: ~80-100 API calls, including some with long contexts (needle probe). Budget roughly $1-3 per target depending on context lengths.

To reduce cost, disable expensive probes (`needle`, `baseline`) in `config/default.yaml` or use `--probe` to run only specific probes.

## License

MIT
