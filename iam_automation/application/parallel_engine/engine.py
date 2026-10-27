"""End-to-end ingestion and source-scoped object assembly for runtime v2."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import EngineRunResult, FileRecognitionAnalysis, ObjectTemplate, ParsedSourceRow, RuntimeConfiguration, SourceTemplate, TemplateConfigurationError
from .database import connect
from .reader import inspect_headers, parse_source_rows
from .rules import evaluate_configured_rules, persist_v2_findings
from .templates import RuntimeTemplateCatalog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches_pattern(filename: str, configured: str) -> bool:
    from fnmatch import fnmatch
    if not configured:
        return True
    return fnmatch(filename.casefold(), configured.casefold())


class ParallelIngestionEngine:
    """Process configured files into isolated evidence and object tables."""

    def __init__(self, database_path: Path, sharepoint_root: Path):
        self.database_path = Path(database_path)
        self.sharepoint_root = Path(sharepoint_root).expanduser().resolve()
        self.catalog = RuntimeTemplateCatalog(self.database_path, self.sharepoint_root)

    def configuration(self) -> RuntimeConfiguration | None:
        return self.catalog.load()

    @staticmethod
    def analyze_source(path: Path, content: bytes, source: SourceTemplate) -> FileRecognitionAnalysis:
        definition = source.definition
        recognition = definition.get("recognition_settings") or {}
        reader = definition.get("reader_settings") or {}
        expected_extension = str(recognition.get("extension") or Path(str(reader.get("format", "XLSX"))).suffix or ("." + str(reader.get("format", "XLSX")).lower()))
        if not expected_extension.startswith("."):
            expected_extension = "." + expected_extension
        extension_match = path.suffix.casefold() == expected_extension.casefold()
        diagnostics: list[str] = []
        if not extension_match:
            diagnostics.append(f"Expected {expected_extension} file extension.")
        pattern = str(recognition.get("filename_pattern") or reader.get("filename_pattern") or "")
        filename_match = _matches_pattern(path.name, pattern)
        if not filename_match:
            diagnostics.append("Filename does not match the configured template pattern.")
        headers: tuple[str, ...] = ()
        sheet = ""
        headers_readable = False
        try:
            headers, sheet = inspect_headers(path, content, source)
            headers_readable = True
        except (ValueError, OSError, TemplateConfigurationError) as exc:
            diagnostics.append(str(exc))
        expected_sheet = str(recognition.get("sheet_name") or reader.get("sheet_name") or "")
        worksheet_match = not expected_sheet or expected_sheet == sheet
        if not worksheet_match:
            diagnostics.append(f"Expected worksheet {expected_sheet!r}, found {sheet!r}.")
        header_set = {header.casefold() for header in headers}
        included_headers = {
            str(field.get("source_name", "")).strip().casefold()
            for field in definition.get("fields", ())
            if field.get("include", True) and str(field.get("source_name", "")).strip()
        }
        required_headers = tuple(
            str(header)
            for header in recognition.get("required_headers", ())
            if str(header).strip().casefold() in included_headers
        )
        missing = tuple(header for header in required_headers if header.casefold() not in header_set)
        if missing:
            diagnostics.append("Required recognition headers are absent: " + ", ".join(missing))
        unknown = tuple(header for header in headers if header and header.casefold() not in included_headers)
        checks = {
            "extension_match": extension_match,
            "filename_match": filename_match,
            "worksheet_match": worksheet_match,
            "headers_readable": headers_readable,
            "required_headers_present": not missing,
        }
        return FileRecognitionAnalysis(
            source=source,
            recognition_status="RECOGNIZED" if all(checks.values()) else "UNRECOGNIZED",
            worksheet_name=sheet,
            detected_headers=headers,
            required_headers=required_headers,
            missing_headers=missing,
            unknown_headers=unknown,
            checks=checks,
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _recognition_match(path: Path, content: bytes, source: SourceTemplate) -> tuple[bool, str]:
        analysis = ParallelIngestionEngine.analyze_source(path, content, source)
        return analysis.recognition_status == "RECOGNIZED", " ".join(analysis.diagnostics)

    def analyze_file(
        self, path: Path, content: bytes, configuration: RuntimeConfiguration | None = None,
    ) -> tuple[FileRecognitionAnalysis, ...]:
        config = configuration or self.catalog.load()
        if config is None:
            raise TemplateConfigurationError("No approved Object Template is active in the runtime catalog.")
        resolved = path.expanduser().resolve()
        candidates = []
        for source in config.sources:
            try:
                resolved.relative_to(source.watched_path.resolve())
            except ValueError:
                continue
            candidates.append(self.analyze_source(resolved, content, source))
        return tuple(candidates)

    def recognize(self, path: Path, content: bytes, configuration: RuntimeConfiguration | None = None) -> SourceTemplate:
        config = configuration or self.catalog.load()
        if config is None:
            raise TemplateConfigurationError("No approved Object Template is active in the runtime catalog.")
        analyses = self.analyze_file(path, content, config)
        candidates = [item.source for item in analyses if item.recognition_status == "RECOGNIZED"]
        diagnostics = [f"{item.source.source_id}: {' '.join(item.diagnostics)}" for item in analyses if item.diagnostics]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise TemplateConfigurationError("No configured report template recognizes this file. " + " ".join(diagnostics))
        raise TemplateConfigurationError("File recognition is ambiguous between: " + ", ".join(source.source_id for source in candidates))

    def stage_file(
        self, path: Path, *, authorized_by: str, content: bytes | None = None,
        configuration: RuntimeConfiguration | None = None,
    ) -> EngineRunResult:
        """Persist parsed row evidence after authorization, without creating object instances.

        This is the first import phase. Object materialization, identifier linking,
        physical star-schema writes and Rules Engine coordination remain separate.
        """
        actor = str(authorized_by or "").strip()
        if not actor:
            raise ValueError("A recorded approver is required to stage an import file.")
        resolved = path.expanduser().resolve()
        if content is None:
            before = resolved.stat()
            content = resolved.read_bytes()
            after = resolved.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise OSError("File changed while runtime v2 was reading it; it will be retried on the next watcher cycle.")
        checksum = hashlib.sha256(content).hexdigest()
        config = configuration or self.catalog.load()
        if config is None:
            raise TemplateConfigurationError("No approved Object Template is active in the runtime catalog.")
        source = self.recognize(resolved, content, config)
        try:
            rows, file_errors, unknown_headers = parse_source_rows(resolved, content, source)
        except (ValueError, OSError, TemplateConfigurationError) as exc:
            rows, file_errors, unknown_headers = (), (str(exc),), ()

        messages = list(file_errors)
        if unknown_headers and str(source.definition.get("schema_drift_policy", "WARNING")).upper() == "WARNING":
            messages.append("Unconfigured source columns: " + ", ".join(unknown_headers))
        quarantined_count = sum(bool(row.issues) for row in rows)
        staged_count = len(rows) - quarantined_count
        status = "FAILED" if file_errors else ("STAGED_WITH_WARNINGS" if quarantined_count or messages else "STAGED")
        batch_id = str(uuid.uuid4())
        now = _utc_now()
        connection = connect(self.database_path)
        try:
            existing = connection.execute(
                """SELECT batch_id, status, total_rows, evidence_rows, quarantined_rows,
                          message FROM engine_v2_batches WHERE source_id = ? AND source_version_id = ?
                     AND object_template_version_id = ? AND source_file = ? AND source_checksum = ?""",
                (source.source_id, source.version_id, config.object_template.version_id, str(resolved), checksum),
            ).fetchone()
            if existing:
                if str(existing["status"]) not in {"STAGED", "STAGED_WITH_WARNINGS", "FAILED"}:
                    raise TemplateConfigurationError(
                        "This file checksum already has a non-staging engine batch; review that batch before retrying."
                    )
                return EngineRunResult(
                    batch_id=str(existing["batch_id"]), source_id=source.source_id,
                    source_version_id=source.version_id,
                    object_template_version_id=config.object_template.version_id,
                    file_path=str(resolved), file_checksum=checksum, status=str(existing["status"]),
                    total_rows=int(existing["total_rows"]), evidence_rows=int(existing["evidence_rows"]),
                    quarantined_rows=int(existing["quarantined_rows"]), objects_created=0,
                    objects_linked=0, message=str(existing["message"]),
                )
            with connection:
                connection.execute(
                    """INSERT INTO engine_v2_batches
                       (batch_id, source_id, source_version_id, object_template_version_id,
                        source_file, source_checksum, status, total_rows, started_at_utc, message,
                        authorized_by, authorized_at_utc)
                       VALUES (?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?, ?, ?, ?)""",
                    (batch_id, source.source_id, source.version_id, config.object_template.version_id,
                     str(resolved), checksum, len(rows), now, "", actor, now),
                )
                for row in rows:
                    row_status = "QUARANTINED" if row.issues else "STAGED"
                    connection.execute(
                        """INSERT INTO engine_v2_evidence
                           (evidence_id, batch_id, row_number, sheet_name, source_key,
                            raw_json, normalized_json, status, diagnostics_json, created_at_utc)
                           VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?)""",
                        (str(uuid.uuid4()), batch_id, row.row_number, row.sheet_name,
                         json.dumps(row.raw_values, ensure_ascii=False, sort_keys=True, default=str),
                         json.dumps(row.normalized_values, ensure_ascii=False, sort_keys=True, default=str),
                         row_status, json.dumps(row.issues, ensure_ascii=False), now),
                    )
                connection.execute(
                    """UPDATE engine_v2_batches SET status = ?, total_rows = ?, evidence_rows = ?,
                       quarantined_rows = ?, completed_at_utc = ?, message = ? WHERE batch_id = ?""",
                    (status, len(rows), staged_count, quarantined_count, _utc_now(), "; ".join(messages), batch_id),
                )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return EngineRunResult(
            batch_id, source.source_id, source.version_id, config.object_template.version_id,
            str(resolved), checksum, status, len(rows), staged_count, quarantined_count, 0, 0,
            "; ".join(messages),
        )

    def ingest_file(
        self, path: Path, content: bytes | None = None,
        configuration: RuntimeConfiguration | None = None, *, authorized_by: str = "",
    ) -> EngineRunResult:
        resolved = path.expanduser().resolve()
        if content is None:
            before = resolved.stat()
            content = resolved.read_bytes()
            after = resolved.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise OSError("File changed while runtime v2 was reading it; it will be retried on the next watcher cycle.")
        checksum = hashlib.sha256(content).hexdigest()
        config = configuration or self.catalog.load()
        if config is None:
            raise TemplateConfigurationError("No approved Object Template is active in the runtime catalog.")
        source = self.recognize(resolved, content, config)
        rows, file_errors, unknown_headers = parse_source_rows(resolved, content, source)
        batch_id = str(uuid.uuid4())
        now = _utc_now()
        status = "FAILED" if file_errors else "COMPLETED"
        evidence_count = quarantine_count = created_count = linked_count = 0
        messages = list(file_errors)
        before_findings: list[dict[str, Any]] = []
        if not file_errors:
            try:
                before_findings, rule_diagnostics = evaluate_configured_rules(
                    self.database_path, phase="BEFORE", source_id=source.source_id,
                    source_system_key=str(source.definition.get("business_rule_source_system", "")), rows=rows,
                )
            except Exception as exc:
                rule_diagnostics = [f"BEFORE rule evaluation unavailable ({type(exc).__name__})."]
            messages.extend(f"Advisory rule: {message}" for message in rule_diagnostics)
        if unknown_headers and str(source.definition.get("schema_drift_policy", "WARNING")).upper() == "WARNING":
            messages.append("Unconfigured source columns: " + ", ".join(unknown_headers))
            status = "COMPLETED_WITH_WARNINGS"

        connection = connect(self.database_path)
        try:
            existing = connection.execute(
                """SELECT batch_id, status, total_rows, evidence_rows, quarantined_rows,
                          objects_created, objects_linked, message
                   FROM engine_v2_batches WHERE source_id = ? AND source_version_id = ?
                     AND object_template_version_id = ? AND source_file = ? AND source_checksum = ?""",
                (source.source_id, source.version_id, config.object_template.version_id, str(resolved), checksum),
            ).fetchone()
            if existing:
                return EngineRunResult(
                    batch_id=str(existing["batch_id"]), source_id=source.source_id,
                    source_version_id=source.version_id,
                    object_template_version_id=config.object_template.version_id,
                    file_path=str(resolved), file_checksum=checksum, status=str(existing["status"]),
                    total_rows=int(existing["total_rows"]), evidence_rows=int(existing["evidence_rows"]),
                    quarantined_rows=int(existing["quarantined_rows"]), objects_created=int(existing["objects_created"]),
                    objects_linked=int(existing["objects_linked"]), message=str(existing["message"]),
                )
            with connection:
                connection.execute(
                    """INSERT INTO engine_v2_batches
                       (batch_id, source_id, source_version_id, object_template_version_id,
                        source_file, source_checksum, status, total_rows, started_at_utc, message,
                        authorized_by, authorized_at_utc)
                       VALUES (?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?, ?, ?, ?)""",
                    (batch_id, source.source_id, source.version_id, config.object_template.version_id,
                     str(resolved), checksum, len(rows), now, "", str(authorized_by or ""), now if authorized_by else None),
                )
                for row in rows:
                    evidence_id = str(uuid.uuid4())
                    row_status = "QUARANTINED" if row.issues else "STAGED"
                    if row.issues:
                        quarantine_count += 1
                    else:
                        evidence_count += 1
                    connection.execute(
                        """INSERT INTO engine_v2_evidence
                           (evidence_id, batch_id, row_number, sheet_name, source_key,
                            raw_json, normalized_json, status, diagnostics_json, created_at_utc)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (evidence_id, batch_id, row.row_number, row.sheet_name,
                         _source_key(row.normalized_values, source, config.object_template),
                         json.dumps(row.raw_values, ensure_ascii=False, sort_keys=True, default=str),
                         json.dumps(row.normalized_values, ensure_ascii=False, sort_keys=True, default=str),
                         row_status, json.dumps(row.issues, ensure_ascii=False), now),
                    )
                    if row.issues:
                        continue
                    object_id, reason, ambiguous = self._find_object(connection, row, source, config.object_template)
                    if ambiguous:
                        connection.execute(
                            "UPDATE engine_v2_evidence SET status = 'QUARANTINED', diagnostics_json = ? WHERE evidence_id = ?",
                            (json.dumps(["Strong identity values point to multiple existing objects; manual review required."]), evidence_id),
                        )
                        quarantine_count += 1
                        evidence_count -= 1
                        continue
                    if object_id is None and _source_can_create_object(source, config.object_template):
                        object_id = str(uuid.uuid4())
                        connection.execute(
                            """INSERT INTO engine_v2_objects
                               (object_id, object_type_id, object_template_version_id, created_at_utc)
                               VALUES (?, ?, ?, ?)""",
                            (object_id, config.object_template.object_type_id,
                             config.object_template.version_id, now),
                        )
                        created_count += 1
                        reason = {"kind": "created", "source_id": source.source_id}
                    elif object_id is None:
                        connection.execute(
                            "UPDATE engine_v2_evidence SET status = 'UNRESOLVED', diagnostics_json = ? WHERE evidence_id = ?",
                            (json.dumps(["No configured Strong identity match; this source is not authorized to create an object."]), evidence_id),
                        )
                        evidence_count -= 1
                        continue
                    else:
                        linked_count += 1
                    connection.execute(
                        """INSERT INTO engine_v2_object_evidence(object_id, evidence_id, link_reason_json, linked_at_utc)
                           VALUES (?, ?, ?, ?)""",
                        (object_id, evidence_id, json.dumps(reason, ensure_ascii=False, sort_keys=True), now),
                    )
                    self._register_strong_identifiers(
                        connection, row, source, config.object_template, object_id, evidence_id, batch_id, now,
                    )
                    fact_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO engine_v2_source_facts
                           (fact_id, object_id, evidence_id, batch_id, object_template_version_id,
                            source_id, source_version_id, source_file, source_checksum, row_number,
                            sheet_name, recorded_at_utc)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (fact_id, object_id, evidence_id, batch_id, config.object_template.version_id,
                         source.source_id, source.version_id, str(resolved), checksum, row.row_number,
                         row.sheet_name, now),
                    )
                    for property_definition in config.object_template.definition.get("properties", ()):
                        if str(property_definition.get("source_id", "")) != source.source_id:
                            continue
                        source_field_key = str(property_definition.get("field_key", "")).strip()
                        if not source_field_key or source_field_key not in row.normalized_values:
                            continue
                        property_key = str(
                            property_definition.get("canonical_property_key") or source_field_key
                        ).strip()
                        connection.execute(
                            """INSERT INTO engine_v2_object_property_values
                               (property_value_id, fact_id, object_id, evidence_id,
                                object_template_version_id, source_id, source_version_id,
                                property_key, source_field_key, data_type, value_json, recorded_at_utc)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (str(uuid.uuid4()), fact_id, object_id, evidence_id,
                             config.object_template.version_id, source.source_id, source.version_id,
                             property_key, source_field_key,
                             str(property_definition.get("data_type", "string")),
                             json.dumps(row.normalized_values[source_field_key], ensure_ascii=False, sort_keys=True, default=str),
                             now),
                        )
                if quarantine_count and status == "COMPLETED":
                    status = "COMPLETED_WITH_WARNINGS"
                if messages and status == "COMPLETED":
                    status = "COMPLETED_WITH_WARNINGS"
                connection.execute(
                    """UPDATE engine_v2_batches SET status = ?, total_rows = ?, evidence_rows = ?,
                       quarantined_rows = ?, objects_created = ?, objects_linked = ?,
                       completed_at_utc = ?, message = ? WHERE batch_id = ?""",
                    (status, len(rows), evidence_count, quarantine_count, created_count, linked_count,
                     _utc_now(), "; ".join(messages), batch_id),
                )
                self._update_observation(connection, source, resolved, checksum, status, "")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not file_errors:
            rule_diagnostics = []
            try:
                after_findings, rule_diagnostics = evaluate_configured_rules(
                    self.database_path, phase="AFTER", source_id=source.source_id,
                    source_system_key=str(source.definition.get("business_rule_source_system", "")), rows=rows,
                )
            except Exception as exc:
                after_findings = []
                rule_diagnostics = [f"AFTER rule evaluation unavailable ({type(exc).__name__})."]
            try:
                connection = connect(self.database_path)
                try:
                    with connection:
                        persist_v2_findings(
                            connection, findings=before_findings + after_findings, batch_id=batch_id,
                            source_id=source.source_id, source_version_id=source.version_id,
                            object_type_id=config.object_template.object_type_id,
                        )
                        if rule_diagnostics:
                            existing_batch = connection.execute(
                                "SELECT status, message FROM engine_v2_batches WHERE batch_id = ?",
                                (batch_id,),
                            ).fetchone()
                            if existing_batch is not None:
                                updated_message = "; ".join(filter(None, [
                                    str(existing_batch["message"]),
                                    *(f"Advisory rule: {message}" for message in rule_diagnostics),
                                ]))
                                updated_status = "COMPLETED_WITH_WARNINGS" if existing_batch["status"] == "COMPLETED" else existing_batch["status"]
                                connection.execute(
                                    "UPDATE engine_v2_batches SET status = ?, message = ? WHERE batch_id = ?",
                                    (updated_status, updated_message, batch_id),
                                )
                                status = updated_status
                                messages.extend(f"Advisory rule: {message}" for message in rule_diagnostics)
                finally:
                    connection.close()
            except Exception as exc:  # findings are advisory and cannot undo an imported batch
                diagnostic = f"Advisory rule findings could not be saved ({type(exc).__name__})."
                messages.append(diagnostic)
                status = "COMPLETED_WITH_WARNINGS" if status == "COMPLETED" else status
                try:
                    connection = connect(self.database_path)
                    try:
                        with connection:
                            connection.execute(
                                "UPDATE engine_v2_batches SET status = ?, message = CASE WHEN message = '' THEN ? ELSE message || '; ' || ? END WHERE batch_id = ?",
                                (status, diagnostic, diagnostic, batch_id),
                            )
                    finally:
                        connection.close()
                except Exception:
                    pass
        return EngineRunResult(batch_id, source.source_id, source.version_id, config.object_template.version_id,
                               str(resolved), checksum, status, len(rows), evidence_count,
                               quarantine_count, created_count, linked_count, "; ".join(messages))

    def observe_error(self, path: Path, source: SourceTemplate, error: str) -> None:
        connection = connect(self.database_path)
        try:
            with connection:
                self._update_observation(connection, source, path.resolve(), "", "RETRY", error)
        finally:
            connection.close()

    @staticmethod
    def _update_observation(
        connection,
        source: SourceTemplate,
        path: Path,
        checksum: str,
        status: str,
        error: str,
        *,
        authorized_by: str | None = None,
        authorized_at_utc: str | None = None,
    ) -> str:
        now = _utc_now()
        connection.execute(
            """INSERT INTO engine_v2_file_observations
               (observation_id, source_id, source_version_id, path, signature, status,
                first_seen_at_utc, last_seen_at_utc, authorized_by, authorized_at_utc, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, source_version_id, path) DO UPDATE SET
                 signature = excluded.signature, status = excluded.status,
                 last_seen_at_utc = excluded.last_seen_at_utc,
                 authorized_by = CASE
                   WHEN engine_v2_file_observations.signature <> excluded.signature THEN excluded.authorized_by
                   WHEN excluded.authorized_by IS NOT NULL THEN excluded.authorized_by
                   ELSE engine_v2_file_observations.authorized_by END,
                 authorized_at_utc = CASE
                   WHEN engine_v2_file_observations.signature <> excluded.signature THEN excluded.authorized_at_utc
                   WHEN excluded.authorized_at_utc IS NOT NULL THEN excluded.authorized_at_utc
                   ELSE engine_v2_file_observations.authorized_at_utc END,
                 last_error = excluded.last_error""",
            (str(uuid.uuid4()), source.source_id, source.version_id, str(path), checksum,
             status, now, now, authorized_by, authorized_at_utc, error),
        )
        row = connection.execute(
            "SELECT observation_id FROM engine_v2_file_observations WHERE source_id = ? AND source_version_id = ? AND path = ?",
            (source.source_id, source.version_id, str(path)),
        ).fetchone()
        return str(row[0])

    @staticmethod
    def _find_object(connection, row: ParsedSourceRow, source: SourceTemplate, object_template: ObjectTemplate) -> tuple[str | None, dict[str, Any], bool]:
        definition = object_template.definition
        current_values = row.normalized_values
        candidates: dict[str, dict[str, Any]] = {}
        configured_ids = {
            (str(item.get("source_id", "")), str(item.get("field_key", ""))): item
            for item in definition.get("identifiers", ())
        }
        for (source_id, field_key), identifier in configured_ids.items():
            if source_id != source.source_id or identifier.get("strength") != "STRONG":
                continue
            value = str(current_values.get(field_key, ""))
            if not value:
                continue
            matches = _existing_identifier_values(
                connection, object_template.object_type_id, source_id, field_key, value,
            )
            matches.extend(str(evidence["object_id"]) for evidence in _existing_evidence(
                connection, object_template.object_type_id, object_template.version_id,
                source_id, field_key,
            ) if str(evidence["value"]) == value)
            for matched_object_id in matches:
                candidates[matched_object_id] = {"kind": "same_source_strong", "field_key": field_key}

        for match in definition.get("matches", ()):
            left = match.get("left", {})
            right = match.get("right", {})
            left_ref = (str(left.get("source_id", "")), str(left.get("field_key", "")))
            right_ref = (str(right.get("source_id", "")), str(right.get("field_key", "")))
            if source.source_id == left_ref[0]:
                current_ref, other_ref = left_ref, right_ref
            elif source.source_id == right_ref[0]:
                current_ref, other_ref = right_ref, left_ref
            else:
                continue
            value = str(current_values.get(current_ref[1], ""))
            if not value:
                continue
            matches = _existing_identifier_values(
                connection, object_template.object_type_id, other_ref[0], other_ref[1], value,
            )
            matches.extend(str(evidence["object_id"]) for evidence in _existing_evidence(
                connection, object_template.object_type_id, object_template.version_id,
                other_ref[0], other_ref[1],
            ) if str(evidence["value"]) == value)
            for matched_object_id in matches:
                candidates[matched_object_id] = {
                    "kind": "configured_cross_source_strong",
                    "from": list(current_ref), "to": list(other_ref),
                }
        if len(candidates) > 1:
            return None, {}, True
        if not candidates:
            return None, {}, False
        object_id, reason = next(iter(candidates.items()))
        return object_id, reason, False

    @staticmethod
    def _register_strong_identifiers(
        connection, row: ParsedSourceRow, source: SourceTemplate, object_template: ObjectTemplate,
        object_id: str, evidence_id: str, batch_id: str, recorded_at_utc: str,
    ) -> None:
        if not object_template.object_type_id:
            # Preserve the engine API contract for callers that construct an
            # isolated configuration directly. Runtime catalog loads always
            # require a registered stable object type.
            return
        for identifier in object_template.definition.get("identifiers", ()):
            if (str(identifier.get("source_id", "")) != source.source_id
                    or str(identifier.get("strength", "")).upper() != "STRONG"):
                continue
            field_key = str(identifier.get("field_key", "")).strip()
            raw_value = row.normalized_values.get(field_key)
            if not field_key or raw_value in (None, ""):
                continue
            connection.execute(
                """INSERT INTO engine_v2_strong_identifiers
                   (identifier_value_id, object_type_id, object_id, source_id, source_version_id,
                    field_key, identifier_value, object_template_version_id, evidence_id, batch_id,
                    recorded_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(object_type_id, source_id, field_key, identifier_value) DO NOTHING""",
                (str(uuid.uuid4()), object_template.object_type_id, object_id, source.source_id,
                 source.version_id, field_key, str(raw_value), object_template.version_id,
                 evidence_id, batch_id, recorded_at_utc),
            )


def _existing_evidence(
    connection, object_type_id: str, object_template_version_id: str, source_id: str, field_key: str,
):
    rows = connection.execute(
        """SELECT oe.object_id, e.normalized_json FROM engine_v2_object_evidence oe
           JOIN engine_v2_evidence e ON e.evidence_id = oe.evidence_id
           JOIN engine_v2_batches b ON b.batch_id = e.batch_id
           JOIN engine_v2_objects o ON o.object_id = oe.object_id
           WHERE ((? <> '' AND o.object_type_id = ?)
               OR (? = '' AND o.object_template_version_id = ?))
             AND b.source_id = ? AND e.status = 'STAGED'""",
        (object_type_id, object_type_id, object_type_id, object_template_version_id, source_id),
    ).fetchall()
    found = []
    for row in rows:
        try:
            normalized = json.loads(row["normalized_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if field_key in normalized:
            found.append({"object_id": row["object_id"], "value": normalized[field_key]})
    return found


def _existing_identifier_values(
    connection, object_type_id: str, source_id: str, field_key: str, identifier_value: str,
) -> list[str]:
    if not object_type_id:
        return []
    return [str(row[0]) for row in connection.execute(
        """SELECT object_id FROM engine_v2_strong_identifiers
           WHERE object_type_id = ? AND source_id = ? AND field_key = ? AND identifier_value = ?""",
        (object_type_id, source_id, field_key, identifier_value),
    ).fetchall()]


def _source_can_create_object(source: SourceTemplate, object_template: ObjectTemplate) -> bool:
    if not object_template.definition.get("allow_object_creation"):
        return False
    identity = source.definition.get("identity_governance") or {}
    selected = [item for item in object_template.definition.get("identifiers", ())
                if item.get("source_id") == source.source_id and item.get("strength") == "STRONG"
                and item.get("can_create_identity") and item.get("source_can_create_object")]
    permitted = [item for item in identity.get("identifiers", ())
                 if item.get("strength") == "STRONG" and item.get("can_match") and item.get("can_create_identity")]
    return (identity.get("role") == "IDENTITY_SEED" and bool(identity.get("can_create_employee"))
            and len(permitted) >= 2 and len(selected) >= 2)


def _source_key(values: dict[str, Any], source: SourceTemplate, object_template: ObjectTemplate) -> str:
    identifiers = [item for item in object_template.definition.get("identifiers", ())
                   if item.get("source_id") == source.source_id and item.get("strength") == "STRONG"]
    parts = [f"{item.get('field_key')}={values.get(item.get('field_key'), '')}" for item in identifiers if values.get(item.get("field_key")) not in (None, "")]
    return "|".join(parts)
