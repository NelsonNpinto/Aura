from typing import Any, Literal

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, Field, field_validator, model_validator


class GenerateRequest(BaseModel):
    seed: int = 42
    format: dict | Literal["json"] | None = None
    model: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_./:-]*$")
    prompt: str = Field(min_length=1, max_length=32000)
    system: str = Field(default="", max_length=16000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=8192)

    @field_validator("prompt")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Prompt cannot be blank")
        return value


class Check(BaseModel):
    kind: Literal[
        "non_empty",
        "valid_json",
        "json_schema",
        "required_keywords",
        "forbidden_phrases",
        "exact_match",
    ]
    values: list[str] = Field(default_factory=list, max_length=100)
    expected: str | None = Field(default=None, max_length=64000)
    schema_definition: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_check(self):
        if self.kind in ("required_keywords", "forbidden_phrases"):
            if not self.values or any(not v.strip() or len(v) > 1000 for v in self.values):
                raise ValueError(
                    "Provide non-empty keywords/phrases (maximum 1000 characters each)"
                )
        if self.kind == "exact_match" and self.expected is None:
            raise ValueError("Exact match requires an expected answer")
        if self.kind == "json_schema":
            if self.schema_definition is None:
                raise ValueError("JSON schema check requires schema_definition")
            try:
                Draft202012Validator.check_schema(self.schema_definition)
            except SchemaError as exc:
                raise ValueError("Invalid JSON schema") from exc

            # Never resolve externally supplied references over network or filesystem.
            def has_reference(node):
                if isinstance(node, dict):
                    return (
                        "$ref" in node
                        or "$dynamicRef" in node
                        or any(has_reference(v) for v in node.values())
                    )
                return isinstance(node, list) and any(has_reference(v) for v in node)

            if has_reference(self.schema_definition):
                raise ValueError("Schema references are not supported; inline the schema")
        return self


class EvaluationRequest(BaseModel):
    name: str = Field(default="Response evaluation", min_length=1, max_length=200)
    response: str = Field(max_length=64000)
    trace_id: str | None = None
    checks: list[Check] = Field(min_length=1, max_length=30)
    threshold: float = Field(default=1, ge=0, le=1)
