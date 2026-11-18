"""Track purchasing source uploads per case, document type and uploader."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "procurement_uploads",
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id", "kind", "user_id", "document_id"),
        sa.ForeignKeyConstraint(["case_id"], ["ap.procurement_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["ap.documents.id"], ondelete="CASCADE"),
        schema="ap",
    )
    op.execute("ALTER TABLE ap.procurement_uploads ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ap.procurement_uploads"
        " USING (org_id = current_setting('app.org_id', true))"
        " WITH CHECK (org_id = current_setting('app.org_id', true))"
    )
    op.execute("GRANT SELECT, INSERT ON ap.procurement_uploads TO aura_app")


def downgrade():
    op.drop_table("procurement_uploads", schema="ap")
