"""Loads and validates tasks.yaml."""

from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TASKS_FILE = Path(__file__).with_name("tasks.yaml")


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpm: int = Field(ge=1)
    tpm: int = Field(ge=1)
    rpd: int = Field(ge=1)
    price_in: int = Field(ge=0, description="micro-USD per 1M input tokens (list price)")
    price_out: int = Field(ge=0)
    open_weight: bool = False
    vision: bool = False
    free_tier_geo_restricted: bool = False
    local_only: bool = False

    def cost_microusd(self, tokens_in: int, tokens_out: int) -> int:
        return round((tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000)


class PromptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: Literal["production", "staging", "canary"] = "production"


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    weight: float = Field(gt=0, le=1)
    chain: list[str] | None = None
    prompt_label: Literal["production", "staging", "canary"] | None = None


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain: list[str] = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1, le=16384)
    timeout_s: float = Field(gt=0, le=120)
    cache: Literal["exact", "none", "semantic"]
    budget_class: Literal["interactive", "eval", "batch"]
    output_schema: str | None = None
    prompt: PromptRef
    open_weight_only: bool = False
    variants: list[Variant] = Field(default_factory=list)

    def schema_model(self) -> type[BaseModel] | None:
        if not self.output_schema:
            return None
        mod, _, attr = self.output_schema.partition(":")
        cls = getattr(importlib.import_module(mod), attr)
        assert isinstance(cls, type) and issubclass(cls, BaseModel)
        return cls


class RouterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: dict[str, ModelSpec]
    tasks: dict[str, TaskSpec]

    @model_validator(mode="after")
    def _chains_known(self) -> RouterConfig:
        for name, t in self.tasks.items():
            for m in t.chain + [m for v in t.variants for m in (v.chain or [])]:
                if m not in self.models:
                    raise ValueError(f"task {name}: unknown model {m}")
            if t.open_weight_only and any(not self.models[m].open_weight for m in t.chain):
                raise ValueError(f"task {name}: open_weight_only but chain has closed models")
        return self


def parse_config(raw: dict[str, Any]) -> RouterConfig:
    defaults = raw.get("defaults", {})
    tasks = {k: {**defaults, **v} for k, v in raw.get("tasks", {}).items()}
    return RouterConfig(models=raw["models"], tasks=tasks)


@lru_cache
def load_config(path: str | None = None) -> RouterConfig:
    raw = yaml.safe_load(Path(path or TASKS_FILE).read_text())
    return parse_config(raw)
