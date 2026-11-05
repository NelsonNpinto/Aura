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

# ================================================================ Phase 1: invoice-to-pay
def _ts(name: str, nullable: bool = True) -> Column[object]:
    return Column(name, TIMESTAMP(timezone=True), nullable=nullable)


def _money(name: str, nullable: bool = True) -> Column[object]:
    return Column(name, BigInteger, nullable=nullable)


RUN_STATUSES = (
    "queued", "running", "awaiting_approval", "awaiting_receipt", "posted",
    "exception", "rejected", "blocked", "failed", "cancelled",
)

# ---------------------------------------------------------------- audit (§B12)
audit_chain_heads = Table(
    "chain_heads",
    metadata,
    Column("org_id", Text, primary_key=True),
    Column("seq", BigInteger, nullable=False, server_default="0"),
    Column("head_hash", Text, nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="audit",
)

audit_events = Table(
    "audit_events",
    metadata,
    _uuid_pk(),
    _org(),
    Column("seq", BigInteger, nullable=False),
    Column("run_id", Text),
    Column("ts", TIMESTAMP(timezone=True), nullable=False),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("target_type", Text),
    Column("target_id", Text),
    Column("tool", Text),
    Column("decision", Text),
    Column("input_hash", Text),
    Column("output_hash", Text),
    Column("evidence_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("model", Text),
    Column("prompt_version", Text),
    Column("git_sha", Text),
    Column("trace_id", Text),
    Column("guardrail_verdicts", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("prev_hash", Text, nullable=False),
    Column("hash", Text, nullable=False),
    UniqueConstraint("org_id", "seq"),
    CheckConstraint("actor_type IN ('agent','human','system')", name="actor_type"),
    CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name="hash_fmt"),
    Index(None, "org_id", "run_id"),
    schema="audit",
)

# ---------------------------------------------------------------- ap (§B5)
ap_documents = Table(
    "documents",
    metadata,
    _uuid_pk(),
    _org(),
    Column("filename", Text, nullable=False),
    Column("blob_key", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("mime", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("pages", Integer),
    Column("text", Text),
    Column("has_text_layer", Boolean),
    Column("hidden_text_findings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source", Text, nullable=False, server_default="upload"),
    Column("synthetic", Boolean, nullable=False, server_default=text("false")),
    Column("demo_key", Text),
    Column("uploaded_by", Text, nullable=False),
    Column("expires_at", TIMESTAMP(timezone=True)),
    _now(),
    UniqueConstraint("org_id", "sha256"),
    CheckConstraint("size_bytes > 0", name="size_pos"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha_fmt"),
    schema="ap",
)

ap_runs = Table(
    "runs",
    metadata,
    _uuid_pk(),
    _org(),
    Column("thread_id", Text, nullable=False),
    Column("document_id", UUID(as_uuid=True), ForeignKey("ap.documents.id"), nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("route", Text),
    Column("outcome", Text),
    Column("mode", Text, nullable=False, server_default="live"),
    Column("started_by", Text, nullable=False),
    Column("tokens", Integer, nullable=False, server_default="0"),
    Column("est_cost_microusd", BigInteger, nullable=False, server_default="0"),
    Column("latency_ms", Integer),
    Column("git_sha", Text),
    Column("config", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("state", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("error", Text),
    Column("seed", Boolean, nullable=False, server_default=text("false")),
    _now(),
    _ts("finished_at"),
    UniqueConstraint("thread_id"),
    CheckConstraint(
        "status IN (" + ",".join(f"'{s}'" for s in RUN_STATUSES) + ")", name="status"
    ),
    CheckConstraint("route IS NULL OR route IN ('auto','approval','exception')", name="route"),
    CheckConstraint("mode IN ('live','replay','fake')", name="mode"),
    Index(None, "org_id", "created_at"),
    Index(None, "org_id", "status"),
    schema="ap",
)

ap_run_events = Table(
    "run_events",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("type", Text, nullable=False),
    Column("node", Text),
    Column("ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    UniqueConstraint("run_id", "seq"),
    schema="ap",
)

ap_invoices = Table(
    "invoices",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id"), nullable=False),
    Column("document_id", UUID(as_uuid=True), ForeignKey("ap.documents.id"), nullable=False),
    Column("doc_type", Text, nullable=False, server_default="invoice"),
    Column("vendor_id", Text),
    Column("vendor_name", Text),
    Column("invoice_number", Text),
    Column("invoice_number_norm", Text),
    Column("invoice_date", Date),
    Column("due_date", Date),
    Column("currency", Text),
    _money("subtotal_minor"),
    _money("tax_minor"),
    _money("total_minor"),
    Column("po_number", Text),
    Column("bank_last4", Text),
    Column("status", Text, nullable=False, server_default="processing"),
    Column("risk_score", Integer),
    Column("risk_level", Text),
    Column("route", Text),
    _now(),
    UniqueConstraint("run_id"),
    CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency"),
    CheckConstraint("bank_last4 IS NULL OR bank_last4 ~ '^[0-9]{4}$'", name="last4"),
    Index(None, "org_id", "vendor_id", "invoice_number_norm"),
    schema="ap",
)

ap_invoice_lines = Table(
    "invoice_lines",
    metadata,
    _uuid_pk(),
    _org(),
    Column("invoice_id", UUID(as_uuid=True), ForeignKey("ap.invoices.id", ondelete="CASCADE"), nullable=False),
    Column("line_no", Integer, nullable=False),
    Column("description", Text, nullable=False),
    Column("quantity", Text, nullable=False),
    Column("uom", Text),
    _money("unit_price_minor"),
    _money("amount_minor"),
    Column("po_line_ref", Text),
    Column("gl_account", Text),
    Column("cost_center", Text),
    Column("gl_confidence", Text),
    Column("match_outcome", Text),
    UniqueConstraint("invoice_id", "line_no"),
    schema="ap",
)

ap_extractions = Table(
    "extractions",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    Column("confidence", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("evidence", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("model", Text),
    Column("prompt_version", Text),
    _now(),
    CheckConstraint("path IN ('text','vision','fixture')", name="path"),
    schema="ap",
)

ap_flags = Table(
    "flags",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("code", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("evidence", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _now(),
    CheckConstraint("severity IN ('LOW','MEDIUM','HIGH')", name="severity"),
    Index(None, "org_id", "code"),
    schema="ap",
)

ap_exceptions = Table(
    "exceptions",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("type", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="open"),
    Column("reason", Text, nullable=False),
    Column("explanation", Text),
    Column("drafted_email", Text),
    Column("resolution", Text),
    Column("resolved_by", Text),
    _ts("resolved_at"),
    _now(),
    CheckConstraint("status IN ('open','resolved','dismissed')", name="status"),
    UniqueConstraint("run_id"),
    schema="ap",
)

ap_approvals = Table(
    "approvals",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("step", Integer, nullable=False, server_default="1"),
    Column("required_role", Text, nullable=False),
    Column("packet_hash", Text, nullable=False),
    Column("packet", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("decision", Text),
    Column("comment", Text),
    Column("callback_verified", Boolean, nullable=False, server_default=text("false")),
    Column("decided_by", Text),
    _ts("decided_at"),
    Column("token_jti", Text),
    _ts("token_used_at"),
    _ts("due_at"),
    _now(),
    UniqueConstraint("run_id", "step"),
    UniqueConstraint("token_jti"),
    CheckConstraint("status IN ('pending','decided','escalated','superseded')", name="status"),
    CheckConstraint(
        "decision IS NULL OR decision IN ('approve','reject','request_info')", name="decision"
    ),
    CheckConstraint("required_role IN ('approver','controller')", name="role"),
    schema="ap",
)

ap_postings = Table(
    "postings",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE"), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("erp_ref", Text, nullable=False),
    Column("payment_ref", Text),
    _money("amount_minor", nullable=False),
    Column("currency", Text, nullable=False),
    _now(),
    UniqueConstraint("idempotency_key"),
    UniqueConstraint("run_id"),
    schema="ap",
)

ap_feedback = Table(
    "feedback",
    metadata,
    _uuid_pk(),
    _org(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("ap.runs.id", ondelete="CASCADE")),
    Column("kind", Text, nullable=False),
    Column("field", Text),
    Column("before", JSONB),
    Column("after", JSONB),
    Column("comment", Text),
    Column("created_by", Text, nullable=False),
    _now(),
    CheckConstraint("kind IN ('field_correction','gl_override','decision_override')", name="kind"),
    schema="ap",
)

# ---------------------------------------------------------------- ops
ops_outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _org(),
    Column("topic", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    _ts("processed_at"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    _now(),
    Index(None, "processed_at", "id"),
    schema="ops",
)

ops_job_runs = Table(
    "job_runs",
    metadata,
    _uuid_pk(),
    Column("job", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _now(),
    _ts("finished_at"),
    schema="ops",
)

ai_dataset_runs = Table(
    "dataset_runs",
    metadata,
    _uuid_pk(),
    Column("dataset", Text, nullable=False),
    Column("dataset_version", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("provider_mode", Text, nullable=False),
    Column("git_sha", Text),
    Column("case_count", Integer, nullable=False),
    Column("metrics", JSONB, nullable=False),
    Column("results", JSONB, nullable=False),
    Column("config", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _now(),
    schema="ai",
)

TENANT_TABLES = [
    "core.org_settings",
    "core.api_keys",
    "ai.llm_calls",
    "ai.traces",
    "kb.documents",
    "kb.chunks",
    "audit.audit_events",
    "audit.chain_heads",
    "ap.documents",
    "ap.runs",
    "ap.run_events",
    "ap.invoices",
    "ap.invoice_lines",
    "ap.extractions",
    "ap.flags",
    "ap.exceptions",
    "ap.approvals",
    "ap.postings",
    "ap.feedback",
    "ops.outbox",
]
