"""Unified API client with timing support."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

from .config import EndpointConfig

# Avoid circular import — cache types are imported lazily where needed.


@dataclass
class APIResponse:
    model_reported: str
    content: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    raw_json: dict[str, Any]
    raw_headers: dict[str, str]
    latency_ms: float = 0.0
    ttfb_ms: float = 0.0
    tokens_per_sec: float = 0.0


class EndpointUnreachableError(Exception):
    """Raised when the endpoint fails a connectivity pre-check."""


class EndpointClient:
    """Wraps anthropic SDK and raw httpx for different provider types."""

    def __init__(self, config: EndpointConfig):
        self.config = config
        self.name = config.name

    async def preflight_check(self) -> None:
        """Send a minimal request to verify the endpoint is reachable.

        Raises ``EndpointUnreachableError`` with a user-friendly message on
        failure, so callers can bail out before running the full probe suite.
        """
        try:
            await self.send_message(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                temperature=0.0,
            )
        except httpx.HTTPStatusError as e:
            raise EndpointUnreachableError(
                f"Endpoint returned {e.response.status_code} ({e.response.reason_phrase}). "
                f"URL: {self.config.base_url}"
            ) from e
        except anthropic.APIStatusError as e:
            raise EndpointUnreachableError(
                f"Endpoint returned {e.status_code}. "
                f"URL: {self.config.base_url}"
            ) from e
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise EndpointUnreachableError(
                f"Cannot connect to endpoint: {self.config.base_url} — {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise EndpointUnreachableError(
                f"Endpoint timed out: {self.config.base_url} — {e}"
            ) from e

    async def send_message(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> APIResponse:
        provider = self.config.provider
        if provider == "anthropic":
            return await self._send_anthropic(messages, system, max_tokens, temperature)
        elif provider == "anthropic_compatible":
            return await self._send_anthropic_compatible(messages, system, max_tokens, temperature)
        elif provider == "openai_compatible":
            return await self._send_openai_compatible(messages, system, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def _send_anthropic(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> APIResponse:
        client = anthropic.AsyncAnthropic(api_key=self.config.api_key)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        t_start = time.perf_counter()
        response = await client.messages.create(**kwargs)
        t_end = time.perf_counter()

        latency_ms = (t_end - t_start) * 1000
        output_tokens = response.usage.output_tokens
        tokens_per_sec = output_tokens / (latency_ms / 1000) if latency_ms > 0 else 0

        raw_json = response.model_dump()
        return APIResponse(
            model_reported=response.model,
            content=response.content[0].text if response.content else "",
            input_tokens=response.usage.input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.stop_reason or "",
            raw_json=raw_json,
            raw_headers={},
            latency_ms=latency_ms,
            ttfb_ms=latency_ms,  # non-streaming, TTFB ≈ total latency
            tokens_per_sec=tokens_per_sec,
        )

    async def _send_anthropic_compatible(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> APIResponse:
        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=300) as client:
            t_start = time.perf_counter()
            resp = await client.post(url, json=body, headers=headers)
            t_end = time.perf_counter()

        resp.raise_for_status()
        data = resp.json()
        latency_ms = (t_end - t_start) * 1000
        output_tokens = data.get("usage", {}).get("output_tokens", 0)
        tokens_per_sec = output_tokens / (latency_ms / 1000) if latency_ms > 0 else 0

        content = ""
        if data.get("content"):
            content = data["content"][0].get("text", "")

        return APIResponse(
            model_reported=data.get("model", ""),
            content=content,
            input_tokens=data.get("usage", {}).get("input_tokens", 0),
            output_tokens=output_tokens,
            stop_reason=data.get("stop_reason", ""),
            raw_json=data,
            raw_headers=dict(resp.headers),
            latency_ms=latency_ms,
            ttfb_ms=latency_ms,
            tokens_per_sec=tokens_per_sec,
        )

    async def _send_openai_compatible(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> APIResponse:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        body = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=300) as client:
            t_start = time.perf_counter()
            resp = await client.post(url, json=body, headers=headers)
            t_end = time.perf_counter()

        resp.raise_for_status()
        data = resp.json()
        latency_ms = (t_end - t_start) * 1000

        usage = data.get("usage", {})
        output_tokens = usage.get("completion_tokens", 0)
        tokens_per_sec = output_tokens / (latency_ms / 1000) if latency_ms > 0 else 0

        content = ""
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        return APIResponse(
            model_reported=data.get("model", ""),
            content=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=output_tokens,
            stop_reason=choices[0].get("finish_reason", "") if choices else "",
            raw_json=data,
            raw_headers=dict(resp.headers),
            latency_ms=latency_ms,
            ttfb_ms=latency_ms,
            tokens_per_sec=tokens_per_sec,
        )


class NullEndpointClient:
    """Returns placeholder responses without making API calls.

    Used as a dummy target during baseline collection so only the
    baseline (recording) side actually hits the API.
    """

    name = "null"

    async def send_message(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> APIResponse:
        return APIResponse(
            model_reported="null",
            content="",
            input_tokens=0,
            output_tokens=0,
            stop_reason="null",
            raw_json={},
            raw_headers={},
        )


class CachedEndpointClient:
    """Drop-in replacement for EndpointClient that serves from a baseline cache."""

    def __init__(self, cache: Any, name: str = "baseline (cached)"):
        # cache is a BaselineCacheFile instance (imported lazily to avoid circular import)
        self.name = name
        self.config: EndpointConfig | None = None
        self._cache = cache

    async def send_message(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> APIResponse:
        from .cache import CacheMissError, compute_prompt_hash, dict_to_apiresponse

        key = compute_prompt_hash(messages, system, max_tokens, temperature)
        entry = self._cache.entries.get(key)
        if entry is None:
            raise CacheMissError(
                f"No cached response for prompt hash {key[:16]}... "
                f"Re-run 'llm-test baseline' to refresh the cache."
            )
        return dict_to_apiresponse(entry.response)


class RecordingEndpointClient:
    """Wraps EndpointClient, forwards calls, and records responses for caching."""

    def __init__(self, inner: EndpointClient):
        self.inner = inner
        self.name = inner.name
        self.config = inner.config
        self.recorded: dict[str, Any] = {}  # prompt_hash -> CacheEntry

    async def send_message(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> APIResponse:
        from .cache import CacheEntry, apiresponse_to_dict, compute_prompt_hash

        response = await self.inner.send_message(messages, system, max_tokens, temperature)
        key = compute_prompt_hash(messages, system, max_tokens, temperature)
        self.recorded[key] = CacheEntry(
            prompt_hash=key,
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            response=apiresponse_to_dict(response),
        )
        return response
