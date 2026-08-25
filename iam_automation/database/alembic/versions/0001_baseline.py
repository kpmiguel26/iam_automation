"""
File: iam_automation/database/alembic/versions/0001_baseline.py
Purpose: Register the existing runtime schema as the Alembic baseline.
Responsibilities: Exposes or coordinates: upgrade, downgrade.
Dependencies: alembic
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

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
#endfile
