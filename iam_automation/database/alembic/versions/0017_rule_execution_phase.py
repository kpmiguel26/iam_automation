"""Store the pipeline phase for each business-rule version."""

from alembic import op
from sqlalchemy import Column, String


revision = "0017_rule_execution_phase"
down_revision = "0016_allow_fact_linking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("business_rule_versions", Column("phase", String, nullable=False, server_default="AFTER"))


def downgrade() -> None:
    op.drop_column("business_rule_versions", "phase")
