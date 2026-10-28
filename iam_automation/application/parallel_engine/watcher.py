"""Independent configured-folder watcher for the parallel ingestion runtime."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .contracts import FileRecognitionAnalysis, RuntimeConfiguration, SourceTemplate, TemplateConfigurationError
from .database import connect
from .engine import ParallelIngestionEngine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParallelFileWatcher:
    """Discover approved-template files; processing waits for per-file authorization."""

    def __init__(self, engine: ParallelIngestionEngine, interval_seconds: float = 120.0):
        self.engine = engine
        self.database_path = engine.database_path
        self.interval_seconds = max(5.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cycle_lock = threading.Lock()
        self._runtime_state_lock = threading.Lock()
        self._activity = "IDLE"
        self._files_checked_this_cycle = 0
        self._processing_file = ""
        self._progress_lock = threading.Lock()
        self._processing_condition = threading.Condition(self._progress_lock)
        self._processing_progress: dict[str, dict[str, object]] = {}
        self._processing_queue: deque[tuple[str, str]] = deque()
        self._active_processing_observation: str | None = None
        self._processing_worker: threading.Thread | None = None

    def processing_progress(self, observation_id: str) -> dict[str, object] | None:
        with self._progress_lock:
            progress = self._processing_progress.get(observation_id)
            return dict(progress) if progress else None

    def _update_processing_progress(self, observation_id: str, **updates: object) -> None:
        with self._progress_lock:
            current = self._processing_progress.setdefault(observation_id, {})
            if updates.get("stage") == "checking":
                updates = {**updates, "status": "RUNNING", "queue_position": 0}
            current.update(updates)

    def start_authorized_processing(self, observation_id: str, actor: str) -> bool:
        """Add an authorized import to the serial background queue."""
        with self._processing_condition:
            current = self._processing_progress.get(observation_id, {})
            if current.get("status") in {"QUEUED", "RUNNING"}:
                return False
            self._processing_queue.append((observation_id, actor))
            queue_position = len(self._processing_queue) + (1 if self._active_processing_observation else 0)
            self._processing_progress[observation_id] = {
                "status": "QUEUED", "stage": "queued", "message": "Queued for processing",
                "queue_position": queue_position,
                "processed": 0, "total": 0, "created": 0, "linked": 0, "quarantined": 0,
            }
            if not self._processing_worker or not self._processing_worker.is_alive():
                self._processing_worker = threading.Thread(
                    target=self._run_processing_queue,
                    name="iam-engine-import-queue", daemon=True,
                )
                self._processing_worker.start()
            self._processing_condition.notify()
        return True

    def _run_processing_queue(self) -> None:
        """Process accepted imports one at a time, in the order they were queued."""
        while True:
            with self._processing_condition:
                while not self._processing_queue:
                    self._processing_condition.wait()
                observation_id, actor = self._processing_queue.popleft()
                self._active_processing_observation = observation_id
                progress = self._processing_progress.setdefault(observation_id, {})
                progress.update(queue_position=1)
                self._refresh_queue_positions_locked()
            try:
                result = self.authorize_and_process(
                    observation_id, actor,
                    progress_callback=lambda values: self._update_processing_progress(observation_id, **values),
                    wait_for_lock=True,
                )
            except Exception as exc:
                self._update_processing_progress(
                    observation_id, status="FAILED", stage="failed",
                    message=f"Import failed: {type(exc).__name__}: {exc}",
                )
            else:
                self._update_processing_progress(
                    observation_id, status="COMPLETED", stage="completed",
                    message="Import complete", processed=result.total_rows, total=result.total_rows,
                    created=result.objects_created, linked=result.objects_linked,
                    quarantined=result.quarantined_rows,
                )
            finally:
                with self._processing_condition:
                    self._active_processing_observation = None
                    self._refresh_queue_positions_locked()

    def _refresh_queue_positions_locked(self) -> None:
        """Refresh visible FIFO positions; caller must hold _processing_condition."""
        offset = 1 if self._active_processing_observation else 0
        for position, (observation_id, _actor) in enumerate(self._processing_queue, start=1 + offset):
            progress = self._processing_progress.setdefault(observation_id, {})
            progress["queue_position"] = position

    def runtime_status(self) -> dict[str, object]:
        """Return live watcher activity for status panels; persisted health remains authoritative for outcomes."""
        with self._runtime_state_lock:
            activity = self._activity
            files_checked = self._files_checked_this_cycle
            processing_file = self._processing_file
        return {
            "active": bool(self._thread and self._thread.is_alive()),
            "activity": activity,
            "files_checked_this_cycle": files_checked,
            "processing_file": processing_file,
        }

    def _set_runtime_activity(
        self, activity: str, *, files_checked: int | None = None, processing_file: str | None = None,
    ) -> None:
        with self._runtime_state_lock:
            self._activity = activity
            if files_checked is not None:
                self._files_checked_this_cycle = files_checked
            elif activity == "IDLE":
                self._files_checked_this_cycle = 0
            self._processing_file = processing_file or ""

    def start(self) -> "ParallelFileWatcher":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="iam-parallel-engine-watcher", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(0.1, timeout))

    def scan_once(self) -> int:
        if not self._cycle_lock.acquire(blocking=False):
            return 0
        processed = 0
        consecutive_failures = 0
        last_error = ""
        scanned_paths: set[Path] = set()
        self._set_runtime_activity("SCANNING", files_checked=0)
        try:
            configuration = self.engine.configuration()
            if configuration is None:
                self._write_health("WAITING_FOR_APPROVAL", 0, 0, "No approved Object Template is active.")
                return 0
            for source in configuration.sources:
                if self._stop.is_set():
                    break
                try:
                    files = self._source_files(source)
                except OSError as exc:
                    consecutive_failures += 1
                    last_error = f"{source.source_id}: {exc}"
                    continue
                for path in files:
                    try:
                        if path in scanned_paths:
                            continue
                        scanned_paths.add(path)
                        processed += 1
                        self._set_runtime_activity("SCANNING", files_checked=processed)
                        content, checksum = self._read_stable(path)
                        previous = self._observation(source, path)
                        if (
                            previous and previous["signature"] == checksum
                            and self._batch_exists(source, path, checksum, configuration)
                            and self._analysis_exists(source, path, checksum, configuration)
                        ):
                            continue
                        analyses = self.engine.analyze_file(path, content, configuration)
                        if not analyses:
                            analyses = (self.engine.analyze_source(path, content, source),)
                        matched = [item for item in analyses if item.recognition_status == "RECOGNIZED"]
                        ambiguous = len(matched) > 1
                        for analysis in analyses:
                            if ambiguous and analysis in matched:
                                status = "AMBIGUOUS"
                                error = "File recognition is ambiguous between: " + ", ".join(item.source.source_id for item in matched)
                            elif len(matched) == 1 and analysis is matched[0]:
                                if self._batch_exists(analysis.source, path, checksum, configuration):
                                    status = "PROCESSED"
                                    error = "This file already has a completed engine batch."
                                else:
                                    status = "PENDING_AUTHORIZATION"
                                    error = "Recognized and waiting for an approver to authorize this file."
                            else:
                                status = "UNRECOGNIZED"
                                error = " ".join(analysis.diagnostics) or "No configured report template recognizes this file."
                            self._record_analysis(
                                analysis, path, checksum, configuration.object_template.version_id, status, error,
                            )
                    except (OSError, PermissionError, ValueError, RuntimeError) as exc:
                        consecutive_failures += 1
                        last_error = f"{path.name}: {type(exc).__name__}: {exc}"
                        self.engine.observe_error(path, source, last_error)
                    except Exception as exc:
                        consecutive_failures += 1
                        last_error = f"{path.name}: {type(exc).__name__}: {exc}"
                        self.engine.observe_error(path, source, last_error)
            self._write_health("DEGRADED" if consecutive_failures else "HEALTHY", consecutive_failures, processed, last_error)
            return processed
        except Exception as exc:
            self._write_health("DEGRADED", max(1, consecutive_failures), processed, f"{type(exc).__name__}: {exc}")
            return processed
        finally:
            self._set_runtime_activity("IDLE")
            self._cycle_lock.release()

    def authorize_and_process(
        self, observation_id: str, actor: str, *, progress_callback=None, wait_for_lock: bool = False,
    ):
        """Process one unchanged, recognized file after an approver's explicit action."""
        acquired = self._cycle_lock.acquire() if wait_for_lock else self._cycle_lock.acquire(timeout=30)
        if not acquired:
            raise ValueError("The watcher is busy scanning files. Please try again shortly.")
        self._set_runtime_activity("PROCESSING")
        try:
            if progress_callback:
                progress_callback({"stage": "checking", "message": "Checking authorization and file signature"})
            connection = connect(self.database_path)
            try:
                row = connection.execute(
                    """SELECT source_id, source_version_id, path, signature, status
                       FROM engine_v2_file_observations WHERE observation_id = ?""",
                    (observation_id,),
                ).fetchone()
            finally:
                connection.close()
            if row is None or row["status"] != "PENDING_AUTHORIZATION":
                raise ValueError("This file is no longer awaiting authorization. Refresh the dashboard and review its current status.")
            self._set_runtime_activity("PROCESSING", processing_file=Path(str(row["path"])).name)
            if progress_callback:
                progress_callback({"stage": "recognition", "message": "Confirming source template"})

            configuration = self.engine.configuration()
            if configuration is None:
                raise ValueError("No approved Object Template is active in the runtime catalog.")
            source = next((item for item in configuration.sources
                           if item.source_id == row["source_id"] and item.version_id == row["source_version_id"]), None)
            if source is None:
                raise ValueError("This observation belongs to an outdated source version. Refresh the dashboard.")

            path = Path(str(row["path"])).expanduser().resolve()
            try:
                path.relative_to(source.watched_path.resolve())
                path.relative_to(self.engine.sharepoint_root)
            except ValueError as exc:
                raise ValueError("The observed file is outside its approved watched folder.") from exc

            content, checksum = self._read_stable(path)
            if checksum != str(row["signature"]):
                self._record(
                    source, path, checksum, "PENDING_AUTHORIZATION",
                    "The file changed after it was reviewed. Review and authorize the updated file.",
                )
                raise ValueError("The file changed after it was reviewed. Review and authorize the updated file.")

            try:
                recognized = self.engine.recognize(path, content, configuration)
            except TemplateConfigurationError as exc:
                self._record(source, path, checksum, "UNRECOGNIZED", str(exc))
                raise ValueError(str(exc)) from exc
            if recognized.source_id != source.source_id or recognized.version_id != source.version_id:
                raise ValueError("The file no longer matches the approved source snapshot.")

            authorized_at_utc = _now()
            self._record(
                source, path, checksum, "PROCESSING_AUTHORIZED",
                "Explicitly authorized by an approver.",
                authorized_by=actor, authorized_at_utc=authorized_at_utc,
            )
            try:
                result = self.engine.ingest_file(
                    path, content, configuration, authorized_by=actor,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                self._record(
                    source, path, checksum, "RETRY", f"{type(exc).__name__}: {exc}",
                    authorized_by=actor, authorized_at_utc=authorized_at_utc,
                )
                raise
            self._record(
                source, path, checksum, "PROCESSED", result.message,
                authorized_by=actor, authorized_at_utc=authorized_at_utc,
            )
            if progress_callback:
                progress_callback({"stage": "completed", "message": "Import complete"})
            return result
        finally:
            self._set_runtime_activity("IDLE")
            self._cycle_lock.release()

    def _source_files(self, source: SourceTemplate) -> tuple[Path, ...]:
        root = self.engine.sharepoint_root
        folder = source.watched_path.resolve()
        try:
            folder.relative_to(root)
        except ValueError as exc:
            raise TemplateConfigurationError(f"Configured folder for {source.source_id} escapes the SharePoint root.") from exc
        if not folder.is_dir():
            return ()
        found = []
        for path in folder.rglob("*"):
            if path.name.startswith(".") or not path.is_file() or path.suffix.casefold() not in {".csv", ".xlsx"}:
                continue
            try:
                path.resolve().relative_to(root)
            except ValueError:
                continue
            found.append(path.resolve())
        return tuple(sorted(found, key=lambda item: str(item).casefold()))

    @staticmethod
    def _read_stable(path: Path) -> tuple[bytes, str]:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise OSError("File is still changing; it will be retried on a later watcher cycle.")
        return content, hashlib.sha256(content).hexdigest()

    @staticmethod
    def _path_candidates(path: Path, configuration: RuntimeConfiguration) -> list[SourceTemplate]:
        candidates = []
        for source in configuration.sources:
            try:
                path.relative_to(source.watched_path)
            except ValueError:
                continue
            candidates.append(source)
        return candidates

    def _observation(self, source: SourceTemplate, path: Path):
        connection = connect(self.database_path)
        try:
            return connection.execute(
                """SELECT signature, status FROM engine_v2_file_observations
                   WHERE source_id = ? AND source_version_id = ? AND path = ?""",
                (source.source_id, source.version_id, str(path)),
            ).fetchone()
        finally:
            connection.close()

    def _batch_exists(self, source: SourceTemplate, path: Path, checksum: str, configuration: RuntimeConfiguration) -> bool:
        connection = connect(self.database_path)
        try:
            return connection.execute(
                """SELECT 1 FROM engine_v2_batches WHERE source_id = ? AND source_version_id = ?
                   AND object_template_version_id = ? AND source_file = ? AND source_checksum = ? LIMIT 1""",
                (source.source_id, source.version_id, configuration.object_template.version_id, str(path), checksum),
            ).fetchone() is not None
        finally:
            connection.close()

    def _analysis_exists(
        self, source: SourceTemplate, path: Path, checksum: str, configuration: RuntimeConfiguration,
    ) -> bool:
        connection = connect(self.database_path)
        try:
            return connection.execute(
                """SELECT 1 FROM engine_v2_file_analyses WHERE source_id = ? AND source_version_id = ?
                   AND object_template_version_id = ? AND path = ? AND file_checksum = ? LIMIT 1""",
                (source.source_id, source.version_id, configuration.object_template.version_id, str(path), checksum),
            ).fetchone() is not None
        finally:
            connection.close()

    def _record(
        self,
        source: SourceTemplate,
        path: Path,
        checksum: str,
        status: str,
        error: str,
        *,
        authorized_by: str | None = None,
        authorized_at_utc: str | None = None,
    ) -> str:
        connection = connect(self.database_path)
        try:
            with connection:
                observation_id = self.engine._update_observation(
                    connection, source, path, checksum, status, error,
                    authorized_by=authorized_by, authorized_at_utc=authorized_at_utc,
                )
            return observation_id
        finally:
            connection.close()

    def _record_analysis(
        self,
        analysis: FileRecognitionAnalysis,
        path: Path,
        checksum: str,
        object_template_version_id: str,
        observation_status: str,
        observation_error: str,
    ) -> None:
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        now = _now()
        connection = connect(self.database_path)
        try:
            with connection:
                observation_id = self.engine._update_observation(
                    connection, analysis.source, path, checksum, observation_status, observation_error,
                )
                connection.execute(
                    """INSERT INTO engine_v2_file_analyses
                       (analysis_id, observation_id, object_template_version_id, source_id,
                        source_version_id, path, file_name, file_checksum, file_size_bytes,
                        file_modified_at_utc, source_order, recognition_status, worksheet_name,
                        detected_headers_json, required_headers_json, missing_headers_json,
                        unknown_headers_json, checks_json, diagnostics_json, analyzed_at_utc)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_id, source_version_id, object_template_version_id, path, file_checksum)
                       DO UPDATE SET observation_id = excluded.observation_id,
                         file_name = excluded.file_name, file_size_bytes = excluded.file_size_bytes,
                         file_modified_at_utc = excluded.file_modified_at_utc,
                         source_order = excluded.source_order, recognition_status = excluded.recognition_status,
                         worksheet_name = excluded.worksheet_name,
                         detected_headers_json = excluded.detected_headers_json,
                         required_headers_json = excluded.required_headers_json,
                         missing_headers_json = excluded.missing_headers_json,
                         unknown_headers_json = excluded.unknown_headers_json,
                         checks_json = excluded.checks_json, diagnostics_json = excluded.diagnostics_json,
                         analyzed_at_utc = excluded.analyzed_at_utc""",
                    (
                        str(uuid.uuid4()), observation_id, object_template_version_id,
                        analysis.source.source_id, analysis.source.version_id, str(path), path.name,
                        checksum, stat.st_size, modified_at, analysis.source.ingestion_order,
                        analysis.recognition_status, analysis.worksheet_name,
                        json.dumps(analysis.detected_headers, ensure_ascii=False),
                        json.dumps(analysis.required_headers, ensure_ascii=False),
                        json.dumps(analysis.missing_headers, ensure_ascii=False),
                        json.dumps(analysis.unknown_headers, ensure_ascii=False),
                        json.dumps(analysis.checks, ensure_ascii=False, sort_keys=True),
                        json.dumps(analysis.diagnostics, ensure_ascii=False), now,
                    ),
                )
        finally:
            connection.close()

    def _write_health(self, status: str, failures: int, processed: int, error: str) -> None:
        connection = connect(self.database_path)
        now = _now()
        try:
            with connection:
                connection.execute(
                    """INSERT INTO engine_v2_watcher_state
                       (singleton_id, status, last_cycle_at_utc, last_success_at_utc,
                        consecutive_failures, last_processed_count, last_error)
                       VALUES (1, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(singleton_id) DO UPDATE SET
                         status = excluded.status, last_cycle_at_utc = excluded.last_cycle_at_utc,
                         last_success_at_utc = CASE WHEN excluded.status = 'HEALTHY' THEN excluded.last_cycle_at_utc ELSE engine_v2_watcher_state.last_success_at_utc END,
                         consecutive_failures = excluded.consecutive_failures,
                         last_processed_count = excluded.last_processed_count, last_error = excluded.last_error""",
                    (status, now, now if status == "HEALTHY" else None, failures, processed, error),
                )
        finally:
            connection.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            self._stop.wait(self.interval_seconds)
