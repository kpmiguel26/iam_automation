"""
File: iam_automation/domain/identities.py
Purpose: Defines domain models and rules for identities.
Responsibilities: Exposes or coordinates: ApprovedIdentity.
Dependencies: Python standard library and local project modules, as applicable.
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedIdentity:
    username: str
    display_name: str
    active: bool
    roles: tuple[str, ...]
