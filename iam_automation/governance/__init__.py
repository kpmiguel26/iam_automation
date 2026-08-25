"""
File: iam_automation/governance/__init__.py
Purpose: Audit, checksum, locking, publication, and recovery controls.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: audit, checksum, lock
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from ..audit import AuditEvent, append_audit_event, build_event
from ..checksum import sha256_file
from ..lock import LockConflict, OperationLock, acquire_lock, release_lock

__all__ = [
    "AuditEvent",
    "LockConflict",
    "OperationLock",
    "acquire_lock",
    "append_audit_event",
    "build_event",
    "release_lock",
    "sha256_file",
]
#endfile
