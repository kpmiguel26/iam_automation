from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReportQueryTemplate:
    template_id: str
    name: str
    created_by: str
    created_at_utc: str
    definition: dict[str, Any]


class ReportTemplateService:
    """Persist reusable Report Studio definitions in the SharePoint workspace."""

    def __init__(self, sharepoint_root: Path):
        self.root = sharepoint_root / "report_templates"

    def save(self, *, name: str, definition: dict[str, Any], created_by: str) -> ReportQueryTemplate:
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("Template name is required.")
        template = ReportQueryTemplate(
            template_id=str(uuid.uuid4()),
            name=name[:120],
            created_by=str(created_by or ""),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            definition=definition,
        )
        self._write(template)
        return template

    def list(self) -> list[ReportQueryTemplate]:
        templates: list[ReportQueryTemplate] = []
        if not self.root.is_dir():
            return templates
        for path in sorted(self.root.glob("*.json")):
            try:
                templates.append(ReportQueryTemplate(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(templates, key=lambda item: (item.name.casefold(), item.created_at_utc))

    def get(self, template_id: str) -> ReportQueryTemplate | None:
        if not template_id:
            return None
        path = self.root / f"{template_id}.json"
        if not path.is_file():
            return None
        try:
            return ReportQueryTemplate(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write(self, template: ReportQueryTemplate) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{template.template_id}.json"
        payload = json.dumps({
            "template_id": template.template_id,
            "name": template.name,
            "created_by": template.created_by,
            "created_at_utc": template.created_at_utc,
            "definition": template.definition,
        }, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(destination)
