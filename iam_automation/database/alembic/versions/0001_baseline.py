"""Register the existing runtime schema as the Alembic baseline."""

from alembic import op


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # runtime_schema creates the baseline tables before Alembic runs.
    pass


def downgrade() -> None:
    # The baseline is intentionally not destructive.
    pass
