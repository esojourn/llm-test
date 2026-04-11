"""Pydantic request/response schemas for the web API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TestRequest(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    provider: str = Field(pattern=r"^(anthropic_compatible|openai_compatible)$")
    model: str = "claude-opus-4-0-20250514"
