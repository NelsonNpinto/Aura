"""Assignment procurement workflow and vendor membership."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("procurement_cases",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("po_number", sa.Text(), nullable=False),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_procurement_cases"),
        sa.UniqueConstraint("org_id", "po_number", name="uq_procurement_cases_org_id_po_number"), schema="ap")
    op.create_table("procurement_members",
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text()),
        sa.PrimaryKeyConstraint("org_id", "user_id", name="pk_procurement_members"), schema="ap")
    for table in ("procurement_cases", "procurement_members"):
        name = f"ap.{table}"
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {name} USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true))")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO aura_app")


def downgrade():
    op.drop_table("procurement_members", schema="ap")
    op.drop_table("procurement_cases", schema="ap")
