"""Index recent purchasing cases for the workspace and vendor views."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    order = [sa.text("created_at DESC"), sa.text("id DESC")]
    op.create_index(
        "ix_procurement_cases_org_recent",
        "procurement_cases",
        ["org_id", *order],
        schema="ap",
    )
    op.create_index(
        "ix_procurement_cases_org_vendor_recent",
        "procurement_cases",
        ["org_id", sa.text("lower(btrim(vendor_id))"), *order],
        schema="ap",
    )


def downgrade() -> None:
    op.drop_index("ix_procurement_cases_org_vendor_recent", schema="ap")
    op.drop_index("ix_procurement_cases_org_recent", schema="ap")
