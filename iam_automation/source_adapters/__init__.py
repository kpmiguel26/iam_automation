"""
File: iam_automation/source_adapters/__init__.py
Purpose: Source-specific ingestion adapters.
Responsibilities: Provides the file-level implementation used by the application.
Dependencies: rsr_supplier_worker_details
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from .rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter

__all__ = ["RsrSupplierWorkerDetailsAdapter"]
#endfile
