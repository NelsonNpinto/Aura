from __future__ import annotations

import os
import tempfile
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://aura:aura-local-only@localhost:5434/aura")
# Tests must never reach real providers or Upstash unless explicitly asked.
for var in (
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "BLOB_READ_WRITE_TOKEN",
):
    os.environ[var] = ""
if not os.environ.get("AURA_TEST_UPSTASH"):
    os.environ["UPSTASH_REDIS_REST_URL"] = ""
    os.environ["UPSTASH_REDIS_REST_TOKEN"] = ""
os.environ.setdefault("LOCAL_BLOB_DIR", os.path.join(tempfile.gettempdir(), "aura-test-blob"))

collect_ignore_glob = ["._*"]


def _db_up() -> bool:
    import psycopg

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    try:
        with psycopg.connect(url, connect_timeout=2) as c:
            c.execute("SELECT 1 FROM ai.prompts LIMIT 1")
        return True
    except Exception:
        return False


DB_UP = _db_up()


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="Postgres with migrations not available (run `make up migrate`)")
    for item in items:
        if "db" in item.keywords and not DB_UP:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def signing_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def mint(signing_key, monkeypatch):
    """Returns a function minting Better-Auth-shaped JWTs accepted by the API under test."""
    from app.core import auth

    class _Key:
        key = signing_key.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, _token):
            return _Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda: _Client())

    def _mint(org_id: str, roles: list[str], user_id: str | None = None, **extra) -> str:
        now = int(time.time())
        claims = {
            "sub": user_id or f"user-{uuid.uuid4().hex[:8]}",
            "org_id": org_id,
            "roles": roles,
            "iss": "http://localhost:3000",
            "aud": "aura-api",
            "iat": now,
            "exp": now + 600,
            **extra,
        }
        return jwt.encode(claims, signing_key, algorithm="EdDSA")

    return _mint


@pytest.fixture
def org_id() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def _fresh_store():
    from app.core.store import get_store

    get_store.cache_clear()
    yield
    get_store.cache_clear()
