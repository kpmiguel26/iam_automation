# DEPRECATED marker inventory

**Reviewed:** October 27, 2026
**Scope:** `DEPRECATED` markers in application code and schema definitions, plus
related migration-policy documentation. Line numbers refer to the current
`feature/ingestion-engine-batch-lifecycle` checkout and can shift as files
change.

This inventory records migration intent; it does not mean the listed code is
disabled or safe to remove. Unless a row says otherwise, callers remain active.

## Application and schema markers

| File and line | Marked component | Meaning and current status |
|---|---|---|
| [`iam_automation/application/file_watch_service.py:298`](../../iam_automation/application/file_watch_service.py#L298) | `FileWatchService._discover_files` source-report roots | **DEPRECATED / DISABLED.** The Roster Lock, Master Roster, RSR and AccessNow roots are retained in comments between `BEGIN` / `END` markers because runtime v2 owns discovery under approved Object Template watched folders. Only these four source-report roots are disabled. Request, configuration, snapshot and approval scans remain active because the legacy watcher still has these operational responsibilities. |
| [`iam_automation/application/parallel_engine/rules.py`](../../iam_automation/application/parallel_engine/rules.py) | V2 advisory Rules Engine adapter | Additive adapter reads active current `RECORD_CONDITION` versions from the existing rule catalog and writes matches to `engine_v2_rule_findings` with v2 lineage. Source-scoped rules use the explicit source-system mapping in approved report-template definitions. It does not call the legacy batch execution service or write legacy findings/quarantine. Composite/cross-source evaluation, finding disposition and parity remain pending; the current deployment requires explicit administrator authorization per file. |
| [`iam_automation/application/parallel_engine/engine.py:443`](../../iam_automation/application/parallel_engine/engine.py#L443) | Legacy evidence-JSON lookup in `_find_object` | **DEPRECATED compatibility fallback; still active.** Schema v6 stores Strong Identifier claims in `engine_v2_strong_identifiers`; matching combines indexed claims with the JSON fallback so prototype evidence without physical identifier rows can still match and conflicting candidates remain visible. Remove the fallback only after conflict-safe backfill and parity checks. |
| [`iam_automation/application/ingestion/orchestrator.py:24`](../../iam_automation/application/ingestion/orchestrator.py#L24) | `IngestionOrchestrator` source selection | Runtime v2 recognizes files using approved report-template snapshots. The legacy facade still dispatches imports to source adapters and runs legacy Rules Engine hooks; keep it active pending physical writes, rule parity and cutover. |
| [`iam_automation/application/master_roster_ingestion_service.py:54`](../../iam_automation/application/master_roster_ingestion_service.py#L54) | Master Roster `ingest_file` persistence | Inline batch, quarantine and fact persistence is a migration target for the generic batch service / future v2 coordinator. Reader, normalization and result contract remain active. |
| [`iam_automation/application/accessnow_ingestion_service.py:73`](../../iam_automation/application/accessnow_ingestion_service.py#L73) | AccessNow `ingest_folder` persistence | Inline batch persistence is a migration target. Multi-file merge, AccessNow policy, reconciliation and result contract remain active pending parity. |
| [`iam_automation/source_adapters/rsr_supplier_worker_details.py:97`](../../iam_automation/source_adapters/rsr_supplier_worker_details.py#L97) | RSR `ingest_file` persistence | Inline batch persistence is a migration target. Reader, source policy, matching/apply facade and result contract remain active pending RSR parity. |
| [`iam_automation/application/source_reconciliation.py:58`](../../iam_automation/application/source_reconciliation.py#L58) | `find_worker_matches` | Employee-specific canonical matching is a replacement target for executable Object Template relationships. Still active for canonical Employees; v2 matching is isolated to prototype objects. |
| [`iam_automation/application/accessnow_ingestion_service.py:194`](../../iam_automation/application/accessnow_ingestion_service.py#L194) | AccessNow `_find_match_detail` | Source-specific canonical Employee resolver is a replacement target. Still active until the Template Object resolver is executable and parity is demonstrated. |
| [`iam_automation/source_adapters/rsr_supplier_worker_details.py:144`](../../iam_automation/source_adapters/rsr_supplier_worker_details.py#L144) | RSR `match_batch` | RSR matching is a replacement target for configured cross-report relationships. Keep current result contract until runtime matching and source parity exist. |
| [`iam_automation/application/ingestion/configuration_contracts.py:119`](../../iam_automation/application/ingestion/configuration_contracts.py#L119) | `DraftFieldMapping` | Compatibility contract for pre-library field mappings. New drafts use `DraftFieldDefinition`; retain the old shape to read existing session/snapshot payloads. |
| [`iam_automation/application/ingestion/configuration_contracts.py:188`](../../iam_automation/application/ingestion/configuration_contracts.py#L188) | `DraftSourceDefinition.mappings` | Deprecated compatibility field; the current field editor does not emit it. Retained for old payloads. |
| [`iam_automation/application/ingestion/configuration_service.py:210`](../../iam_automation/application/ingestion/configuration_service.py#L210) | Legacy mapping fallback in draft normalization | Old drafts may still override field key/cleanup with `DraftFieldMapping`. New drafts store these on the source field; retain fallback while older snapshots exist. |
| [`iam_automation/interfaces/web/ingestion_configuration_routes.py:1108`](../../iam_automation/interfaces/web/ingestion_configuration_routes.py#L1108) | Legacy mapping form fields | Compatibility for old form posts. The current schema editor has no canonical mapping controls; preserve the versioned field-key contract. |
| [`iam_automation/database/runtime_schema.py:263`](../../iam_automation/database/runtime_schema.py#L263) | SQLite `template_mappings` table | Compatibility schema retained for old databases and callers. New template configuration is versioned in `source_definition_versions`; do not drop the table in this migration. |
| [`iam_automation/database/schema.py:36`](../../iam_automation/database/schema.py#L36), [`:60`](../../iam_automation/database/schema.py#L60) | Access `tbl_TemplateMappings` table | Legacy Access compatibility table retained for existing installations; versioned report-template snapshots are the new configuration path. |

## Related migration policy and documentation

These are policy or explanatory references, rather than additional runtime
components marked for migration:

| File and line(s) | Why it is relevant |
|---|---|
| [`AGENTS.md:65`](../../AGENTS.md#L65), [`:68`](../../AGENTS.md#L68), [`:72`](../../AGENTS.md#L72), [`:74`](../../AGENTS.md#L74), [`:79`](../../AGENTS.md#L79) | Repository rules for adding, retaining and testing deprecated compatibility paths. |
| [`docs/ingestion-engine/README.md:27`](README.md#L27), [`:30`](README.md#L30) | High-level status: legacy paths remain active; the marker does not disable them. |
| [`docs/ingestion-engine/CONFIGURATION_UI_DESIGN.md:105`](CONFIGURATION_UI_DESIGN.md#L105), [`:112`](CONFIGURATION_UI_DESIGN.md#L112), [`:113`](CONFIGURATION_UI_DESIGN.md#L113), [`:116`](CONFIGURATION_UI_DESIGN.md#L116) | Detailed runtime overlap and deprecation register. |
| [`docs/work/2026-09-22-ingestion-engine-work-plan.md:68`](../work/2026-09-22-ingestion-engine-work-plan.md#L68), [`:73`](../work/2026-09-22-ingestion-engine-work-plan.md#L73), [`:194`](../work/2026-09-22-ingestion-engine-work-plan.md#L194), [`:230`](../work/2026-09-22-ingestion-engine-work-plan.md#L230) | Earlier migration plan describing preservation of compatibility paths and adapters. |
| [`docs/quarantine-rules/WORK_PLAN_2026-09-18_RULE_ENGINE_REFACTOR.md:32`](../quarantine-rules/WORK_PLAN_2026-09-18_RULE_ENGINE_REFACTOR.md#L32), [`docs/STATUS.md:41`](../STATUS.md#L41), [`docs/architecture/INGESTION_ENGINE_ARCHITECTURE.md:833`](../architecture/INGESTION_ENGINE_ARCHITECTURE.md#L833), [`docs/architecture/INGESTION_ARCHITECTURE.md:101`](../architecture/INGESTION_ARCHITECTURE.md#L101) | Other documentation references to retired/deprecated compatibility components and future cleanup. |
| [`docs/archive/deprecated/README.md:1`](../archive/deprecated/README.md#L1), [`docs/archive/deprecated/REHIRE_ALERT_SERVICE.md:1`](../archive/deprecated/REHIRE_ALERT_SERVICE.md#L1) | Archived rehire alert service; separate from the parallel ingestion migration. |

This inventory file is itself an audit document and is not an additional
deprecated runtime component.

## Removal gates

Before removing any marked path, confirm its callers have migrated, preserve
the compatibility contract required by old databases/snapshots, and verify
the relevant source-specific behavior. In particular, keep legacy import,
canonical Employee matching, Rules Engine hooks and application approval flows
until runtime v2 meets the import-readiness acceptance criteria in
[`2026-09-30_IMPORT_READINESS_AND_PLAN.md`](2026-09-30_IMPORT_READINESS_AND_PLAN.md).
