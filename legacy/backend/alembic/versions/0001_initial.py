"""Initial traces and deterministic evaluation runs."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system", sa.Text(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
    )
    for name in ("created_at", "model", "status"):
        op.create_index(f"ix_traces_{name}", "traces", [name])
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("trace_id", sa.String(36), sa.ForeignKey("traces.id")),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
    )
    for name in ("created_at", "trace_id"):
        op.create_index(f"ix_evaluation_runs_{name}", "evaluation_runs", [name])


def downgrade():
    op.drop_table("evaluation_runs")
    op.drop_table("traces")
