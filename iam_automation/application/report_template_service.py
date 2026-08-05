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
    folder_id: str = ""
    shared: bool = False


@dataclass(frozen=True)
class ReportTemplateFolder:
    folder_id: str
    name: str
    created_by: str
    created_at_utc: str
    shared: bool = False


class ReportTemplateService:
    """Persist reusable Report Studio definitions in the SharePoint workspace."""

    def __init__(self, sharepoint_root: Path):
        self.root = sharepoint_root / "report_templates"
        self.folders_root = self.root / "folders"

    def save(self, *, name: str, definition: dict[str, Any], created_by: str, folder_id: str = "", shared: bool = False) -> ReportQueryTemplate:
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("Template name is required.")
        template = ReportQueryTemplate(
            template_id=str(uuid.uuid4()),
            name=name[:120],
            created_by=str(created_by or ""),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            definition=definition,
            folder_id=str(folder_id or ""),
            shared=bool(shared),
        )
        self._write(template)
        return template

    def list(self) -> list[ReportQueryTemplate]:
        return self.list_for_user("", include_shared=True)

    def list_for_user(self, username: str, *, include_shared: bool = True) -> list[ReportQueryTemplate]:
        templates: list[ReportQueryTemplate] = []
        if not self.root.is_dir():
            return templates
        for path in sorted(self.root.glob("*.json")):
            try:
                template = ReportQueryTemplate(**json.loads(path.read_text(encoding="utf-8")))
                owned = str(template.created_by).casefold() == str(username).casefold()
                if username and not owned and not (include_shared and template.shared):
                    continue
                templates.append(template)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(templates, key=lambda item: (item.folder_id.casefold(), item.name.casefold(), item.created_at_utc))

    def get(self, template_id: str) -> ReportQueryTemplate | None:
        return self._read_template(template_id)

    def get_for_user(self, template_id: str, username: str, *, include_shared: bool = True) -> ReportQueryTemplate | None:
        template = self._read_template(template_id)
        if template is None:
            return None
        owned = str(template.created_by).casefold() == str(username).casefold()
        return template if owned or (include_shared and template.shared) else None

    def save_folder(self, *, name: str, created_by: str, shared: bool = False) -> ReportTemplateFolder:
        normalized = " ".join(str(name or "").split())
        if not normalized:
            raise ValueError("Folder name is required.")
        folder = ReportTemplateFolder(
            folder_id=str(uuid.uuid4()),
            name=normalized[:80],
            created_by=str(created_by or ""),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            shared=bool(shared),
        )
        self._write_folder(folder)
        return folder

    def list_folders(self, username: str, *, include_shared: bool = True) -> list[ReportTemplateFolder]:
        folders: list[ReportTemplateFolder] = []
        if not self.folders_root.is_dir():
            return folders
        for path in sorted(self.folders_root.glob("*.json")):
            try:
                folder = ReportTemplateFolder(**json.loads(path.read_text(encoding="utf-8")))
                owned = str(folder.created_by).casefold() == str(username).casefold()
                if username and not owned and not (include_shared and folder.shared):
                    continue
                folders.append(folder)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(folders, key=lambda item: (item.name.casefold(), item.created_at_utc))

    def get_folder_for_user(self, folder_id: str, username: str, *, include_shared: bool = True) -> ReportTemplateFolder | None:
        if not folder_id:
            return None
        for folder in self.list_folders(username, include_shared=include_shared):
            if folder.folder_id == folder_id:
                return folder
        return None

    def _read_template(self, template_id: str) -> ReportQueryTemplate | None:
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
            "folder_id": template.folder_id,
            "shared": template.shared,
        }, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(destination)

    def _write_folder(self, folder: ReportTemplateFolder) -> None:
        self.folders_root.mkdir(parents=True, exist_ok=True)
        destination = self.folders_root / f"{folder.folder_id}.json"
        payload = json.dumps({
            "folder_id": folder.folder_id,
            "name": folder.name,
            "created_by": folder.created_by,
            "created_at_utc": folder.created_at_utc,
            "shared": folder.shared,
        }, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.folders_root, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(destination)
