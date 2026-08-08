"""
File: iam_automation/database/migrations/v001_initial_schema.py
Purpose: Baseline for the schema created by runtime_schema.initialize_runtime_database.
Responsibilities: Exposes or coordinates: upgrade.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""


VERSION = "v001_initial_schema"
DESCRIPTION = "Register the existing runtime schema as the migration baseline."


def upgrade(connection) -> None:
    # The bootstrap schema already creates the initial tables. This migration
    # records that state so future changes can be applied incrementally.
    return None
