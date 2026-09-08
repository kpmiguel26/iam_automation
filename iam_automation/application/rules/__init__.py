"""Pipeline rule contracts and discovery.

Rules in this package are intentionally separate from the configurable
business-rule records stored in SQLite.  Pipeline rules are code-owned
checks that the ingestion orchestrator can run before or after an adapter.
"""

from .base import PipelineRule, RuleContext, RuleExecutionError, RulePhase, RuleResult
from .registry import RuleRegistry

__all__ = [
    "PipelineRule",
    "RuleContext",
    "RuleExecutionError",
    "RulePhase",
    "RuleResult",
    "RuleRegistry",
]
