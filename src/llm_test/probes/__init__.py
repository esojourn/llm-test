"""Probe base class and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..client import APIResponse, EndpointClient


@dataclass
class ProbeResult:
    probe_name: str
    score: float  # 0.0 (definitely not Opus) to 1.0 (consistent with Opus)
    confidence: float  # How confident this probe is in its score
    details: dict[str, Any] = field(default_factory=dict)
    raw_responses: list[APIResponse] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = max(0.0, min(1.0, self.score))
        self.confidence = max(0.0, min(1.0, self.confidence))


class BaseProbe(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult: ...


_PROBE_REGISTRY: dict[str, type[BaseProbe]] = {}


def register_probe(cls: type[BaseProbe]) -> type[BaseProbe]:
    _PROBE_REGISTRY[cls.name] = cls
    return cls


def get_probe(name: str) -> BaseProbe:
    if name not in _PROBE_REGISTRY:
        raise KeyError(f"Unknown probe: {name}. Available: {list(_PROBE_REGISTRY.keys())}")
    return _PROBE_REGISTRY[name]()


def get_all_probes() -> dict[str, BaseProbe]:
    return {name: cls() for name, cls in _PROBE_REGISTRY.items()}


# Import all probe modules to trigger registration
def _load_probes() -> None:
    from . import (  # noqa: F401
        baseline,
        identity,
        knowledge,
        latency,
        logprobs,
        metadata,
        needle,
        reasoning,
        style,
        sysprompt,
    )


_load_probes()
