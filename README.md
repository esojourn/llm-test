# llm-test

[中文文档](README-cn.md)

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

### Web UI (recommended for most users)

```bash
# 1. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Start the web server
llm-test serve

# 3. Open http://127.0.0.1:8000 in your browser
#    Enter your API proxy's base URL and key, click "开始验证"
```

### CLI

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

# --- Baseline caching (save API costs) ---

# Collect baseline responses once and cache to disk
llm-test baseline

# Run tests using cached baseline (no official API calls for baseline)
llm-test run --baseline-cache cache/baseline.json

# Include latency data in cache (not recommended — timing data is ephemeral)
llm-test baseline --include-latency

# Custom cache output path
llm-test baseline --output path/to/cache.json
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
| **latency** | 3.0 | Measures tokens/second and latency. Opus is fundamentally slower than smaller models — a proxy that responds at Haiku speed (>120 tok/s) while claiming Opus is suspicious. **Asymmetric scoring**: slower than baseline = score 1.0 (network overhead is normal); faster uses linear interpolation from 1.0 at ratio=1.0 down to 0.1 at ratio=2.0+. |
| **knowledge** | 3.0 | Asks about events near training data cutoff boundaries. Different model versions have different knowledge cutoffs, so a model answering wrong about events it should know (or right about events it shouldn't) reveals its true version. |
| **style** | 3.0 | Extracts stylistic features (response length, vocabulary richness, sentence complexity, hedging language frequency, formatting habits) and compares distributions between target and baseline. |

### Medium signal

| Probe | Weight | What it tests |
|---|---|---|
| **identity** | 2.0 | 8 creative prompts to make the model reveal its identity — direct asks, role-play scenarios, reverse spelling, completion traps. Distinguishes between specific "Opus" self-identification (strong signal), generic "Claude" response (weak positive), and non-Claude identity (strong negative). Can be overridden by system prompts, hence medium signal. |
| **sysprompt** | 2.0 | Attempts to extract injected system prompts. Many proxies add a hidden system prompt like "You are Claude Opus" — if this leaks, it's evidence of manipulation. Disabled by default. |
| **logprobs** | 2.0 | Compares token probability distributions (requires API logprob support). Highly reliable when available, but most Anthropic-compatible APIs don't expose logprobs. Disabled by default. |

### Low signal

| Probe | Weight | What it tests |
|---|---|---|
| **metadata** | 1.0 | Checks the `model` field in the API response and inspects HTTP headers for proxy fingerprints. Trivially spoofable, but a mismatch is a strong negative signal. |

## Testing guide

### Recommended testing workflow

```bash
# Step 1: Collect baseline once (saves API costs for subsequent runs)
llm-test baseline

# Step 2: Quick sanity check (fast, cheap — verifies connectivity and basic signals)
llm-test run --quick --baseline-cache cache/baseline.json --output terminal --output json

# Step 3: Full test (all 8 enabled probes, thorough but slower)
llm-test run --baseline-cache cache/baseline.json --output terminal --output json

# Step 4: Review detailed results
llm-test report results/latest.json        # terminal display
cat results/latest.json | jq '.detailed_results'  # raw JSON
```

### Testing specific concerns

```bash
# Suspect speed is too fast? Focus on latency
llm-test run --probe latency --baseline-cache cache/baseline.json

# Suspect a different model? Focus on reasoning + identity
llm-test run --probe reasoning --probe identity --probe baseline

# Test a single target out of many
llm-test run --target my-proxy --baseline-cache cache/baseline.json

# Full test with JSON output only (no terminal clutter, for CI/scripts)
llm-test run --output json --baseline-cache cache/baseline.json
```

### Interpreting results

- **All probes confidence < 0.75**: These probes are excluded from scoring (configurable via `scoring.confidence_threshold` in `config/default.yaml`). Usually means errors occurred — check `details.error` in the JSON report.
- **High score but low confidence**: The result looks good but the measurement was unreliable. Run more samples or check for intermittent errors.
- **Latency score = 1.0 with low confidence**: Baseline comparison unavailable. The probe fell back to absolute heuristics.
- **Identity score = 0.6**: The model identifies as "Claude" generically but not specifically as "Opus". Ambiguous — could be Opus with a system prompt override.

## Report output

### Terminal output

The terminal report shows:
- Provider info (type, model, URL) for each target
- A probe scores table with **Score** and **Confidence** columns
- Verdict classification and explanation
- Notes about which probes were excluded due to low confidence

### JSON report

When you add `--output json`, llm-test writes a timestamped report to `results/` (plus a `latest.json` copy). The report uses a **v2 format** with two sections:

**`targets`** — backwards-compatible summary:

```json
{
  "version": 2,
  "timestamp": "20260410_153000",
  "targets": {
    "my-proxy": {
      "overall_score": 0.82,
      "classification": "LIKELY_OPUS",
      "probe_scores": {"metadata": 1.0, "latency": 0.7, "reasoning": 0.85},
      "explanation": "Most probes are consistent with Opus, minor anomalies detected."
    }
  }
}
```

**`detailed_results`** — full diagnostic data for every target, probe, and API call:

```json
{
  "detailed_results": {
    "my-proxy": {
      "endpoint": {
        "name": "my-proxy",
        "provider": "anthropic_compatible",
        "base_url": "https://my-proxy.example.com",
        "model": "claude-opus-4-6"
      },
      "probes": [
        {
          "probe_name": "reasoning",
          "score": 0.85,
          "confidence": 0.9,
          "details": {"correct": 4, "total": 5, "accuracy": 0.8, "tasks": [...]},
          "api_calls": [
            {
              "model_reported": "claude-opus-4-6-20260301",
              "content": "The answer is 42 because...",
              "input_tokens": 385,
              "output_tokens": 120,
              "stop_reason": "end_turn",
              "latency_ms": 4521.3,
              "ttfb_ms": 1230.5,
              "tokens_per_sec": 26.5
            }
          ]
        }
      ]
    }
  }
}
```

### Report field reference

**Top level:**

| Field | Description |
|---|---|
| `version` | Report format version (currently `2`) |
| `timestamp` | UTC time of the test run (`YYYYMMDD_HHMMSS`) |
| `targets` | Summary scores per target (backwards compatible with v1) |
| `detailed_results` | Full diagnostic data per target |

**`targets.{name}`:**

| Field | Description |
|---|---|
| `overall_score` | Weighted aggregate score (0.0 - 1.0) |
| `classification` | One of: `GENUINE_OPUS`, `LIKELY_OPUS`, `SUSPICIOUS`, `LIKELY_DOWNGRADE`, `DEFINITE_DOWNGRADE` |
| `probe_scores` | Map of probe name to score (all probes, including excluded ones) |
| `explanation` | Human-readable interpretation of the verdict |

**`detailed_results.{name}.endpoint`:**

| Field | Description |
|---|---|
| `name` | Target name from `endpoints.yaml` |
| `provider` | `anthropic`, `anthropic_compatible`, or `openai_compatible` |
| `base_url` | API endpoint URL |
| `model` | Requested model name |

**`detailed_results.{name}.probes[]`:**

| Field | Description |
|---|---|
| `probe_name` | Probe identifier |
| `score` | 0.0 (not Opus) to 1.0 (consistent with Opus), clamped to this range |
| `confidence` | How reliable this measurement is (0.0 - 1.0). Probes below `confidence_threshold` (default 0.75) are excluded from the verdict |
| `details` | Probe-specific diagnostic data (see below) |
| `api_calls` | Array of every API call made by this probe |

**`details` per probe:**

| Probe | Key fields in `details` |
|---|---|
| metadata | `model_reported`, `model_expected`, `model_field_match`, `interesting_headers` |
| identity | `identity_votes` (vote counts per model family), `dominant_identity`, `prompts` (per-prompt results) |
| latency | `per_length` (stats per prompt length), `target_median_tps`, `speed_ratio` |
| reasoning | `correct`, `total`, `accuracy`, `tasks` (per-task pass/fail with response previews) |
| needle | `results` (per context length and depth), `accuracy` |
| baseline | `avg_similarity`, `comparisons` (per-prompt similarity and length ratios) |
| knowledge | `results` (per-fact match results with extracted dates) |
| style | Linguistic feature scores and comparisons |

**`api_calls[]`:**

| Field | Description |
|---|---|
| `model_reported` | Model name returned by the API |
| `content` | Full model response text |
| `input_tokens` | Prompt token count |
| `output_tokens` | Response token count |
| `stop_reason` | Why the model stopped (`end_turn`, `max_tokens`, etc.) |
| `latency_ms` | Total request latency in milliseconds |
| `ttfb_ms` | Time to first byte in milliseconds |
| `tokens_per_sec` | Output throughput (output_tokens / latency_seconds) |

The `llm-test report` command can display both old (v1, no detailed data) and new (v2) format files.

## Data storage

All persistent data is stored in two directories:

```
cache/                              Baseline response cache (git-ignored)
  baseline.json                     Cached baseline responses for all probes

results/                            Test reports (git-ignored)
  report_YYYYMMDD_HHMMSS.json       Timestamped report per run (v2 format)
  latest.json                       Copy of the most recent report
```

**`cache/baseline.json`** stores cached baseline API responses so you don't need to call the official Anthropic API on every run. Each entry contains the full API response (model output, tokens, timing), keyed by a SHA-256 hash of the request parameters. Generated by `llm-test baseline`, consumed by `llm-test run --baseline-cache`.

**`results/report_*.json`** stores the complete test record for each run. Every run with `--output json` creates a new timestamped file and overwrites `latest.json`. Reports are self-contained — they include the endpoint configuration, all probe scores with confidence, diagnostic details, and raw API call data. Reports are never deleted automatically; old reports accumulate in `results/` for historical comparison.

**Not stored** (excluded to avoid leaking secrets): API keys, the `api_key_env` variable name, and the full `raw_json`/`raw_headers` from API responses (these echo the request and bloat the file).

## Scoring formula

```
final_score = sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)
```

Each probe's contribution is scaled by both its weight (how important the dimension is) and its confidence (how reliable this particular measurement was). A probe that errors out gets confidence=0.1 and score=0.5, effectively removing it from the final calculation.

**Confidence threshold**: Probes with confidence below `scoring.confidence_threshold` (default: 0.75, configurable in `config/default.yaml`) are excluded from the aggregation entirely. Their scores are still recorded in the report but do not affect the verdict. This prevents unreliable measurements (e.g., from errors or cache misses) from skewing the final score. Excluded probes are noted in the explanation text.

**Score clamping**: All probe scores and confidence values are automatically clamped to [0.0, 1.0] to prevent edge cases from producing invalid aggregations.

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

## Web application

llm-test includes a built-in web interface for users who want to test their API proxy without touching the command line.

```bash
llm-test serve                    # Start on http://127.0.0.1:8000
llm-test serve --port 3000        # Custom port
llm-test serve --reload           # Dev mode with auto-reload
```

### Features

- **Homepage** — Enter your proxy's base URL, API key, and protocol type, then click to start testing. Real-time progress shows each probe's result as it completes via Server-Sent Events.
- **Report page** — Shareable report with verdict, probe score breakdown, and full diagnostic explanation. Each report gets a unique URL (`/report/{id}`).
- **Methodology page** — Detailed explanation of all 10 probes, scoring formula, design principles, and known limitations.
- **User accounts** — Optional registration with username/password. Logged-in users' reports are saved to their account.

### Architecture

The web app is a FastAPI application that directly imports and runs the existing probe code on the server. This protects probe prompts, scoring logic, and baseline data from being exposed to the client.

- **Backend**: FastAPI + Jinja2 templates + SQLAlchemy async
- **Frontend**: Tailwind CSS (dark theme) + Alpine.js for interactivity
- **Database**: SQLite by default (`data/llm_test.db`), PostgreSQL for production (set `DATABASE_URL`)
- **Auth**: bcrypt + JWT stored in cookies
- **Real-time progress**: SSE (Server-Sent Events)

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/llm_test.db` | Database connection string. Use `postgresql+asyncpg://...` for production. |
| `SECRET_KEY` | `dev-secret-change-in-production` | JWT signing key. **Must be changed in production.** |

## Project structure

```
src/llm_test/
  __init__.py
  cli.py          Click CLI entry point (run, report, baseline, serve)
  config.py       YAML + Pydantic config loading
  client.py       Unified API client (anthropic SDK + httpx)
  cache.py        Baseline response caching (data model + I/O)
  runner.py       Async probe orchestrator with progress display
  scoring.py      Weighted confidence aggregation, Verdict + RunResult
  report.py       Rich terminal tables + JSON output (v2 with full details)
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
  web/
    app.py            FastAPI application factory
    database.py       SQLAlchemy async engine + session
    models.py         User + TestReport database models
    auth.py           bcrypt + JWT authentication
    schemas.py        Request validation schemas
    templates_conf.py Jinja2 templates setup
    routes/
      pages.py        HTML page routes (/, /methodology, /report, /login, /register)
      auth.py         Register/login API
      api.py          Test submission + SSE progress streaming
    templates/        Jinja2 HTML templates (dark theme)
    static/           CSS + JS assets

config/
  default.yaml            Probe weights, parameters, output settings
  endpoints.yaml.example  Endpoint config template

data/                     SQLite database (git-ignored)
cache/                    Baseline response cache (git-ignored)
results/                  CLI runtime output (git-ignored)
alembic/                  Database migrations (for production PostgreSQL)
```

## Related tools

This toolkit is self-contained but draws on ideas from these projects:

- **[Promptfoo](https://github.com/promptfoo/promptfoo)** -- CLI for LLM output evaluation and comparison. Useful as an external cross-check.
- **[LLMTest_NeedleInAHaystack](https://github.com/gkamradt/LLMTest_NeedleInAHaystack)** -- The original needle-in-a-haystack test by Gregory Kamradt. Our `needle` probe implements a similar methodology.
- **[lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)** -- Academic benchmark framework with hundreds of datasets. Can complement llm-test for deep capability profiling.

## Baseline caching

By default, every `llm-test run` calls the official Anthropic API for baseline comparisons in 4 probes (baseline, latency, style, knowledge). Since the content-based comparisons are stable for the same model at temperature 0, you can collect baseline responses once and reuse them across runs.

```bash
# Step 1: Collect baseline (one-time, or refresh when the model changes)
llm-test baseline

# Step 2: Use the cache in subsequent runs
llm-test run --baseline-cache cache/baseline.json
```

**How it works:**

- `llm-test baseline` runs all baseline-using probes against the official API and saves every response to `cache/baseline.json` (configurable via `--output`).
- `llm-test run --baseline-cache` loads the cache and serves responses from it instead of calling the API. Probes receive a `CachedEndpointClient` that implements the same interface as `EndpointClient` — no probe code changes are needed.
- The **latency probe is excluded by default** because its timing data (tokens/sec, latency) depends on real-time server load and would be misleading if cached. When excluded, the latency probe falls back to absolute throughput heuristics. Use `--include-latency` to override.
- The cache includes a `config_hash` of the baseline endpoint configuration. If you change the baseline model or URL, a warning is printed and you should re-run `llm-test baseline`.
- Cache keys are SHA-256 hashes of `(messages, system, max_tokens, temperature)`. If a probe's prompts are updated, the cache automatically misses and that probe degrades gracefully (score=0.5, confidence=0.1).

**When to refresh the cache:**

- After a new Claude model version is deployed
- After changing the baseline model in `config/endpoints.yaml`
- After modifying probe prompts or parameters in `config/default.yaml`

## Cost considerations

A full test run makes many API calls to both the baseline and each target. Approximate per-target costs at default settings:

- **Quick mode** (`--quick`): ~15 API calls, minimal cost
- **Full run**: ~80-100 API calls, including some with long contexts (needle probe). Budget roughly $1-3 per target depending on context lengths.
- **With baseline cache** (`--baseline-cache`): Eliminates all baseline API calls (~15-20 per target), cutting cost roughly in half.

To reduce cost further, disable expensive probes (`needle`, `baseline`) in `config/default.yaml` or use `--probe` to run only specific probes.

## License

MIT
