# CLAUDE.md

## Project overview

llm-test is a Python CLI tool that verifies whether an API endpoint is truly serving Claude Opus, or has been downgraded to a cheaper model. It runs 10 independent probes (reasoning, latency, needle-in-a-haystack, etc.) and produces a weighted confidence score.

## Language and runtime

- Python 3.11+, async throughout (asyncio)
- Package layout: `src/llm_test/` (setuptools src-layout)
- CLI: Click. Install with `pip install -e .`, run with `llm-test`
- Dependencies: anthropic, httpx, click, rich, pyyaml, numpy, pydantic

## Build and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Must have config/endpoints.yaml with real API keys to run:
llm-test run           # full suite
llm-test run --quick   # fast mode (metadata + identity + latency)
```

## Test

```bash
pytest tests/
```

No tests are written yet -- `tests/` is empty and awaiting implementation.

## Architecture

### Core modules (`src/llm_test/`)

- **config.py** -- Loads `config/default.yaml` (probe settings) and `config/endpoints.yaml` (API endpoints) into Pydantic models. `AppConfig` is the root config object.
- **client.py** -- `EndpointClient` wraps three provider types (anthropic SDK, anthropic-compatible httpx, openai-compatible httpx) behind a single `send_message()` async method. Returns `APIResponse` dataclass with raw JSON, headers, and timing data (latency_ms, ttfb_ms, tokens_per_sec).
- **runner.py** -- `run_probes()` orchestrates all enabled probes sequentially per target, with Rich progress display. Returns `{target_name: Verdict}`.
- **scoring.py** -- `compute_verdict()` aggregates probe results using `sum(score * weight * confidence) / sum(weight * confidence)`. Classifies into 5 tiers (GENUINE_OPUS through DEFINITE_DOWNGRADE).
- **report.py** -- Terminal output via Rich tables + JSON file output to `results/`.
- **cli.py** -- Click commands: `run` (execute probes) and `report` (re-display saved JSON).

### Probe system (`src/llm_test/probes/`)

- **`__init__.py`** -- `BaseProbe` ABC, `ProbeResult` dataclass, `@register_probe` decorator, and probe registry. `_load_probes()` imports all probe modules at package init time.
- Each probe file defines a class decorated with `@register_probe` that implements `async run(target, baseline, config) -> ProbeResult`.
- ProbeResult has: `score` (0-1), `confidence` (0-1), `details` (dict), `raw_responses` (list of APIResponse).

### Adding a new probe

1. Create `src/llm_test/probes/my_probe.py` with a class inheriting `BaseProbe` and decorated with `@register_probe`
2. Add the import in `probes/__init__.py` inside `_load_probes()`
3. Optionally add config entry in `config/default.yaml` with `enabled`, `weight`, and custom params

### Key design patterns

- **Asymmetric latency scoring**: Faster than baseline = suspicious (smaller model), slower = fine (proxy overhead). See `latency.py:_score_latency()`.
- **Baseline-relative comparison**: Most probes compare target against a known-good Anthropic endpoint rather than using absolute thresholds.
- **Weighted confidence aggregation**: Each probe has both a weight (importance of dimension) and a confidence (reliability of this measurement). Both factor into the final score.
- **Graceful degradation**: If a probe errors, it returns score=0.5, confidence=0.1, effectively removing it from the calculation.

## Config files

- `config/default.yaml` -- Probe weights, enabled flags, sample counts, context lengths
- `config/endpoints.yaml` -- API endpoint definitions (git-ignored, contains secrets)
- `config/endpoints.yaml.example` -- Template for endpoints config

## Code conventions

- Type hints throughout, `from __future__ import annotations` in every file
- Dataclasses for data containers (`APIResponse`, `ProbeResult`, `Verdict`)
- Pydantic BaseModel for config objects
- All API calls are async
- No global state; config passed as arguments
