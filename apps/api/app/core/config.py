"""Typed settings loaded from the environment (§B17). Secrets are SecretStr and never logged."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "preview", "production"]


def normalize_pg_url(url: str) -> str:
    """Accept postgres:// / postgresql:// (Neon's format) and select the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env.local", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = "local"
    git_sha: str = "dev"
    log_level: str = "INFO"
    web_origin: str = "http://localhost:3000"

    database_url: str = "postgresql://aura:aura-local-only@localhost:5434/aura"
    database_url_unpooled: str | None = None

    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: SecretStr | None = None

    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: SecretStr | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://us.cloud.langfuse.com"
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    enable_bedrock: bool = False
    aws_region: str = "us-east-1"
    ollama_base_url: str | None = None
    router_fault_injection: str = ""

    blob_read_write_token: SecretStr | None = None
    local_blob_dir: str = ".local/blob"

    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "aura/ms-marco-MiniLM-L-6-v2-int8"
    fastembed_cache_dir: str = "model_cache"
    kb_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    kb_max_pages: int = Field(default=60, ge=1)

    aura_jwks_url: str = "http://localhost:3000/api/auth/jwks"
    aura_jwt_issuer: str = "http://localhost:3000"
    aura_jwt_audience: str = "aura-api"

    turnstile_secret_key: SecretStr | None = None

    daily_run_budget: int = Field(default=200, ge=0)
    guest_daily_runs: int = Field(default=10, ge=0)
    org_daily_runs: int = Field(default=100, ge=0)
    rate_limit_per_minute: int = Field(default=60, ge=1)

    max_body_bytes: int = 12 * 1024 * 1024

    @field_validator("database_url", "database_url_unpooled")
    @classmethod
    def _driver(cls, v: str | None) -> str | None:
        return normalize_pg_url(v) if v else v

    @property
    def is_deployed(self) -> bool:
        return self.app_env in ("preview", "production")

    @property
    def migration_url(self) -> str:
        return self.database_url_unpooled or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
