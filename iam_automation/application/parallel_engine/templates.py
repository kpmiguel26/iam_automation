"""Read-only loader for approved configuration snapshots used by runtime v2."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import ObjectTemplate, RuntimeConfiguration, SourceTemplate, TemplateConfigurationError
from .database import connect


def _is_below_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class RuntimeTemplateCatalog:
    """Resolve approved source and object definitions without calling legacy services."""

    def __init__(self, database_path: Path, sharepoint_root: Path):
        self.database_path = Path(database_path)
        self.sharepoint_root = Path(sharepoint_root).expanduser().resolve()

    def load(self) -> RuntimeConfiguration | None:
        connection = connect(self.database_path)
        try:
            approved_objects = connection.execute(
                """SELECT v.employee_template_version_id, v.version_number,
                          v.definition_json, a.approved_by, a.approved_at_utc,
                          t.object_type_id
                   FROM employee_template_versions v
                   JOIN engine_v2_object_template_approvals a
                     ON a.object_template_version_id = v.employee_template_version_id
                   JOIN engine_v2_object_template_types t
                     ON t.object_template_version_id = v.employee_template_version_id
                   WHERE v.template_key = 'EMPLOYEE_PROFILE' AND v.status = 'DRAFT'
                   ORDER BY v.version_number DESC"""
            ).fetchall()
            if not approved_objects:
                return None
            latest_object = approved_objects[0]
            object_definition = json.loads(latest_object["definition_json"])
            source_refs = object_definition.get("source_templates") or ()
            if not source_refs:
                raise TemplateConfigurationError("Approved Object Template has no report sources.")

            active_deletions = {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT source_id FROM source_template_lifecycle_events WHERE restored_at_utc IS NULL"
                ).fetchall()
            }
            sources: list[SourceTemplate] = []
            for ref in source_refs:
                source_id = str(ref.get("source_id", "")).strip()
                version_id = str(ref.get("source_definition_version_id", "")).strip()
                if not source_id or not version_id:
                    raise TemplateConfigurationError("Object Template contains a report reference without a pinned version.")
                if source_id in active_deletions:
                    raise TemplateConfigurationError(f"Report template {source_id!r} is removed from the active library.")
                row = connection.execute(
                    """SELECT source_id, definition_version_id, version_number, status, definition_json
                       FROM source_definition_versions WHERE definition_version_id = ?""",
                    (version_id,),
                ).fetchone()
                if row is None or row["source_id"] != source_id or row["status"] != "APPROVED":
                    raise TemplateConfigurationError(f"Pinned report version for {source_id!r} is missing or not approved.")
                newest = connection.execute(
                    """SELECT definition_version_id FROM source_definition_versions
                       WHERE source_id = ? AND status = 'APPROVED'
                       ORDER BY version_number DESC LIMIT 1""",
                    (source_id,),
                ).fetchone()
                if newest is None or newest[0] != version_id:
                    raise TemplateConfigurationError(
                        f"Approved Object Template is stale for report {source_id!r}; save and approve it against the latest approved report version."
                    )
                definition = json.loads(row["definition_json"])
                folder = str(definition.get("watched_subfolder", "") or definition.get("reader_settings", {}).get("watched_path", "")).strip()
                if not folder:
                    raise TemplateConfigurationError(f"Approved report {source_id!r} has no configured watch folder.")
                configured_path = Path(folder).expanduser()
                if not configured_path.is_absolute():
                    configured_path = self.sharepoint_root / configured_path
                watched_path = configured_path.resolve()
                if not _is_below_root(watched_path, self.sharepoint_root):
                    raise TemplateConfigurationError(f"Watch folder for {source_id!r} is outside the SharePoint root.")
                if not watched_path.is_dir():
                    raise TemplateConfigurationError(f"Configured watch folder for {source_id!r} is unavailable.")
                order_row = connection.execute(
                    "SELECT ingestion_order FROM source_ingestion_orders WHERE source_id = ?", (source_id,)
                ).fetchone()
                sources.append(SourceTemplate(
                    source_id=source_id,
                    version_id=version_id,
                    version_number=int(row["version_number"]),
                    display_name=str(definition.get("display_name") or source_id),
                    definition=definition,
                    watched_path=watched_path,
                    ingestion_order=int(order_row[0]) if order_row else 2**31 - 1,
                ))

            sources.sort(key=lambda source: (source.ingestion_order, source.source_id.casefold()))
            self._validate_object(object_definition, sources)
            return RuntimeConfiguration(
                object_template=ObjectTemplate(
                    version_id=str(latest_object["employee_template_version_id"]),
                    version_number=int(latest_object["version_number"]),
                    definition=object_definition,
                    approved_by=str(latest_object["approved_by"]),
                    approved_at_utc=str(latest_object["approved_at_utc"]),
                    sources=tuple(sources),
                    object_type_id=str(latest_object["object_type_id"]),
                ),
                sources=tuple(sources),
            )
        finally:
            connection.close()

    def approve_object_template(self, version_id: str, actor: str) -> None:
        """Approve an object snapshot without mutating the legacy template row."""
        connection = connect(self.database_path)
        try:
            with connection:
                row = connection.execute(
                    """SELECT definition_json FROM employee_template_versions
                       WHERE employee_template_version_id = ?
                         AND template_key = 'EMPLOYEE_PROFILE' AND status = 'DRAFT'""",
                    (version_id,),
                ).fetchone()
                if row is None:
                    raise TemplateConfigurationError("Only a saved Object Template draft can be approved.")
                object_type = connection.execute(
                    "SELECT object_type_id FROM engine_v2_object_types WHERE object_type_key = 'EMPLOYEE_PROFILE'"
                ).fetchone()
                if object_type is None:
                    raise TemplateConfigurationError("The stable Employee object type has not been initialized.")
                connection.execute(
                    """INSERT OR IGNORE INTO engine_v2_object_template_types
                       (object_template_version_id, object_type_id) VALUES (?, ?)""",
                    (version_id, str(object_type[0])),
                )
                definition = json.loads(row["definition_json"])
                refs = definition.get("source_templates") or ()
                source_ids = {str(ref.get("source_id", "")) for ref in refs}
                if not refs or not all(source_ids):
                    raise TemplateConfigurationError("Object Template must select at least one report template.")
                sources: list[SourceTemplate] = []
                for ref in refs:
                    source_id = str(ref.get("source_id", ""))
                    source_version_id = str(ref.get("source_definition_version_id", ""))
                    if source_id in {
                        str(item[0]) for item in connection.execute(
                            "SELECT DISTINCT source_id FROM source_template_lifecycle_events WHERE restored_at_utc IS NULL"
                        ).fetchall()
                    }:
                        raise TemplateConfigurationError(f"Report template {source_id!r} is removed.")
                    source = connection.execute(
                        """SELECT source_id, version_number, status, definition_json
                           FROM source_definition_versions WHERE definition_version_id = ?""",
                        (source_version_id,),
                    ).fetchone()
                    if source is None or source["source_id"] != source_id or source["status"] != "APPROVED":
                        raise TemplateConfigurationError(f"Report template {source_id!r} must reference an approved version.")
                    newest = connection.execute(
                        """SELECT definition_version_id FROM source_definition_versions
                           WHERE source_id = ? AND status = 'APPROVED'
                           ORDER BY version_number DESC LIMIT 1""",
                        (source_id,),
                    ).fetchone()
                    if newest is None or newest[0] != source_version_id:
                        raise TemplateConfigurationError(f"Refresh Object Template source {source_id!r} to its latest approved version.")
                    config = json.loads(source["definition_json"])
                    folder = str(config.get("watched_subfolder", "") or config.get("reader_settings", {}).get("watched_path", ""))
                    if not folder:
                        raise TemplateConfigurationError(f"Configure a watch folder for report template {source_id!r} first.")
                    path = Path(folder).expanduser()
                    if not path.is_absolute():
                        path = self.sharepoint_root / path
                    path = path.resolve()
                    if not _is_below_root(path, self.sharepoint_root) or not path.is_dir():
                        raise TemplateConfigurationError(f"Watch folder for report template {source_id!r} must exist below the SharePoint root.")
                    order = connection.execute("SELECT ingestion_order FROM source_ingestion_orders WHERE source_id = ?", (source_id,)).fetchone()
                    sources.append(SourceTemplate(source_id, source_version_id, int(source["version_number"]), str(config.get("display_name") or source_id), config, path, int(order[0]) if order else 2**31 - 1))
                self._validate_object(definition, sources)
                if definition.get("allow_object_creation"):
                    authorized = False
                    for source in sources:
                        identity = source.definition.get("identity_governance") or {}
                        strong_creation = [item for item in identity.get("identifiers", ()) if item.get("strength") == "STRONG" and item.get("can_match") and item.get("can_create_identity")]
                        selected_creation = [item for item in definition.get("identifiers", ())
                                             if item.get("source_id") == source.source_id
                                             and item.get("strength") == "STRONG"
                                             and item.get("can_create_identity")
                                             and item.get("source_can_create_object")]
                        if identity.get("role") == "IDENTITY_SEED" and identity.get("can_create_employee") and len(strong_creation) >= 2 and len(selected_creation) >= 2:
                            authorized = True
                    if not authorized:
                        raise TemplateConfigurationError("Object creation requires an Identity Seed source with two authorized Strong identifiers.")
                connection.execute(
                    """INSERT INTO engine_v2_object_template_approvals
                       (object_template_version_id, approved_by, approved_at_utc)
                       VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
                    (version_id, actor),
                )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_object(definition: dict[str, Any], sources: list[SourceTemplate]) -> None:
        source_map = {source.source_id: source for source in sources}
        property_keys_by_source: set[tuple[str, str]] = set()
        for prop in definition.get("properties", ()):
            source_id = str(prop.get("source_id", ""))
            field_key = str(prop.get("field_key", ""))
            canonical_key = str(prop.get("canonical_property_key") or field_key).strip()
            source = source_map.get(source_id)
            if source is None:
                raise TemplateConfigurationError("Object Template property references an unselected report source.")
            included_fields = {
                str(field.get("field_key", ""))
                for field in source.definition.get("fields", ())
                if field.get("include")
            }
            if not field_key or field_key not in included_fields:
                raise TemplateConfigurationError(f"Object Template property {field_key!r} is not an included field in source {source_id!r}.")
            if not canonical_key or len(canonical_key) > 120:
                raise TemplateConfigurationError("Canonical property keys must contain between 1 and 120 characters.")
            if canonical_key != field_key and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,119}", canonical_key):
                raise TemplateConfigurationError(f"Canonical property key {canonical_key!r} is invalid.")
            property_ref = (source_id, canonical_key)
            if property_ref in property_keys_by_source:
                raise TemplateConfigurationError(f"Source {source_id!r} maps more than one field to property {canonical_key!r}.")
            property_keys_by_source.add(property_ref)
        refs = {(str(item.get("source_id", "")), str(item.get("field_key", ""))): item for item in definition.get("identifiers", ())}
        if len(sources) > 1:
            adjacency: dict[str, set[str]] = {source.source_id: set() for source in sources}
            for match in definition.get("matches", ()):
                left = match.get("left", {})
                right = match.get("right", {})
                left_ref = (str(left.get("source_id", "")), str(left.get("field_key", "")))
                right_ref = (str(right.get("source_id", "")), str(right.get("field_key", "")))
                if left_ref not in refs or right_ref not in refs:
                    raise TemplateConfigurationError("Object Template contains a match link to an unconfigured identifier.")
                if refs[left_ref].get("strength") != "STRONG" or refs[right_ref].get("strength") != "STRONG":
                    raise TemplateConfigurationError("Runtime object matching accepts configured Strong identifiers only.")
                if left_ref[0] not in source_map or right_ref[0] not in source_map:
                    raise TemplateConfigurationError("Object Template match link references an unselected source.")
                adjacency[left_ref[0]].add(right_ref[0])
                adjacency[right_ref[0]].add(left_ref[0])
            seen: set[str] = set()
            frontier = [sources[0].source_id]
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                frontier.extend(adjacency[current] - seen)
            if seen != set(source_map):
                raise TemplateConfigurationError("Approved Object Template does not connect every selected report source.")
