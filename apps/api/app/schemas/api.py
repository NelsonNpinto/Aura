"""Request/response models. Explicit bounds on every field; unknown fields rejected (§B5)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlaygroundRun(Strict):
    task: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_0-9]+$")
    variables: dict[str, str] = Field(default_factory=dict, max_length=20)


class PromptCreate(Strict):
    system: str = Field(default="", max_length=20_000)
    template: str = Field(min_length=1, max_length=20_000)
    variables_schema: dict[str, object] = Field(default_factory=dict)
    config: dict[str, object] = Field(default_factory=dict)


class LabelSet(Strict):
    version: int = Field(ge=1, le=1_000_000)


class SearchRequest(Strict):
    query: str = Field(min_length=2, max_length=500)
    doc_types: list[str] | None = Field(default=None, max_length=10)
    as_of: date | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class AskRequest(Strict):
    question: str = Field(min_length=3, max_length=500)
    doc_types: list[str] | None = Field(default=None, max_length=10)


class ApiKeyCreate(Strict):
    name: str = Field(min_length=1, max_length=100)
    roles: list[Literal["clerk", "approver", "controller", "auditor", "admin"]] = Field(
        min_length=1, max_length=5
    )
