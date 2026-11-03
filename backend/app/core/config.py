from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://aura@localhost:5433/aura"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout_seconds: float = 180
    ollama_api_key: str = ""
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    api_key: str = ""
    webhook_secret: str = ""
    otel_endpoint: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "http://localhost:3000"
    request_limit_per_minute: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
