"""Independent, template-driven ingestion runtime running beside legacy IAM."""

from .engine import ParallelIngestionEngine
from .templates import RuntimeTemplateCatalog
from .watcher import ParallelFileWatcher

__all__ = ["ParallelFileWatcher", "ParallelIngestionEngine", "RuntimeTemplateCatalog"]
