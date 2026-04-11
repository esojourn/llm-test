# CLAUDE.md

## Project overview

llm-test is a Python tool that verifies whether an API endpoint is truly serving Claude Opus, or has been downgraded to a cheaper model. It runs 10 independent probes (reasoning, latency, needle-in-a-haystack, etc.) and produces a weighted confidence score. Available as both a CLI tool and a web application.

## Language and runtime

- Python 3.11+, async throughout (asyncio)
- Package layout: `src/llm_test/` (setuptools src-layout)
- CLI: Click. Install with `pip install -e .`, run with `llm-test`
- Web: FastAPI + Jinja2 + Tailwind CSS + Alpine.js
- Dependencies: anthropic, httpx, click, rich, pyyaml, pydantic, fastapi, uvicorn, sqlalchemy, bcrypt, python-jose

## Build and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# CLI mode — must have config/endpoints.yaml with real API keys:
llm-test run           # full suite
llm-test run --quick   # fast mode (metadata + identity + latency)

# Web mode — no config needed, users provide their own API keys:
llm-test serve              # http://127.0.0.1:8000
llm-test serve --reload     # dev mode with auto-reload
```

## Test

```bash
pytest tests/
```

No tests are written yet -- `tests/` is empty and awaiting implementation.

## Architecture

### Core modules (`src/llm_test/`)

- **config.py** -- Loads `config/default.yaml` (probe settings) and `config/endpoints.yaml` (API endpoints) into Pydantic models. `AppConfig` is the root config object. `EndpointConfig` supports both env-var based keys (`api_key_env`) and direct inline keys (`api_key_inline`) for web use.
- **client.py** -- `EndpointClient` wraps three provider types (anthropic SDK, anthropic-compatible httpx, openai-compatible httpx) behind a single `send_message()` async method. Returns `APIResponse` dataclass with raw JSON, headers, and timing data (latency_ms, ttfb_ms, tokens_per_sec).
- **runner.py** -- `run_probes()` orchestrates all enabled probes sequentially per target, with Rich progress display. Returns `{target_name: RunResult}`.
- **scoring.py** -- `compute_verdict()` aggregates probe results using `sum(score * weight * confidence) / sum(weight * confidence)`. Classifies into 5 tiers (GENUINE_OPUS through DEFINITE_DOWNGRADE).
- **report.py** -- Terminal output via Rich tables + JSON file output to `results/`.
- **cli.py** -- Click commands: `run` (execute probes), `report` (re-display saved JSON), `baseline` (collect baseline cache), `serve` (start web server).

### Probe system (`src/llm_test/probes/`)

- **`__init__.py`** -- `BaseProbe` ABC, `ProbeResult` dataclass, `@register_probe` decorator, and probe registry. `_load_probes()` imports all probe modules at package init time.
- Each probe file defines a class decorated with `@register_probe` that implements `async run(target, baseline, config) -> ProbeResult`.
- ProbeResult has: `score` (0-1), `confidence` (0-1), `details` (dict), `raw_responses` (list of APIResponse).

### Web application (`src/llm_test/web/`)

- **app.py** -- FastAPI application factory with lifespan (auto-creates DB tables on startup).
- **database.py** -- SQLAlchemy async engine + session. Defaults to SQLite (`data/llm_test.db`) for development; set `DATABASE_URL` env var for PostgreSQL in production.
- **models.py** -- DB models: `User` (auth), `TestReport` (persisted test results with JSON probe data).
- **auth.py** -- bcrypt password hashing + JWT token creation/verification.
- **schemas.py** -- Pydantic request validation for API endpoints.
- **templates_conf.py** -- Jinja2 templates configuration (separate module to avoid circular imports).
- **routes/pages.py** -- Server-rendered HTML pages: `/` (homepage), `/methodology`, `/report/{id}`, `/login`, `/register`.
- **routes/auth.py** -- Register/login API endpoints returning JWT tokens.
- **routes/api.py** -- `POST /api/test` starts a test run in background, `GET /api/test/{id}/stream` provides SSE progress updates. Tests run on the server using existing probe code via direct Python import.
- **templates/** -- Jinja2 HTML templates with Tailwind dark theme (Linear-style) and Alpine.js for interactivity.

### Adding a new probe

1. Create `src/llm_test/probes/my_probe.py` with a class inheriting `BaseProbe` and decorated with `@register_probe`
2. Add the import in `probes/__init__.py` inside `_load_probes()`
3. Optionally add config entry in `config/default.yaml` with `enabled`, `weight`, and custom params

### Key design patterns

- **Asymmetric latency scoring**: Faster than baseline = suspicious (smaller model), slower = fine (proxy overhead). See `latency.py:_score_latency()`.
- **Baseline-relative comparison**: Most probes compare target against a known-good Anthropic endpoint rather than using absolute thresholds.
- **Weighted confidence aggregation**: Each probe has both a weight (importance of dimension) and a confidence (reliability of this measurement). Both factor into the final score.
- **Graceful degradation**: If a probe errors, it returns score=0.5, confidence=0.1, effectively removing it from the calculation.
- **Backend test execution**: Web tests run on the server to protect probe prompts, scoring logic, and baseline data from exposure to the client.
- **SSE progress streaming**: Real-time probe progress via Server-Sent Events (`EventSource` on the client, `StreamingResponse` on the server).

## Config files

- `config/default.yaml` -- Probe weights, enabled flags, sample counts, context lengths
- `config/endpoints.yaml` -- API endpoint definitions (git-ignored, contains secrets)
- `config/endpoints.yaml.example` -- Template for endpoints config

## Data files

- `data/llm_test.db` -- SQLite database for web app (dev mode, git-ignored)
- `cache/baseline.json` -- Cached baseline responses (git-ignored)
- `results/` -- CLI JSON reports (git-ignored)
- `alembic/` -- Database migrations (for PostgreSQL production use)

## Code conventions

- Type hints throughout, `from __future__ import annotations` in every file
- Dataclasses for data containers (`APIResponse`, `ProbeResult`, `Verdict`)
- Pydantic BaseModel for config objects
- All API calls are async
- No global state; config passed as arguments
- Web templates use Jinja2 + Tailwind CSS (CDN for dev) + Alpine.js (CDN)
- Dark theme design following Linear.app style
