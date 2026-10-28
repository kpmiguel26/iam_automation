"""
File: iam_automation/interfaces/web/employee_routes.py
Purpose: Defines Flask routes for the employee routes area.
Responsibilities: Exposes or coordinates: create_employee_blueprint.
Dependencies: flask, application, identity
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

from functools import wraps
import hashlib
import json
import logging
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ...application.audit_service import record_audit
from ...application.business_rule_service import BusinessRuleService
from ...application.employee_service import EmployeeService
from ...application.file_watch_service import load_watcher_health, load_watcher_manifest
from ...application.ingestion.orchestrator import IngestionOrchestrator
from ...application.notification_service import NotificationService
from ...application.parallel_engine.database import connect as connect_parallel_engine
from ...application.parallel_engine.feature_flags import FILE_PROCESSING_ENABLED
from ...application.request_service import OPERATION_OPTIONS, RequestService
from ...application.shared_request_service import SharedRequestService
from ...infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, orm_session
from ...identity import CurrentUser


import_logger = logging.getLogger("iam.import")


def create_employee_blueprint(database_path: Path, *, sharepoint_root: Path | None = None, audit_path: Path | None = None) -> Blueprint:
    blueprint = Blueprint("employees", __name__, url_prefix="/employees")
    service = EmployeeService(database_path)
    business_rules = BusinessRuleService(database_path)
    requests = SharedRequestService(sharepoint_root) if sharepoint_root else RequestService(database_path)
    source_order = ("ROSTER_LOCK", "MASTER_ROSTER", "RSR_SUPPLIER_WORKER_DETAILS", "ACCESSNOW")
    import_tasks: dict[str, dict[str, object]] = {}
    import_task_by_file: dict[tuple[str, str], str] = {}
    import_tasks_lock = threading.RLock()
    import_execution_lock = threading.Lock()

    def task_snapshot(task_id: str | None) -> dict[str, object] | None:
        if not task_id:
            return None
        with import_tasks_lock:
            task = import_tasks.get(task_id)
            return dict(task) if task else None

    def update_task(task_id: str, **updates: object) -> None:
        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if task is not None:
                task.update(updates)

    def task_for_file(source_system: str, source_file: str) -> dict[str, object] | None:
        with import_tasks_lock:
            task_id = import_task_by_file.get((source_system, source_file))
        return task_snapshot(task_id)

    def pending_source_update_count() -> int:
        """Count database review work plus reports found only by discovery."""
        count = service.pending_source_update_count()
        manifest = load_watcher_manifest(database_path).get("observations", {})
        if not isinstance(manifest, dict):
            return count
        source_kinds = set(source_order)
        imported_paths = {
            str(file.get("source_path", ""))
            for source_system in source_order
            for file in service.list_source_files(source_system)
            if file.get("source_path")
        }
        discovered_only = sum(
            1
            for item in manifest.values()
            if isinstance(item, dict)
            and item.get("source_system") in source_kinds
            and str(item.get("path", "")) not in imported_paths
        )
        return count + discovered_only

    def parallel_engine_panel() -> dict[str, object] | None:
        """Build an admin-only, read-only summary for the runtime-v2 watcher."""
        roles = {str(role).strip().upper() for role in session.get("iam_roles", ())}
        if not roles & {"APPLICATION_ADMIN", "MASTER_ADMIN", "SUPER_OPERATOR"}:
            return None
        engine = current_app.extensions.get("parallel_engine")
        if engine is None:
            return {"available": False, "error": "Runtime v2 is not connected to this app process."}
        watcher = current_app.extensions.get("parallel_engine_watcher")
        watcher_runtime = watcher.runtime_status() if watcher is not None else {
            "active": False,
            "activity": "IDLE",
            "files_checked_this_cycle": 0,
            "processing_file": "",
        }

        configuration = None
        configuration_error = ""
        try:
            configuration = engine.configuration()
        except Exception as exc:
            configuration_error = f"{type(exc).__name__}: {exc}"

        connection = connect_parallel_engine(database_path)
        try:
            health_row = connection.execute(
                "SELECT * FROM engine_v2_watcher_state WHERE singleton_id = 1"
            ).fetchone()
            status_counts = {
                str(row["status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM engine_v2_file_observations GROUP BY status"
                ).fetchall()
            }
            observation_count = int(connection.execute(
                "SELECT COUNT(*) FROM engine_v2_file_observations"
            ).fetchone()[0])
            observations = [dict(row) for row in connection.execute(
                """SELECT o.observation_id, o.source_id, o.source_version_id, o.path, o.signature,
                          o.status, o.first_seen_at_utc, o.last_seen_at_utc,
                          o.authorized_by, o.authorized_at_utc, o.last_error,
                          b.batch_id, b.status AS batch_status, b.total_rows,
                          b.evidence_rows, b.quarantined_rows, b.objects_created, b.objects_linked,
                          b.message AS batch_message
                   FROM engine_v2_file_observations o
                   LEFT JOIN engine_v2_batches b ON b.batch_id = (
                       SELECT candidate.batch_id FROM engine_v2_batches candidate
                       WHERE candidate.source_id = o.source_id
                         AND candidate.source_version_id = o.source_version_id
                         AND candidate.source_file = o.path
                         AND candidate.source_checksum = o.signature
                       ORDER BY candidate.started_at_utc DESC LIMIT 1
                   )
                   ORDER BY o.last_seen_at_utc DESC LIMIT 50"""
            ).fetchall()]
            batches = [dict(row) for row in connection.execute(
                """SELECT batch_id, source_id, source_version_id, source_file, status,
                          total_rows, evidence_rows, quarantined_rows, objects_created,
                          objects_linked, started_at_utc, completed_at_utc, message
                   FROM engine_v2_batches ORDER BY started_at_utc DESC LIMIT 50"""
            ).fetchall()]
            for batch in batches:
                diagnostic_counts: Counter[str] = Counter()
                for row in connection.execute(
                    "SELECT diagnostics_json, COUNT(*) AS row_count FROM engine_v2_evidence WHERE batch_id = ? GROUP BY diagnostics_json",
                    (batch["batch_id"],),
                ).fetchall():
                    try:
                        diagnostics = json.loads(row["diagnostics_json"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        diagnostics = ["Unparseable diagnostics payload"]
                    for diagnostic in diagnostics if isinstance(diagnostics, list) else [str(diagnostics)]:
                        diagnostic_counts[str(diagnostic)] += int(row["row_count"])
                batch["diagnostics"] = [
                    {"message": message, "row_count": count}
                    for message, count in diagnostic_counts.most_common(4)
                ]
            batches_by_id = {str(batch["batch_id"]): batch for batch in batches}
        finally:
            connection.close()

        sources = []
        if configuration:
            for source in configuration.sources:
                try:
                    folder = str(source.watched_path.relative_to(engine.sharepoint_root)) or "."
                except ValueError:
                    folder = source.watched_path.name
                sources.append({
                    "source_id": source.source_id,
                    "display_name": source.display_name,
                    "version_number": source.version_number,
                    "folder": folder,
                    "ingestion_order": source.ingestion_order,
                })
        for observation in observations:
            observation["filename"] = Path(str(observation["path"])).name
            observation["diagnostic"] = observation["last_error"] or observation["batch_message"] or ""
            observation["processing_progress"] = (
                watcher.processing_progress(str(observation["observation_id"])) if watcher is not None else None
            )
            batch = batches_by_id.get(str(observation.get("batch_id") or ""), {})
            observation["diagnostics"] = batch.get("diagnostics", [])
        for batch in batches:
            batch["filename"] = Path(str(batch["source_file"])).name
        configured_source_ids = set()
        for source in sources:
            configured_source_ids.add(source["source_id"])
            source_observations = [item for item in observations if item["source_id"] == source["source_id"]]
            source["observations"] = source_observations
            source["file_count"] = len(source_observations)
            source["pending_count"] = sum(item["status"] == "PENDING_AUTHORIZATION" for item in source_observations)
            source["error_count"] = sum(
                item["status"] in {"UNRECOGNIZED", "AMBIGUOUS", "ERROR"}
                or int(item.get("quarantined_rows") or 0) > 0
                for item in source_observations
            )
        other_observations = [item for item in observations if item["source_id"] not in configured_source_ids]
        return {
            "available": True,
            "health": dict(health_row) if health_row else {"status": "STARTING"},
            "watcher_runtime": watcher_runtime,
            "configuration_error": configuration_error,
            "has_configuration": configuration is not None,
            "sources": sources,
            "status_counts": status_counts,
            "observation_count": observation_count,
            "observations": observations,
            "other_observations": other_observations,
            "batches": batches,
            "can_authorize": FILE_PROCESSING_ENABLED and bool(roles & {"APPLICATION_ADMIN", "MASTER_ADMIN"}),
            "processing_enabled": FILE_PROCESSING_ENABLED,
        }

    def notify_import_result(task: dict[str, object], actor: str, *, status: str, result: dict[str, object] | None = None, error: str = "") -> str:
        """Persist the import outcome for the actor in the shared notification center."""
        source_system = str(task.get("source_system", ""))
        source_file = str(task.get("source_file", ""))
        result = result or {}
        processed = int(result.get("processed", task.get("processed", 0)) or 0)
        created = int(result.get("created", task.get("created", 0)) or 0)
        reused = int(result.get("reused", task.get("reused", 0)) or 0)
        failed = int(result.get("failed", task.get("failed", 0)) or 0)
        target_route = "/employees/source-updates"
        if source_system and source_file:
            target_route += "?" + urlencode({"source": source_system, "file": source_file})
        if status == "FAILED":
            notification_type = "SOURCE_FILE_IMPORT_FAILED"
            severity = "ERROR"
            title = "Source file import failed"
            message = f"The {source_system.replace('_', ' ').title()} file {source_file} could not be imported. {error or 'Review the task details for the error.'}"
        else:
            notification_type = "SOURCE_FILE_IMPORT_COMPLETED"
            severity = "WARNING" if status == "COMPLETED_WITH_WARNINGS" else "INFO"
            title = "Source file import completed" if severity == "INFO" else "Source file import completed with warnings"
            message = (
                f"{source_file}: {processed} row(s) processed, {created} new employee(s), "
                f"{int(result.get('changed', 0) or 0)} employee change(s), "
                f"{int(result.get('unchanged', 0) or 0)} unchanged row(s), and {failed} error(s). "
                "Changes are local and require administrator publication to share them."
            )
        try:
            stable_notification_id = hashlib.sha256(
                f"source-file-import:{actor.casefold()}:{source_system}:{source_file}:{task.get('source_checksum', '')}".encode("utf-8")
            ).hexdigest()
            return NotificationService(database_path).create(
                actor,
                notification_type,
                title,
                message,
                severity=severity,
                target_route=target_route,
                entity_type="source_file",
                entity_id=f"{source_system}:{source_file}",
                notification_id=stable_notification_id,
            )
        except Exception:  # pragma: no cover - notification storage failure must not hide import result
            import_logger.exception("IMPORT NOTIFICATION FAILED | source=%s | file=%s | actor=%s", source_system, source_file, actor)
            return ""

    def run_import_task(task_id: str, record_ids: list[str], actor: str) -> None:
        update_task(task_id, status="RUNNING", started_at=datetime.now(timezone.utc).isoformat(), message="Importing source history…")
        task = task_snapshot(task_id) or {}
        import_logger.info("IMPORT STARTED | source=%s | file=%s | rows=%s | task=%s", task.get("source_system"), task.get("source_file"), len(record_ids), task_id[:8])

        def report_progress(processed: int, total: int, created: int, reused: int, failed: int) -> None:
            update_task(
                task_id,
                processed=processed,
                total=total,
                created=created,
                reused=reused,
                failed=failed,
                message=f"Processing row {processed} of {total}…",
            )

        try:
            with import_execution_lock:
                result = service.apply_approved_import_records(record_ids, actor, progress_callback=report_progress)
            failed = int(result.get("failed", 0))
            status = "COMPLETED_WITH_WARNINGS" if failed else "COMPLETED"
            update_task(
                task_id,
                status=status,
                processed=len(record_ids),
                total=len(record_ids),
                created=int(result.get("created", 0)),
                reused=int(result.get("reused", 0)),
                changed=int(result.get("changed", 0)),
                unchanged=int(result.get("unchanged", 0)),
                failed=failed,
                errors=list(result.get("errors", [])),
                completed_at=datetime.now(timezone.utc).isoformat(),
                message="Import completed with warnings." if failed else "Import completed successfully.",
            )
            task_after_import = task_snapshot(task_id) or {}
            rule_findings = business_rules.count_findings_for_records(record_ids)
            quarantined = int(task_after_import.get("quarantined", 0) or 0)
            update_task(
                task_id,
                rule_findings=rule_findings,
                total_quarantine=quarantined + rule_findings,
                message=(
                    f"Import completed with {rule_findings} rule finding(s) to review."
                    if rule_findings
                    else ("Import completed with warnings." if failed else "Import completed successfully.")
                ),
            )
            notification_id = notify_import_result(task_snapshot(task_id) or {}, actor, status=status, result=result)
            if notification_id:
                update_task(task_id, notification_id=notification_id)
            import_logger.log(logging.WARNING if failed else logging.INFO, "IMPORT %s | source=%s | file=%s | processed=%s | created=%s | reused=%s | failed=%s | task=%s", status, task.get("source_system"), task.get("source_file"), result.get("processed", 0), result.get("created", 0), result.get("reused", 0), failed, task_id[:8])
        except Exception as exc:  # pragma: no cover - exercised by runtime failures
            update_task(
                task_id,
                status="FAILED",
                completed_at=datetime.now(timezone.utc).isoformat(),
                message=str(exc),
            )
            notification_id = notify_import_result(task_snapshot(task_id) or {}, actor, status="FAILED", error=str(exc))
            if notification_id:
                update_task(task_id, notification_id=notification_id)
            import_logger.exception("IMPORT FAILED | source=%s | file=%s | task=%s | error=%s", task.get("source_system"), task.get("source_file"), task_id[:8], exc)

    def source_timeline(*, include_imported: bool = True, max_files: int | None = None):
        grouped = {str(item["source_system"]): item for item in service.list_source_systems()}
        timeline = []
        previous_complete = True
        for source_system in source_order:
            files = service.list_source_files(source_system)
            manifest = load_watcher_manifest(database_path).get("observations", {})
            if isinstance(manifest, dict):
                known_paths = {str(item.get("source_path", item.get("source_file", ""))) for item in files}
                known_files = {str(item.get("source_file", "")) for item in files}
                for item in manifest.values():
                    if not isinstance(item, dict) or item.get("source_system") != source_system:
                        continue
                    manifest_path = str(item.get("path", ""))
                    if manifest_path in known_paths or Path(manifest_path.replace("\\", "/")).name in known_files:
                        continue
                    files.append({
                        "source_file": str(item.get("source_file", Path(str(item.get("path", ""))).name)),
                        "source_path": str(item.get("path", "")),
                        "source_checksum": str(item.get("source_checksum", "")),
                        "record_count": 0,
                        "pending_count": 0,
                        "ambiguous_count": 0,
                        "conflict_count": 0,
                        "linked_count": 0,
                        "imported": False,
                        "latest_at": item.get("updated_at_utc", ""),
                        "source_modified_at": item.get("updated_at_utc", ""),
                    })
            files.sort(key=lambda item: (str(item.get("source_modified_at") or item.get("latest_at") or ""), str(item.get("source_file", "")).casefold()))
            imported = bool(files) and all(bool(item.get("imported")) for item in files)
            # A row-level conflict must remain visible and retryable, but it
            # must not stop later source systems after the rest of its file
            # was processed. A file is considered progressed when at least
            # one row is no longer STAGED; a file with every row still STAGED
            # remains a true predecessor blocker.
            file_progress = [
                bool(file.get("imported"))
                or int(file.get("record_count", 0) or 0) > int(file.get("staged_count", 0) or 0)
                for file in files
            ]
            stage_can_advance = not files or all(file_progress)
            partial = bool(files) and not imported and stage_can_advance
            item = grouped.get(source_system, {"source_system": source_system, "label": "Fieldglass" if source_system == "RSR_SUPPLIER_WORKER_DETAILS" else service._source_label(source_system), "file_count": 0, "record_count": 0, "pending_count": 0, "linked_count": 0})
            item = dict(item)
            item["files"] = files
            item["step"] = len(timeline) + 1
            item["imported"] = imported
            item["partial"] = partial
            item["available"] = bool(files) and previous_complete and not imported
            item["blocked"] = bool(files) and not previous_complete
            item["timeline_status"] = "IMPORTED" if imported else "READY_TO_IMPORT" if item["available"] else "WAITING_FOR_FILE" if not files else "BLOCKED"
            next_file_index = next((index for index, file in enumerate(files) if not file.get("imported")), None)
            for index, file in enumerate(files):
                file["import_task"] = task_for_file(source_system, str(file["source_file"]))
                file["is_latest"] = bool(files) and index == len(files) - 1
                file["partial"] = bool(file_progress[index] and not file.get("imported"))
                file["available"] = bool(item["available"] and next_file_index == index)
            if not include_imported:
                # Keep the operational inbox focused on files that can still
                # require action. The complete list remains available in the
                # dedicated history view and the import workflow.
                item["files"] = [file for file in files if not file.get("imported") or int(file.get("pending_count", 0) or 0) > 0 or int(file.get("ambiguous_count", 0) or 0) > 0 or int(file.get("conflict_count", 0) or 0) > 0 or (file.get("import_task") or {}).get("status") == "FAILED"]
            elif max_files is not None:
                item["files"] = files[-max_files:]
            timeline.append(item)
            previous_complete = previous_complete and stage_can_advance
        return timeline

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("iam_user"):
                return "Application login required.", 401
            return view(*args, **kwargs)
        return wrapped

    @blueprint.get("")
    @authenticated
    def employee_directory():
        """Compatibility entry point; the default catalog now contains runtime objects."""
        return redirect(url_for("objects.directory", **request.args))

    @blueprint.get("/source-updates")
    @authenticated
    def source_updates_overview():
        source_system = request.args.get("source", "").strip()
        source_file = request.args.get("file", "").strip()
        mode = request.args.get("mode", "").strip().lower()
        view = request.args.get("view", "ATTENTION").strip().upper()
        if view not in {"ATTENTION", "RECENT_FILES"}:
            view = "ATTENTION"
        result_order = request.args.get("result_order", "RESULT").strip().upper()
        requested_all = request.args.get("all", "") == "1"
        if result_order not in {"RESULT", "NEW_HIRES", "UPDATED", "CURRENT", "PENDING"}:
            result_order = "RESULT"
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1
        page = requested_page
        sources = service.list_source_systems()
        files = service.list_source_files(source_system) if source_system else []
        file_summary = service.get_source_file_summary(source_system, source_file) if source_system and source_file else None
        load_all = requested_all or bool(file_summary and int(file_summary.get("record_count", 0) or 0) <= 1000)
        records, total_records = service.list_source_records(source_system, source_file, page=page, per_page=50, result_order=result_order, load_all=load_all) if file_summary else ([], 0)
        page_count = 1 if load_all else max(1, (total_records + 49) // 50)
        page = min(page, page_count)
        if file_summary and page != requested_page and not load_all:
            records, total_records = service.list_source_records(source_system, source_file, page=page, per_page=50, result_order=result_order, load_all=load_all)
        duplicate_summary = service.source_duplicate_summary(source_file=source_file) if mode == "duplicates" else None
        if files and view == "ATTENTION":
            files = [item for item in files if not item.get("imported") or int(item.get("pending_count", 0) or 0) > 0 or int(item.get("ambiguous_count", 0) or 0) > 0 or int(item.get("conflict_count", 0) or 0) > 0]
        elif files and view == "RECENT_FILES":
            files = sorted(files, key=lambda item: (str(item.get("source_modified_at") or item.get("latest_at") or ""), str(item.get("source_file") or "").casefold()), reverse=True)[:25]
        return render_template(
            "employees/source_updates_overview.html",
            sources=sources,
            files=files,
            records=records,
            total_records=total_records,
            page=page,
            page_count=page_count,
            source_system=source_system,
            source_file=source_file,
            file_summary=file_summary,
            mode=mode,
            result_order=result_order,
            load_all=load_all,
            duplicate_summary=duplicate_summary,
            view=view,
            source_timeline=source_timeline(include_imported=view == "RECENT_FILES", max_files=25 if view == "RECENT_FILES" else None),
            watcher_health=load_watcher_health(database_path),
            parallel_engine_panel=parallel_engine_panel() if not source_system else None,
        )

    @blueprint.get("/source-updates/watcher-status")
    @authenticated
    def source_updates_watcher_status():
        return render_template(
            "employees/_source_import_timeline.html",
            watcher_health=load_watcher_health(database_path),
            source_timeline=source_timeline(include_imported=request.args.get("view", "ATTENTION").upper() == "RECENT_FILES", max_files=25 if request.args.get("view", "ATTENTION").upper() == "RECENT_FILES" else None),
            show_history_files=request.args.get("view", "ATTENTION").upper() == "RECENT_FILES",
            view=request.args.get("view", "ATTENTION").upper(),
        )

    @blueprint.get("/source-updates/history")
    @authenticated
    def source_updates_history():
        source_filter = request.args.get("source", "").strip()
        status_filter = request.args.get("status", "ALL").strip().upper()
        search = request.args.get("q", "").strip().casefold()
        if status_filter not in {"ATTENTION", "IMPORTED", "ALL"}:
            status_filter = "ATTENTION"
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1

        systems = [source_filter] if source_filter else list(source_order)
        history_files = []
        for system in systems:
            for file in service.list_source_files(system):
                needs_attention = (
                    not file.get("imported")
                    or int(file.get("pending_count", 0) or 0) > 0
                    or int(file.get("ambiguous_count", 0) or 0) > 0
                    or int(file.get("conflict_count", 0) or 0) > 0
                )
                if status_filter == "ATTENTION" and not needs_attention:
                    continue
                if status_filter == "IMPORTED" and needs_attention:
                    continue
                if search and search not in str(file.get("source_file", "")).casefold():
                    continue
                file["needs_attention"] = needs_attention
                history_files.append(file)
        history_files.sort(key=lambda item: (str(item.get("source_modified_at") or item.get("latest_at") or ""), str(item.get("source_file") or "").casefold()), reverse=True)
        per_page = 25
        total_files = len(history_files)
        page_count = max(1, (total_files + per_page - 1) // per_page)
        page = min(requested_page, page_count)
        start = (page - 1) * per_page
        return render_template(
            "employees/source_updates_history.html",
            sources=service.list_source_systems(),
            files=history_files[start : start + per_page],
            total_files=total_files,
            page=page,
            page_count=page_count,
            source_filter=source_filter,
            status_filter=status_filter,
            search=request.args.get("q", "").strip(),
        )

    @blueprint.post("/source-updates/import")
    @authenticated
    def import_source_file():
        source_system = request.form.get("source_system", "").strip()
        source_file = request.form.get("source_file", "").strip()
        if source_system not in source_order or not source_file:
            return "Invalid source import request.", 400
        summary = service.get_source_file_summary(source_system, source_file)
        if summary is None:
            manifest = load_watcher_manifest(database_path).get("observations", {})
            candidate = next((item for item in manifest.values() if isinstance(item, dict) and item.get("source_system") == source_system and item.get("source_file") == source_file), None) if isinstance(manifest, dict) else None
            if not candidate or not Path(str(candidate.get("path", ""))).is_file():
                return "Source file was not found in discovery manifest.", 404
            source_path = Path(str(candidate["path"]))
            orchestrator = IngestionOrchestrator(database_path)
            if source_system == "ACCESSNOW":
                # AccessNow is a two-report source view; the orchestrator
                # evaluates rules around the same merged folder import.
                orchestrator.ingest_accessnow(source_path.parent, actor=str(session["iam_user"]))
            else:
                # Manual source imports must use the same BEFORE/AFTER rule
                # lifecycle as every other explicit ingestion entry point.
                orchestrator.ingest_file(source_system, source_path, actor=str(session["iam_user"]))
            summary = service.get_source_file_summary(source_system, source_file)
        if summary is None:
            return "Source file could not be staged for import.", 422
        timeline = source_timeline()
        with orm_session(database_path) as db_session:
            record_ids = list(db_session.scalars(select(IngestionRecordModel.record_id).where(IngestionRecordModel.source_system == source_system, IngestionRecordModel.source_file == summary["source_path"], IngestionRecordModel.status == "STAGED")).all())
            quarantine_rows = int(db_session.scalar(select(ImportBatchModel.quarantine_rows).where(ImportBatchModel.batch_id == select(IngestionRecordModel.batch_id).where(IngestionRecordModel.record_id == record_ids[0]).scalar_subquery())) or 0) if record_ids else 0
        if not record_ids:
            if request.headers.get("HX-Request"):
                return render_template("employees/_source_import_message.html", message="This file has already been imported."), 200
            return render_template("employees/_source_import_timeline.html", source_timeline=timeline, import_message="This file has already been imported."), 200
        current = next(item for item in timeline if item["source_system"] == source_system)
        if not current["available"]:
            return render_template("employees/_source_import_timeline.html", source_timeline=timeline, import_error="This source is not available yet. Import the previous source first."), 409
        file_key = (source_system, str(summary["source_file"]))
        with import_tasks_lock:
            existing_id = import_task_by_file.get(file_key)
            existing = import_tasks.get(existing_id) if existing_id else None
            if existing and existing.get("status") in {"QUEUED", "RUNNING"}:
                return render_template("employees/_source_import_task.html", task=dict(existing)), 202
            task_id = str(uuid.uuid4())
            import_tasks[task_id] = {
                "task_id": task_id,
                "source_system": source_system,
                "source_file": source_file,
                "source_label": str(current["label"]),
                "detected_at": str(summary.get("source_modified_at") or summary.get("latest_at", "")),
                "source_checksum": str(summary.get("source_checksum", "")),
                "review_url": url_for("employees.source_updates_overview", source=source_system, file=str(summary["source_file"])),
                "status": "QUEUED",
                "processed": 0,
                "total": len(record_ids),
                "created": 0,
                "reused": 0,
                "changed": 0,
                "unchanged": 0,
                "failed": 0,
                "quarantined": quarantine_rows,
                "rule_findings": 0,
                "total_quarantine": quarantine_rows,
                "errors": [],
                "message": "Queued for import…",
            }
            import_task_by_file[file_key] = task_id
        actor = str(session["iam_user"])
        threading.Thread(target=run_import_task, args=(task_id, record_ids, actor), name=f"source-import-{task_id[:8]}", daemon=True).start()
        return render_template("employees/_source_import_task.html", task=task_snapshot(task_id)), 202

    @blueprint.get("/source-updates/import-status/<task_id>")
    @authenticated
    def import_source_task_status(task_id: str):
        task = task_snapshot(task_id)
        if task is None:
            return "Import task was not found.", 404
        return render_template("employees/_source_import_task.html", task=task)

    @blueprint.get("/duplicates")
    @authenticated
    def canonical_duplicates():
        return render_template("employees/canonical_duplicates.html", groups=service.list_canonical_duplicates())

    @blueprint.route("/duplicates/<worker_id>", methods=["GET", "POST"])
    @authenticated
    def canonical_duplicate_review(worker_id: str):
        review = service.canonical_duplicate_review(worker_id)
        plan = service.canonical_duplicate_merge_plan(worker_id)
        if review is None or plan is None:
            return render_template("errors/404.html"), 404
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        error = None
        if request.method == "POST":
            if not current_user.can_decide_requests:
                error = "Only an administrator can merge canonical employee profiles."
            else:
                try:
                    survivor_id = str(plan["survivor"]["worker_id"])
                    result = None
                    for duplicate in plan["duplicates"]:
                        result = service.merge_workers(survivor_id, str(duplicate["worker_id"]), request.form.get("reason", ""), current_user.username)
                    record_audit(audit_path, current_user.username, "CANONICAL_WORKER_MERGED", "worker", survivor_id, new_values={"result": result, "selection": "automatic_completeness"})
                    return redirect(url_for("employees.canonical_duplicates"))
                except (OSError, ValueError, PermissionError) as exc:
                    error = str(exc)
        return render_template("employees/canonical_duplicate_review.html", review=review, plan=plan, can_merge=current_user.can_decide_requests, error=error)

    @blueprint.post("/source-updates/create-all")
    @authenticated
    def create_all_source_candidates():
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice="Only an administrator can run bulk creation.", notice_type="danger"))
        try:
            result = service.create_all_source_candidates(current_user.username)
            record_audit(audit_path, current_user.username, "ALL_SOURCE_CANDIDATES_APPLIED", "source_updates", "bulk", new_values={"result": result})
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice=f"Processed {result['dossiers']} record(s): {result['created']} employee(s) created, {result['reused']} reused, {result['skipped']} skipped, and {result['failed']} failed.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates_overview", all_people="1", notice=str(exc), notice_type="danger"))

    @blueprint.get("/source-updates/duplicate/<record_id>")
    @authenticated
    def duplicate_review(record_id: str):
        review = service.duplicate_review(record_id)
        if review is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/duplicate_review.html", review=review)

    @blueprint.get("/source-updates/candidate/<record_id>")
    @authenticated
    def source_candidate(record_id: str):
        preview = service.source_candidate_preview(record_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        return render_template("employees/source_candidate.html", preview=preview, can_apply=current_user.can_decide_requests, message=request.args.get("notice"), error=request.args.get("error"))

    def _request_source_change(*, operation_type: str, entity_id: str, payload: dict[str, object], reason: str, actor: str) -> str:
        current_user = CurrentUser(actor, "local-web", tuple(session.get("iam_roles", ())))
        item = requests.create(current_user, operation_type, entity_id, payload, reason)
        request_id = item.request_id
        NotificationService(database_path).notify_request_reviewers(request_id, operation_type, actor, record_count=len(payload.get("record_ids", [])))
        record_audit(audit_path, actor, "SOURCE_CHANGE_REQUEST_CREATED", "change_request", request_id, new_values={"operation_type": operation_type, "record_count": len(payload.get("record_ids", []))})
        return request_id

    @blueprint.get("/<worker_id>")
    @authenticated
    def employee_detail(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/detail.html", operation_options=OPERATION_OPTIONS, message=request.args.get("notice"), error=request.args.get("error"), **detail)

    @blueprint.get("/<worker_id>/edit")
    @authenticated
    def employee_edit(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/edit.html", operation_options=OPERATION_OPTIONS, message=request.args.get("notice"), error=request.args.get("error"), **detail)

    @blueprint.get("/<worker_id>/history")
    @authenticated
    def employee_history(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        return render_template("employees/history.html", **detail)

    @blueprint.get("/<worker_id>/source-updates")
    @authenticated
    def source_updates(worker_id: str):
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        return render_template("employees/source_updates.html", preview=preview, can_apply=current_user.can_decide_requests, message=request.args.get("notice"), error=request.args.get("error"))

    @blueprint.post("/source-updates/<worker_id>/apply")
    @authenticated
    def apply_source_updates(worker_id: str):
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="Only an administrator can apply source changes directly.", notice_type="danger"))
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        record_ids = sorted({str(update["record_id"]) for update in preview["updates"]})
        if not record_ids:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="No pending source changes are available.", notice_type="warning"))
        try:
            result = service.apply_selected_source_updates(worker_id, record_ids, request.form.getlist("apply_fields"), current_user.username)
            record_audit(audit_path, current_user.username, "EMPLOYEE_SOURCE_CHANGE_APPLIED", "worker", worker_id, new_values={"record_ids": record_ids, "result": result})
            return redirect(url_for("employees.source_updates", worker_id=worker_id, notice=f"Applied locally: {result.get('processed', 0)} source record(s). History updated. Publish SQLite separately to share it.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/<worker_id>/request")
    @authenticated
    def request_source_updates(worker_id: str):
        preview = service.source_update_preview(worker_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        record_ids = sorted({str(update["record_id"]) for update in preview["updates"]})
        if not record_ids:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error="No pending source changes are available.", notice_type="warning"))
        try:
            actor = str(session["iam_user"])
            request_id = _request_source_change(
                operation_type="UPDATE_EMPLOYEE",
                entity_id=worker_id,
                payload={"source_delta": True, "worker_id": worker_id, "record_ids": record_ids, "source_updates": preview["updates"], "fields": preview.get("fields", []), "apply_fields": request.form.getlist("apply_fields")},
                reason=request.form.get("reason", "Source update review"),
                actor=actor,
            )
            return redirect(url_for("employees.source_updates", worker_id=worker_id, notice=f"Request {request_id[:8]} submitted for administrator approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_updates", worker_id=worker_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/candidate/<record_id>/apply")
    @authenticated
    def apply_source_candidate(record_id: str):
        current_user = CurrentUser(str(session["iam_user"]), "local-web", tuple(session.get("iam_roles", ())))
        if not current_user.can_decide_requests:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error="Only an administrator can apply source changes directly.", notice_type="danger"))
        try:
            preview = service.source_candidate_preview(record_id)
            if preview is None:
                return render_template("errors/404.html"), 404
            record_ids = [str(item["record_id"]) for item in preview.get("records", [])]
            preparation = service.prepare_source_candidate(record_ids or [record_id], current_user.username)
            result = service.apply_approved_import_records(record_ids or [record_id], current_user.username)
            record_audit(audit_path, current_user.username, "NEW_EMPLOYEE_SOURCE_APPLIED", "ingestion_record", record_id, new_values={"result": result})
            return redirect(url_for("employees.source_candidate", record_id=record_id, notice=f"Applied {result.get('processed', 0)} source record(s) to one canonical employee. {'Created' if preparation['created'] else 'Reused'} worker {preparation['worker_id'][:8]}.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/source-updates/candidate/<record_id>/request")
    @authenticated
    def request_source_candidate(record_id: str):
        preview = service.source_candidate_preview(record_id)
        if preview is None:
            return render_template("errors/404.html"), 404
        try:
            actor = str(session["iam_user"])
            operation_type = "IMPORT_RSR_SUPPLIER_DETAILS" if preview["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS" else "IMPORT_ACCESSNOW" if preview["source_system"] == "ACCESSNOW" else "IMPORT_ROSTER_LOCK"
            evidence = list(preview.get("records", []))
            record_ids = [str(item["record_id"]) for item in evidence] or [record_id]
            request_id = _request_source_change(operation_type=operation_type, entity_id=str(preview["batch_id"]), payload={"record_ids": record_ids, "record_previews": evidence or [preview]}, reason=request.form.get("reason", "New source employee review"), actor=actor)
            return redirect(url_for("employees.source_candidate", record_id=record_id, notice=f"Request {request_id[:8]} submitted for administrator approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.source_candidate", record_id=record_id, error=str(exc), notice_type="danger"))

    @blueprint.post("/<worker_id>/request")
    @authenticated
    def request_employee_change(worker_id: str):
        detail = service.get_worker(worker_id)
        if detail is None:
            return render_template("errors/404.html"), 404
        try:
            actor = str(session["iam_user"])
            worker = detail["worker"]
            engagement = detail["engagements"][0] if detail["engagements"] else None
            current_values = {
                "first_name": worker.first_name or "",
                "last_name": worker.last_name or "",
                "email": worker.canonical_email or "",
                "status": worker.status or "",
                "job_title": engagement.job_title if engagement else "",
                "lob": engagement.lob if engagement else "",
                "vendor_name": engagement.vendor_name if engagement else "",
                "program": engagement.program if engagement else "",
                "project": engagement.project if engagement else "",
                "country": engagement.country if engagement else "",
                "site_location": engagement.site_location if engagement else "",
                "supervisor_name": engagement.supervisor_name if engagement else "",
                "onboarding_date": engagement.onboarding_date if engagement else "",
                "production_start_date": engagement.production_start_date if engagement else "",
                "engagement_status": engagement.status if engagement else "",
                "npn": engagement.npn if engagement else "",
                "license_state": engagement.license_state if engagement else "",
                "license_number": engagement.license_number if engagement else "",
                "taxonomy_code": engagement.taxonomy_code if engagement else "",
                "key_billable_function": engagement.key_billable_function if engagement else "",
            }
            submitted_values = {key: request.form.get(key, "").strip() for key in current_values}
            payload = {
                key: value
                for key, value in submitted_values.items()
                if value != current_values[key]
            }
            identifier_updates = {
                identifier.identifier_id: request.form.get(f"identifier_{identifier.identifier_id}", "").strip()
                for identifier in detail["identifiers"]
                if request.form.get(f"identifier_{identifier.identifier_id}", "").strip() != identifier.identifier_value
            }
            lineage_updates = {
                lineage.lineage_id: request.form.get(f"lineage_{lineage.lineage_id}", "").strip()
                for lineage in detail["lineage"]
                if request.form.get(f"lineage_{lineage.lineage_id}", "").strip() != lineage.normalized_value
            }
            if identifier_updates:
                payload["identifier_updates"] = identifier_updates
            if lineage_updates:
                payload["lineage_updates"] = lineage_updates
            if not payload:
                raise ValueError("No changes were entered.")
            operation_type = "DEACTIVATE_EMPLOYEE" if payload.get("status") in {"INACTIVE", "TERMINATED"} else "UPDATE_EMPLOYEE"
            item = requests.create(
                CurrentUser(actor, "local-web", tuple(session.get("iam_roles", ()))),
                operation_type,
                worker_id,
                payload,
                request.form.get("reason", ""),
            )
            record_audit(audit_path, actor, "EMPLOYEE_CHANGE_REQUEST_CREATED", "worker", worker_id, new_values={"request_id": item.request_id, "operation_type": item.operation_type})
            return redirect(url_for("employees.employee_detail", worker_id=worker_id, notice=f"Request {item.request_id[:8]} submitted for reviewer approval.", notice_type="success"))
        except (OSError, ValueError, PermissionError) as exc:
            return redirect(url_for("employees.employee_detail", worker_id=worker_id, error=str(exc), notice_type="danger"))

    return blueprint
#endfile
