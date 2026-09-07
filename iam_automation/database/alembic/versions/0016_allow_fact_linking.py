"""Allow employee linkage updates while keeping source facts immutable."""

from alembic import op


revision = "0016_allow_fact_linking"
down_revision = "0015_source_separated_write_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = (
        "fact_accessnow_employee",
        "fact_master_roster_employee",
        "fact_roster_lock_assignment",
        "fact_rsr_assignment",
        "fact_source_field_value",
    )
    for table in tables:
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_update")
        bind.exec_driver_sql(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_update
            BEFORE UPDATE ON {table}
            WHEN NEW.employee_key IS OLD.employee_key
            BEGIN SELECT RAISE(ABORT, 'source facts are append-only except employee linkage'); END"""
        )


def downgrade() -> None:
    pass
