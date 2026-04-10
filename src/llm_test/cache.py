"""Baseline response cache — data model, serialization, and I/O."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .client import APIResponse
from .config import EndpointConfig


class CacheEntry(BaseModel):
    prompt_hash: str
    messages: list[dict[str, str]]
    system: str | None
    max_tokens: int
    temperature: float
    response: dict[str, Any]


class BaselineCacheFile(BaseModel):
    version: int = 1
    created_at: str
    model: str
    config_hash: str
    entries: dict[str, CacheEntry] = Field(default_factory=dict)
    excluded_probes: list[str] = Field(default_factory=list)


class CacheError(Exception):
    pass


class CacheMissError(CacheError):
    pass


def compute_prompt_hash(
    messages: list[dict[str, str]],
    system: str | None,
    max_tokens: int,
    temperature: float,
) -> str:
    """Deterministic SHA-256 hash of call parameters."""
    canonical = json.dumps(
        {"messages": messages, "system": system,
         "max_tokens": max_tokens, "temperature": temperature},
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_config_hash(config: EndpointConfig) -> str:
    """Hash of baseline endpoint identity (model + base_url + provider)."""
    canonical = json.dumps(
        {"model": config.model, "base_url": config.base_url,
         "provider": config.provider},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def apiresponse_to_dict(resp: APIResponse) -> dict[str, Any]:
    return {
        "model_reported": resp.model_reported,
        "content": resp.content,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "stop_reason": resp.stop_reason,
        "raw_json": resp.raw_json,
        "raw_headers": resp.raw_headers,
        "latency_ms": resp.latency_ms,
        "ttfb_ms": resp.ttfb_ms,
        "tokens_per_sec": resp.tokens_per_sec,
    }


def dict_to_apiresponse(d: dict[str, Any]) -> APIResponse:
    return APIResponse(
        model_reported=d["model_reported"],
        content=d["content"],
        input_tokens=d["input_tokens"],
        output_tokens=d["output_tokens"],
        stop_reason=d["stop_reason"],
        raw_json=d.get("raw_json", {}),
        raw_headers=d.get("raw_headers", {}),
        latency_ms=d.get("latency_ms", 0.0),
        ttfb_ms=d.get("ttfb_ms", 0.0),
        tokens_per_sec=d.get("tokens_per_sec", 0.0),
    )


def save_cache(cache: BaselineCacheFile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache.model_dump(), f, indent=2, ensure_ascii=False)


def load_cache(path: Path) -> BaselineCacheFile:
    try:
        with open(path) as f:
            data = json.load(f)
        return BaselineCacheFile(**data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise CacheError(f"Corrupt or invalid cache file {path}: {e}") from e


def create_cache_file(
    config: EndpointConfig,
    entries: dict[str, CacheEntry],
    excluded_probes: list[str] | None = None,
) -> BaselineCacheFile:
    return BaselineCacheFile(
        created_at=datetime.now(timezone.utc).isoformat(),
        model=config.model,
        config_hash=compute_config_hash(config),
        entries=entries,
        excluded_probes=excluded_probes or [],
    )
