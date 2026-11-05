"""SQLAlchemy Core tables (§B5). Phase 0: core, ai (prompts, telemetry, traces), kb (RAG).

Money is integer minor units; costs are integer micro-USD. Time is timezone-aware UTC.
Every tenant-owned table has `org_id` and an RLS policy (see migration 0001).
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR, UUID

EMBED_DIM = 384
APP_SCHEMAS = ("core", "ai", "kb", "ap", "audit", "ops")

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _now() -> Column[object]:
    return Column(
        "created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


def _uuid_pk() -> Column[object]:
    return Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _org() -> Column[object]:
    return Column("org_id", Text, nullable=False)


# ---------------------------------------------------------------- core
org_settings = Table(
    "org_settings",
    metadata,
    Column("org_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("settings", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _now(),
    CheckConstraint("char_length(org_id) BETWEEN 1 AND 64", name="org_id_len"),
    schema="core",
)

api_keys = Table(
    "api_keys",
    metadata,
    _uuid_pk(),
    _org(),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("prefix", Text, nullable=False, unique=True),
    Column("key_hash", Text, nullable=False),
    Column("roles", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    _now(),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_len"),
    CheckConstraint("char_length(prefix) = 10", name="prefix_len"),
    Index(None, "org_id"),
    schema="core",
)

# ---------------------------------------------------------------- ai: prompt registry
prompts = Table(
    "prompts",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("name", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("system", Text, nullable=False, server_default=""),
    Column("template", Text, nullable=False),
    Column("variables_schema", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("config", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_by", Text, nullable=False),
    _now(),
    UniqueConstraint("name", "version"),
    CheckConstraint("version >= 1", name="version_pos"),
    CheckConstraint("name ~ '^[a-z][a-z0-9_.-]{1,63}$'", name="name_fmt"),
    schema="ai",
)

prompt_labels = Table(
    "prompt_labels",
    metadata,
    Column("name", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_by", Text, nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("name", "label"),
    ForeignKeyConstraint(["name", "version"], ["ai.prompts.name", "ai.prompts.version"]),
    CheckConstraint("label IN ('production', 'staging', 'canary')", name="label_known"),
    schema="ai",
)

prompt_label_events = Table(
    "prompt_label_events",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("name", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("old_version", Integer),
    Column("new_version", Integer, nullable=False),
    Column("changed_by", Text, nullable=False),
    Column("changed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="ai",
)

# ---------------------------------------------------------------- ai: telemetry
llm_calls = Table(
    "llm_calls",
    metadata,
    _uuid_pk(),
    _org(),
    Column("trace_id", Text),
    Column("request_id", Text),
    Column("run_id", Text),
    Column("task", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_name", Text),
    Column("prompt_version", Integer),
    Column("variant", Text),
    Column("attempt", Integer, nullable=False, server_default="1"),
    Column("tokens_in", Integer, nullable=False, server_default="0"),
    Column("tokens_out", Integer, nullable=False, server_default="0"),
    Column("est_cost_microusd", BigInteger, nullable=False, server_default="0"),
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("cache_hit", Boolean, nullable=False, server_default=text("false")),
    Column("fallback_reason", Text),
    Column("status", Text, nullable=False),
    Column("error_type", Text),
    _now(),
    CheckConstraint("status IN ('ok', 'error', 'skipped')", name="status_known"),
    CheckConstraint("tokens_in >= 0 AND tokens_out >= 0", name="tokens_nonneg"),
    Index(None, "org_id", "created_at"),
    Index(None, "trace_id"),
    schema="ai",
)

traces = Table(
    "traces",
    metadata,
    _uuid_pk(),
    _org(),
    Column("trace_id", Text, nullable=False),
    Column("parent_id", Text),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("input", JSONB),
    Column("output", JSONB),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False),
    Column("duration_ms", Integer, nullable=False, server_default="0"),
    Column("exported", Boolean, nullable=False, server_default=text("false")),
    Index(None, "org_id", "started_at"),
    Index(None, "trace_id"),
    schema="ai",
)

# ---------------------------------------------------------------- kb: knowledge / policy RAG
kb_documents = Table(
    "documents",
    metadata,
    _uuid_pk(),
    _org(),
    Column("filename", Text, nullable=False),
    Column("mime", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("blob_key", Text, nullable=False),
    Column("doc_type", Text, nullable=False, server_default="general"),
    Column("version", Text),
    Column("effective_from", Date),
    Column("effective_to", Date),
    Column("pages", Integer),
    Column("status", Text, nullable=False, server_default="ready"),
    Column("chunk_count", Integer, nullable=False, server_default="0"),
    Column("synthetic", Boolean, nullable=False, server_default=text("false")),
    Column("created_by", Text, nullable=False),
    _now(),
    UniqueConstraint("org_id", "sha256"),
    CheckConstraint("size_bytes > 0", name="size_pos"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha_fmt"),
    CheckConstraint(
        "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
        name="effective_range",
    ),
    schema="kb",
)

kb_chunks = Table(
    "chunks",
    metadata,
    _uuid_pk(),
    _org(),
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("kb.documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ord", Integer, nullable=False),
    Column("heading", Text, nullable=False, server_default=""),
    Column("text", Text, nullable=False),
    Column("page", Integer),
    Column("token_estimate", Integer, nullable=False),
    Column("embedding", Vector(EMBED_DIM), nullable=False),
    Column(
        "tsv", TSVECTOR, Computed("to_tsvector('english', heading || ' ' || text)", persisted=True)
    ),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _now(),
    UniqueConstraint("document_id", "ord"),
    Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    Index(
        "ix_chunks_embedding",
        "embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    ),
    Index(None, "org_id"),
    schema="kb",
)

TENANT_TABLES = [
    "core.org_settings",
    "core.api_keys",
    "ai.llm_calls",
    "ai.traces",
    "kb.documents",
    "kb.chunks",
]
