"""Genuine human labels for judge calibration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("judge_labels",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_judge_labels"),
        sa.ForeignKeyConstraint(["run_id"], ["ai.dataset_runs.id"], name="fk_judge_labels_run_id_dataset_runs"),
        sa.UniqueConstraint("run_id", "created_by", name="uq_judge_labels_run_id_created_by"),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_judge_labels_score_range"), schema="ai")
    op.execute("ALTER TABLE ai.judge_labels ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON ai.judge_labels USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true))")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ai.judge_labels TO aura_app")


def downgrade():
    op.drop_table("judge_labels", schema="ai")
