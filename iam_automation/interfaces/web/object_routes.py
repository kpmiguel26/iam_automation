"""Authenticated, read-only views over runtime-v2 objects and their evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from ...application.parallel_engine.database import connect


PAGE_SIZE = 25
HISTORY_PAGE_SIZE = 50


def _source_filename(value: object) -> str:
    """Return a readable file name while retaining the original path in details."""
    raw = str(value or "").strip()
    return raw.replace("\\", "/").rsplit("/", 1)[-1] if raw else "File unavailable"


def _template_definition(connection, template_version_id: str | None) -> dict:
    if not template_version_id:
        return {}
    row = connection.execute(
        "SELECT definition_json FROM employee_template_versions WHERE employee_template_version_id = ?",
        (template_version_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError, AttributeError):
        return {}


def _presentation(connection, template_version_id: str | None) -> dict:
    return _template_definition(connection, template_version_id).get("presentation", {})


def _source_labels(connection, template_version_id: str | None) -> dict[str, str]:
    definition = _template_definition(connection, template_version_id)
    labels = {}
    for source in definition.get("source_templates", ()):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", ""))
        label = " ".join(str(source.get("source_label", "")).split())
        if source_id and label:
            labels[source_id] = label
    return labels


def _display_value(value_json: object) -> str:
    try:
        value = json.loads(value_json)
    except (TypeError, ValueError):
        value = value_json
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _configured_displays(connection, records: list[dict]) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    presentations = {}
    requested_by_object = {}
    for item in records:
        object_id = str(item["object_id"])
        version_id = item.get("object_template_version_id")
        if version_id not in presentations:
            presentations[version_id] = _presentation(connection, version_id)
        config = presentations[version_id]
        requested_by_object[object_id] = set(
            key for key in [config.get("title_property_key"), *config.get("context_property_keys", ())]
            if isinstance(key, str) and key
        )
    values_by_object = {object_id: {} for object_id in requested_by_object}
    object_ids = list(requested_by_object)
    for offset in range(0, len(object_ids), 400):
        chunk = object_ids[offset:offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"""SELECT object_id, property_key, value_json FROM engine_v2_object_property_values
                WHERE object_id IN ({placeholders}) AND value_json IS NOT NULL
                ORDER BY recorded_at_utc DESC, property_value_id DESC""",
            chunk,
        ).fetchall()
        for row in rows:
            object_id, key = str(row[0]), str(row[1])
            if key in requested_by_object[object_id] and key not in values_by_object[object_id]:
                value = _display_value(row[2])
                if value:
                    values_by_object[object_id][key] = value
    result = {}
    for item in records:
        object_id = str(item["object_id"])
        config = presentations.get(item.get("object_template_version_id"), {})
        values = values_by_object[object_id]
        title_key = config.get("title_property_key")
        context = [
            (str(key).replace("_", " ").replace(".", " ").title(), values[key])
            for key in config.get("context_property_keys", ())
            if key in values and values[key] and key != title_key
        ]
        result[object_id] = (values.get(title_key, ""), context)
    return result


def _configured_display(connection, object_id: str, template_version_id: str | None) -> tuple[str, list[tuple[str, str]]]:
    return _configured_displays(connection, [{
        "object_id": object_id, "object_template_version_id": template_version_id,
    }])[object_id]


def create_object_blueprint(database_path: Path, *, login_url: str = "/login") -> Blueprint:
    database_path = Path(database_path)
    blueprint = Blueprint("objects", __name__, url_prefix="/objects")

    @blueprint.before_request
    def require_login():
        if not session.get("iam_user"):
            return redirect(login_url)
        return None

    @blueprint.get("")
    def directory():
        filters = {
            "q": request.args.get("q", "").strip(),
            "type": request.args.get("type", "ALL").strip(),
            "source": request.args.get("source", "ALL").strip(),
            "status": request.args.get("status", "ALL").strip(),
            "property": request.args.get("property", "ALL").strip(),
            "value": request.args.get("value", "").strip(),
            "review": request.args.get("review", "ALL").strip().upper(),
            "updated": request.args.get("updated", "ALL").strip().upper(),
            "sort": request.args.get("sort", "UPDATED_DESC").strip().upper(),
            "all": request.args.get("all", "0") == "1",
        }
        if filters["review"] not in {"ALL", "OPEN", "CLEAR"}:
            filters["review"] = "ALL"
        if filters["updated"] not in {"ALL", "LAST_24_HOURS", "LAST_7_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"}:
            filters["updated"] = "ALL"
        if filters["sort"] not in {"UPDATED_DESC", "UPDATED_ASC", "ID_ASC", "ID_DESC"}:
            filters["sort"] = "UPDATED_DESC"
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1

        connection = connect(database_path)
        try:
            types = [dict(row) for row in connection.execute(
                "SELECT object_type_key, object_type_id FROM engine_v2_object_types ORDER BY object_type_key"
            ).fetchall()]
            statuses = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT status FROM engine_v2_objects ORDER BY status"
            ).fetchall()]
            sources = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT source_id FROM engine_v2_source_facts ORDER BY source_id"
            ).fetchall()]
            properties = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT property_key FROM engine_v2_object_property_values ORDER BY property_key"
            ).fetchall()]
            total_objects = int(connection.execute("SELECT COUNT(*) FROM engine_v2_objects").fetchone()[0])
            open_findings = int(connection.execute(
                "SELECT COUNT(DISTINCT object_id) FROM engine_v2_rule_findings WHERE status = 'OPEN' AND object_id IS NOT NULL"
            ).fetchone()[0])

            conditions: list[str] = []
            params: list[object] = []
            if filters["q"]:
                pattern = f"%{filters['q']}%"
                conditions.append("""(o.object_id LIKE ? OR EXISTS (
                    SELECT 1 FROM engine_v2_object_property_values p
                    WHERE p.object_id = o.object_id AND p.value_json LIKE ?
                ) OR EXISTS (
                    SELECT 1 FROM engine_v2_source_facts f
                    WHERE f.object_id = o.object_id AND f.source_file LIKE ?
                ))""")
                params.extend([pattern, pattern, pattern])
            if filters["type"] != "ALL":
                conditions.append("o.object_type_id = ?")
                params.append(filters["type"])
            if filters["source"] != "ALL":
                conditions.append("EXISTS (SELECT 1 FROM engine_v2_source_facts f WHERE f.object_id = o.object_id AND f.source_id = ?)")
                params.append(filters["source"])
            if filters["status"] != "ALL":
                conditions.append("o.status = ?")
                params.append(filters["status"])
            if filters["property"] != "ALL":
                property_condition = "p.object_id = o.object_id AND p.property_key = ?"
                property_params: list[object] = [filters["property"]]
                if filters["value"]:
                    property_condition += " AND p.value_json LIKE ?"
                    property_params.append(f"%{filters['value']}%")
                conditions.append(f"EXISTS (SELECT 1 FROM engine_v2_object_property_values p WHERE {property_condition})")
                params.extend(property_params)
            elif filters["value"]:
                conditions.append("EXISTS (SELECT 1 FROM engine_v2_object_property_values p WHERE p.object_id = o.object_id AND p.value_json LIKE ?)")
                params.append(f"%{filters['value']}%")
            if filters["review"] == "OPEN":
                conditions.append("EXISTS (SELECT 1 FROM engine_v2_rule_findings r WHERE r.object_id = o.object_id AND r.status = 'OPEN')")
            elif filters["review"] == "CLEAR":
                conditions.append("NOT EXISTS (SELECT 1 FROM engine_v2_rule_findings r WHERE r.object_id = o.object_id AND r.status = 'OPEN')")
            date_modifier = {
                "LAST_24_HOURS": "-1 day", "LAST_7_DAYS": "-7 days",
                "LAST_30_DAYS": "-30 days", "LAST_90_DAYS": "-90 days",
            }.get(filters["updated"])
            if date_modifier:
                conditions.append("EXISTS (SELECT 1 FROM engine_v2_source_facts f WHERE f.object_id = o.object_id AND julianday(f.recorded_at_utc) >= julianday('now', ?))")
                params.append(date_modifier)
            where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
            matching_count = int(connection.execute(
                "SELECT COUNT(*) FROM engine_v2_objects o" + where_sql, params,
            ).fetchone()[0])
            has_query = bool(
                filters["q"] or filters["type"] != "ALL" or filters["source"] != "ALL"
                or filters["status"] != "ALL" or filters["property"] != "ALL" or filters["value"]
                or filters["review"] != "ALL" or filters["updated"] != "ALL" or filters["all"]
            )
            page_size = matching_count if filters["all"] else PAGE_SIZE
            page_count = max(1, math.ceil(matching_count / page_size)) if page_size else 1
            page = min(requested_page, page_count)
            sort_sql = {
                "UPDATED_DESC": "last_updated DESC, o.created_at_utc DESC",
                "UPDATED_ASC": "last_updated ASC, o.created_at_utc ASC",
                "ID_ASC": "o.object_id ASC",
                "ID_DESC": "o.object_id DESC",
            }[filters["sort"]]
            if has_query:
                limit_sql = "" if filters["all"] else " LIMIT ? OFFSET ?"
                list_params = list(params)
                if not filters["all"]:
                    list_params.extend([PAGE_SIZE, (page - 1) * PAGE_SIZE])
                rows = [dict(row) for row in connection.execute(
                    f"""SELECT o.object_id, o.status, o.created_at_utc, o.object_type_id,
                               o.object_template_version_id,
                               t.object_type_key,
                               (SELECT MAX(f.recorded_at_utc) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS last_updated,
                               (SELECT COUNT(DISTINCT f.source_id) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS source_count,
                               (SELECT COUNT(*) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS evidence_count,
                               (SELECT COUNT(DISTINCT p.property_key) FROM engine_v2_object_property_values p WHERE p.object_id = o.object_id) AS property_count,
                               (SELECT COUNT(*) FROM engine_v2_rule_findings r WHERE r.object_id = o.object_id AND r.status = 'OPEN') AS open_findings
                        FROM engine_v2_objects o
                        LEFT JOIN engine_v2_object_types t ON t.object_type_id = o.object_type_id
                        {where_sql}
                        ORDER BY {sort_sql}{limit_sql}""",
                    list_params,
                ).fetchall()]
                display_values = _configured_displays(connection, rows)
                for item in rows:
                    item["display_title"], item["display_context"] = display_values[item["object_id"]]
            else:
                rows = []
        finally:
            connection.close()

        template_context = dict(
            objects=rows, filters=filters,
            types=types, statuses=statuses, sources=sources, properties=properties,
            total_objects=total_objects, matching_count=matching_count,
            open_findings=open_findings, has_query=has_query,
            page=page, page_count=page_count, page_size=PAGE_SIZE,
            oob_counts=False,
        )
        if request.headers.get("HX-Request") == "true":
            template_context["oob_counts"] = True
            return render_template("objects/_directory_results.html", **template_context)
        return render_template("objects/directory.html", **template_context)

    @blueprint.get("/<object_id>")
    def detail(object_id: str):
        connection = connect(database_path)
        try:
            obj = connection.execute(
                """SELECT o.object_id, o.status, o.created_at_utc, o.object_template_version_id,
                          o.object_type_id, t.object_type_key,
                          (SELECT MAX(f.recorded_at_utc) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS last_updated,
                          (SELECT COUNT(DISTINCT f.source_id) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS source_count,
                          (SELECT COUNT(*) FROM engine_v2_source_facts f WHERE f.object_id = o.object_id) AS evidence_count
                   FROM engine_v2_objects o LEFT JOIN engine_v2_object_types t ON t.object_type_id = o.object_type_id
                   WHERE o.object_id = ?""", (object_id,),
            ).fetchone()
            if obj is None:
                abort(404)
            source_labels = _source_labels(connection, obj["object_template_version_id"])
            properties = [dict(row) for row in connection.execute(
                """WITH ranked AS (
                     SELECT p.property_key, p.source_field_key, p.data_type, p.value_json,
                            p.source_id, p.source_version_id, p.recorded_at_utc, p.evidence_id,
                            e.row_number, e.sheet_name, b.source_file,
                            ROW_NUMBER() OVER (
                              PARTITION BY p.property_key, p.source_id
                              ORDER BY p.recorded_at_utc DESC, p.property_value_id DESC
                            ) AS row_rank
                     FROM engine_v2_object_property_values p
                     LEFT JOIN engine_v2_evidence e ON e.evidence_id = p.evidence_id
                     LEFT JOIN engine_v2_batches b ON b.batch_id = e.batch_id
                     WHERE p.object_id = ?
                   ) SELECT * FROM ranked WHERE row_rank = 1
                   ORDER BY property_key, source_id""", (object_id,),
            ).fetchall()]
            for item in properties:
                try:
                    item["value"] = json.loads(item["value_json"])
                except (TypeError, ValueError):
                    item["value"] = item["value_json"]
                item["source_filename"] = _source_filename(item.get("source_file"))
                item["source_label"] = source_labels.get(
                    item["source_id"], str(item["source_id"]).replace("_", " ").title()
                )
            sources = [dict(row) for row in connection.execute(
                """SELECT f.source_id, COUNT(*) AS fact_count, MAX(f.recorded_at_utc) AS last_seen,
                          (SELECT latest.source_file FROM engine_v2_source_facts latest
                           WHERE latest.object_id = f.object_id AND latest.source_id = f.source_id
                           ORDER BY latest.recorded_at_utc DESC LIMIT 1) AS latest_file
                   FROM engine_v2_source_facts f WHERE f.object_id = ?
                   GROUP BY f.source_id ORDER BY last_seen DESC, f.source_id""", (object_id,),
            ).fetchall()]
            for item in sources:
                item["latest_filename"] = _source_filename(item.get("latest_file"))
                item["source_label"] = source_labels.get(
                    item["source_id"], str(item["source_id"]).replace("_", " ").title()
                )
                item["properties"] = []
            source_groups = {item["source_id"]: item for item in sources}
            for item in properties:
                source_id = item["source_id"]
                if source_id not in source_groups:
                    source_groups[source_id] = {
                        "source_id": source_id,
                        "source_label": source_labels.get(
                            source_id, str(source_id).replace("_", " ").title()
                        ),
                        "fact_count": 0,
                        "last_seen": item.get("recorded_at_utc"),
                        "latest_filename": item["source_filename"],
                        "properties": [],
                    }
                source_groups[source_id]["properties"].append(item)
            property_groups = list(source_groups.values())
            identifiers = [dict(row) for row in connection.execute(
                """SELECT source_id, field_key, identifier_value, recorded_at_utc
                   FROM engine_v2_strong_identifiers WHERE object_id = ?
                   ORDER BY recorded_at_utc DESC, source_id, field_key""", (object_id,),
            ).fetchall()]
            findings = [dict(row) for row in connection.execute(
                """SELECT rule_name, phase, severity, status, title, message, field_key,
                          source_id, row_number, created_at_utc
                   FROM engine_v2_rule_findings WHERE object_id = ?
                   ORDER BY created_at_utc DESC""", (object_id,),
            ).fetchall()]
            recent_evidence = [dict(row) for row in connection.execute(
                """SELECT f.fact_id, f.source_id, f.source_file, f.row_number, f.sheet_name,
                          f.recorded_at_utc, e.evidence_id, e.status AS evidence_status
                   FROM engine_v2_source_facts f
                   JOIN engine_v2_evidence e ON e.evidence_id = f.evidence_id
                   WHERE f.object_id = ?
                   ORDER BY f.recorded_at_utc DESC, f.row_number DESC LIMIT 25""", (object_id,),
            ).fetchall()]
            for item in recent_evidence:
                item["source_filename"] = _source_filename(item.get("source_file"))
                item["source_label"] = source_labels.get(
                    item["source_id"], str(item["source_id"]).replace("_", " ").title()
                )
                status = str(item.get("evidence_status", "")).upper()
                item["evidence_status_label"] = {
                    "STAGED": "Captured",
                    "QUARANTINED": "Needs review",
                }.get(status, status.replace("_", " ").title() or "Recorded")
            for source in sources:
                source["recent_evidence"] = [
                    item for item in recent_evidence if item["source_id"] == source["source_id"]
                ]
            display_title, display_context = _configured_display(
                connection, object_id, obj["object_template_version_id"]
            )
        finally:
            connection.close()
        return render_template(
            "objects/detail.html", object_record=dict(obj), properties=properties,
            sources=sources, property_groups=property_groups,
            identifiers=identifiers, findings=findings,
            recent_evidence=recent_evidence, display_title=display_title,
            display_context=display_context,
        )

    @blueprint.get("/<object_id>/evidence/<evidence_id>")
    def evidence(object_id: str, evidence_id: str):
        connection = connect(database_path)
        try:
            row = connection.execute(
                """SELECT f.source_id, f.source_file, f.row_number, f.sheet_name,
                          f.recorded_at_utc, f.batch_id, e.evidence_id, e.status AS evidence_status,
                          e.normalized_json, e.raw_json, e.diagnostics_json
                   FROM engine_v2_source_facts f
                   JOIN engine_v2_evidence e ON e.evidence_id = f.evidence_id
                   WHERE f.object_id = ? AND e.evidence_id = ?""",
                (object_id, evidence_id),
            ).fetchone()
            if row is None:
                abort(404)
            item = dict(row)
            object_version = connection.execute(
                "SELECT object_template_version_id FROM engine_v2_objects WHERE object_id = ?",
                (object_id,),
            ).fetchone()
            source_labels = _source_labels(
                connection, object_version["object_template_version_id"] if object_version else None
            )
            item["source_label"] = source_labels.get(
                item["source_id"], str(item["source_id"]).replace("_", " ").title()
            )
            status = str(item.get("evidence_status", "")).upper()
            item["evidence_status_label"] = {
                "STAGED": "Captured",
                "QUARANTINED": "Needs review",
            }.get(status, status.replace("_", " ").title() or "Recorded")
        finally:
            connection.close()
        for field in ("normalized_json", "raw_json", "diagnostics_json"):
            try:
                item[field.removesuffix("_json")] = json.loads(item[field])
            except (TypeError, ValueError):
                item[field.removesuffix("_json")] = [] if field == "diagnostics_json" else {}
        return render_template("objects/_evidence_content.html", item=item)

    @blueprint.get("/<object_id>/history")
    def history(object_id: str):
        source_filter = request.args.get("source", "ALL").strip()
        search = request.args.get("q", "").strip()
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1
        connection = connect(database_path)
        try:
            obj = connection.execute(
                "SELECT object_id, status, created_at_utc FROM engine_v2_objects WHERE object_id = ?", (object_id,),
            ).fetchone()
            if obj is None:
                abort(404)
            sources = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT source_id FROM engine_v2_source_facts WHERE object_id = ? ORDER BY source_id", (object_id,),
            ).fetchall()]
            conditions = ["f.object_id = ?"]
            params: list[object] = [object_id]
            if source_filter != "ALL":
                conditions.append("f.source_id = ?")
                params.append(source_filter)
            if search:
                pattern = f"%{search}%"
                conditions.append("(f.source_file LIKE ? OR e.normalized_json LIKE ? OR e.raw_json LIKE ? OR e.diagnostics_json LIKE ?)")
                params.extend([pattern] * 4)
            where_sql = " AND ".join(conditions)
            total_rows = int(connection.execute(
                f"SELECT COUNT(*) FROM engine_v2_source_facts f JOIN engine_v2_evidence e ON e.evidence_id = f.evidence_id WHERE {where_sql}",
                params,
            ).fetchone()[0])
            page_count = max(1, math.ceil(total_rows / HISTORY_PAGE_SIZE))
            page = min(requested_page, page_count)
            rows = [dict(row) for row in connection.execute(
                f"""SELECT f.source_id, f.source_file, f.row_number, f.sheet_name,
                           f.recorded_at_utc, f.batch_id, e.evidence_id, e.status AS evidence_status
                    FROM engine_v2_source_facts f
                    JOIN engine_v2_evidence e ON e.evidence_id = f.evidence_id
                    WHERE {where_sql}
                    ORDER BY f.recorded_at_utc DESC, f.row_number DESC
                    LIMIT ? OFFSET ?""", [*params, HISTORY_PAGE_SIZE, (page - 1) * HISTORY_PAGE_SIZE],
            ).fetchall()]
            for item in rows:
                item["source_filename"] = _source_filename(item.get("source_file"))
        finally:
            connection.close()
        history_context = dict(
            object_record=dict(obj), rows=rows, sources=sources,
            source_filter=source_filter, search=search, total_rows=total_rows,
            page=page, page_count=page_count, page_size=HISTORY_PAGE_SIZE,
        )
        if request.headers.get("HX-Request") == "true":
            return render_template("objects/_history_results.html", **history_context)
        return render_template(
            "objects/history.html", **history_context,
        )

    return blueprint
