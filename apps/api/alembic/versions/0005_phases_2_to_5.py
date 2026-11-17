"""Phases 2-5: memory, copilot threads, trust layer, model registry, onboarding.

Expand-only: every table is new, so the migration is reversible by dropping them.
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

EMBED_DIM = 384

TENANT_TABLES = [
    "ai.memories",
    "ai.copilot_threads",
    "ai.copilot_messages",
    "ai.guardrail_events",
    "ai.feedback_events",
    "ai.baselines",
    "ai.experiments",
    "ai.eval_reports",
    "ai.challenge_attempts",
    "ai.semantic_cache",
    "ai.model_versions",
    "ops.drift_reports",
    "ap.onboarding_cases",
]


def _uuid_pk(name):
    return sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade():
    # ---------------------------------------------------------------- memory (B8.3)
    op.create_table(
        "memories",
        _uuid_pk("memories"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("fact_norm", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("observations", sa.Integer(), server_default="1", nullable=False),
        sa.Column("confidence", sa.Integer(), server_default="50", nullable=False),
        sa.Column("source_event_id", UUID(as_uuid=True)),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        _created(),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
        sa.UniqueConstraint("org_id", "kind", "subject_id", "fact_norm",
                            name="uq_memories_org_id_kind_subject_id_fact_norm"),
        sa.CheckConstraint("kind IN ('vendor','user')", name="ck_memories_kind_valid"),
        sa.CheckConstraint("status IN ('pending','active','retired')", name="ck_memories_status_valid"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_memories_confidence_range"),
        schema="ai",
    )
    op.create_index("ix_memories_org_id_kind_subject_id", "memories", ["org_id", "kind", "subject_id"], schema="ai")

    # ---------------------------------------------------------------- copilot threads (B7)
    op.create_table(
        "copilot_threads",
        _uuid_pk("copilot_threads"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        _created(),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_copilot_threads"),
        schema="ai",
    )
    op.create_index("ix_copilot_threads_org_id_user_id", "copilot_threads", ["org_id", "user_id"], schema="ai")
    op.create_table(
        "copilot_messages",
        _uuid_pk("copilot_messages"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tool_events", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("llm", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_copilot_messages"),
        sa.ForeignKeyConstraint(["thread_id"], ["ai.copilot_threads.id"],
                                name="fk_copilot_messages_thread_id_copilot_threads", ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_copilot_messages_role_valid"),
        schema="ai",
    )
    op.create_index("ix_copilot_messages_thread_id_created_at", "copilot_messages",
                    ["thread_id", "created_at"], schema="ai")

    # ---------------------------------------------------------------- trust layer (B11, B13)
    op.create_table(
        "guardrail_events",
        _uuid_pk("guardrail_events"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True)),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("check", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), server_default="LOW", nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("details", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_guardrail_events"),
        sa.CheckConstraint("verdict IN ('pass','flag','block')", name="ck_guardrail_events_verdict_valid"),
        schema="ai",
    )
    op.create_index("ix_guardrail_events_org_id_created_at", "guardrail_events",
                    ["org_id", "created_at"], schema="ai")

    op.create_table(
        "feedback_events",
        _uuid_pk("feedback_events"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="new", nullable=False),
        sa.Column("dataset", sa.Text()),
        sa.Column("case_id", sa.Text()),
        sa.Column("triaged_by", sa.Text()),
        sa.Column("triaged_at", sa.DateTime(timezone=True)),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_events"),
        sa.UniqueConstraint("org_id", "event_id", name="uq_feedback_events_org_id_event_id"),
        sa.CheckConstraint("status IN ('new','accepted','rejected')", name="ck_feedback_events_status_valid"),
        schema="ai",
    )

    op.create_table(
        "baselines",
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("case_snapshot", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("justification", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("org_id", "dataset", name="pk_baselines"),
        sa.ForeignKeyConstraint(["run_id"], ["ai.dataset_runs.id"],
                                name="fk_baselines_run_id_dataset_runs"),
        schema="ai",
    )

    op.create_table(
        "experiments",
        _uuid_pk("experiments"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("results", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_experiments"),
        sa.CheckConstraint("kind IN ('offline','online')", name="ck_experiments_kind_valid"),
        schema="ai",
    )
    op.create_index("ix_experiments_org_id_created_at", "experiments", ["org_id", "created_at"], schema="ai")

    op.create_table(
        "eval_reports",
        _uuid_pk("eval_reports"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("report", JSONB(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("git_sha", sa.Text()),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_eval_reports"),
        sa.UniqueConstraint("org_id", "slug", name="uq_eval_reports_org_id_slug"),
        schema="ai",
    )

    op.create_table(
        "challenge_attempts",
        _uuid_pk("challenge_attempts"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Text(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("verdicts", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("visitor_hash", sa.Text(), server_default="", nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_attempts"),
        schema="ai",
    )
    op.create_index("ix_challenge_attempts_org_id_created_at", "challenge_attempts",
                    ["org_id", "created_at"], schema="ai")

    op.create_table(
        "semantic_cache",
        _uuid_pk("semantic_cache"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", JSONB(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_semantic_cache"),
        schema="ai",
    )
    op.create_index("ix_semantic_cache_org_id_task", "semantic_cache", ["org_id", "task"], schema="ai")

    op.create_table(
        "tool_registry",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("allowed_roles", ARRAY(sa.Text()), nullable=False),
        sa.Column("allowed_agents", ARRAY(sa.Text()), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("idempotent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rate_limit", sa.Integer(), server_default="60", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_schema", JSONB(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_tool_registry"),
        schema="ai",
    )

    op.create_table(
        "drift_reports",
        _uuid_pk("drift_reports"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("breaches", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_drift_reports"),
        schema="ops",
    )
    op.create_index("ix_drift_reports_org_id_created_at", "drift_reports",
                    ["org_id", "created_at"], schema="ops")

    # ---------------------------------------------------------------- model registry (B15)
    op.create_table(
        "model_versions",
        _uuid_pk("model_versions"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("base_model", sa.Text(), nullable=False),
        sa.Column("adapter_repo", sa.Text(), server_default="", nullable=False),
        sa.Column("adapter_revision", sa.Text(), server_default="", nullable=False),
        sa.Column("dataset_version", sa.Text(), server_default="", nullable=False),
        sa.Column("metrics", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.Text(), server_default="candidate", nullable=False),
        sa.Column("canary_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("promoted_by", sa.Text()),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_model_versions"),
        sa.UniqueConstraint("org_id", "name", "adapter_revision",
                            name="uq_model_versions_org_id_name_adapter_revision"),
        sa.CheckConstraint("status IN ('candidate','canary','production','retired')",
                           name="ck_model_versions_status_valid"),
        sa.CheckConstraint("canary_percent BETWEEN 0 AND 100", name="ck_model_versions_canary_range"),
        schema="ai",
    )

    # ---------------------------------------------------------------- onboarding pack (Phase 5)
    op.create_table(
        "onboarding_cases",
        _uuid_pk("onboarding_cases"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("vendor_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("state", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_onboarding_cases"),
        schema="ap",
    )
    op.create_index("ix_onboarding_cases_org_id_created_at", "onboarding_cases",
                    ["org_id", "created_at"], schema="ap")

    # ---------------------------------------------------------------- RLS + grants
    for name in TENANT_TABLES:
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {name}"
            " USING (org_id = current_setting('app.org_id', true))"
            " WITH CHECK (org_id = current_setting('app.org_id', true))"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO aura_app")
    # The tool registry is configuration, not tenant data: readable by the app, written by sync.
    op.execute("GRANT SELECT ON ai.tool_registry TO aura_app")


def downgrade():
    op.drop_table("onboarding_cases", schema="ap")
    op.drop_table("model_versions", schema="ai")
    op.drop_table("drift_reports", schema="ops")
    op.drop_table("tool_registry", schema="ai")
    op.drop_table("semantic_cache", schema="ai")
    op.drop_table("challenge_attempts", schema="ai")
    op.drop_table("eval_reports", schema="ai")
    op.drop_table("experiments", schema="ai")
    op.drop_table("baselines", schema="ai")
    op.drop_table("feedback_events", schema="ai")
    op.drop_table("guardrail_events", schema="ai")
    op.drop_table("copilot_messages", schema="ai")
    op.drop_table("copilot_threads", schema="ai")
    op.drop_table("memories", schema="ai")
