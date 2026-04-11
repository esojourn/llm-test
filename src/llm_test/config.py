"""Configuration loading for llm-test."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EndpointConfig(BaseModel):
    name: str = "baseline"
    provider: str  # "anthropic" | "anthropic_compatible" | "openai_compatible"
    api_key_env: str = ""
    base_url: str = ""
    model: str = ""
    api_key_inline: str = ""  # Direct key (used by web API, bypasses env var)

    @property
    def api_key(self) -> str:
        if self.api_key_inline:
            return self.api_key_inline
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class ProbeConfig(BaseModel):
    enabled: bool = True
    weight: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class ScoringConfig(BaseModel):
    confidence_threshold: float = 0.75


class OutputConfig(BaseModel):
    format: list[str] = Field(default_factory=lambda: ["terminal", "json"])
    results_dir: str = "results/"


class AppConfig(BaseModel):
    baseline: EndpointConfig
    targets: list[EndpointConfig]
    probes: dict[str, ProbeConfig]
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_config(
    config_path: str | Path = "config/default.yaml",
    endpoints_path: str | Path = "config/endpoints.yaml",
) -> AppConfig:
    config_path = Path(config_path)
    endpoints_path = Path(endpoints_path)

    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    with open(endpoints_path) as f:
        raw_endpoints = yaml.safe_load(f)

    # Parse probe configs
    probes: dict[str, ProbeConfig] = {}
    for probe_name, probe_data in raw_config.get("probes", {}).items():
        probes[probe_name] = ProbeConfig(**probe_data)

    # Parse endpoints
    baseline = EndpointConfig(**raw_endpoints["baseline"])
    targets = [
        EndpointConfig(**t) for t in raw_endpoints.get("targets", [])
    ]

    return AppConfig(
        baseline=baseline,
        targets=targets,
        probes=probes,
        scoring=ScoringConfig(**raw_config.get("scoring", {})),
        output=OutputConfig(**raw_config.get("output", {})),
    )
