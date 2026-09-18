# Today's Work: Incremental Business Rule Engine Refactor

Work date: 2026-09-18

## Status

- [x] Extracted the pure condition evaluator to `iam_automation/domain/rules`.
- [x] Extracted pure calendar settings and business-day calculation primitives.
- [x] Kept `application/condition_evaluator.py` as a compatibility facade for
  existing routes, services and persisted rule behavior.
- [x] Added domain-only evaluator tests covering simple, compound, derived and
  malformed conditions.
- [x] Extracted application execution orchestration to
  `iam_automation/application/rules/execution.py` for previews, BEFORE/AFTER
  evaluation, batch processing and advisory finding persistence.
- [x] Kept `BusinessRuleService` as the compatibility facade used by existing
  routes, pipeline rules and tests.
- [x] Removed inferred calendar/environment fallbacks. Missing or invalid
  calendar configuration now raises an actionable configuration error.
- [x] Made operating weekdays, date-boundary behavior and interval inclusion
  explicit inputs to the pure business-day calculator; they are loaded from
  the versioned calendar/context and are no longer code defaults.
- [x] Removed form and ORM-level runtime defaults for timezone, weekdays and
  date boundaries so incomplete decisions are surfaced for configuration.
- [x] Preserved the Phase One advisory boundary: missing calendar configuration
  is reported to the user/pipeline and never blocks or undoes an import.
- [x] Full regression suite: **234 passed, 1 skipped**.
- [x] Retired the legacy `RehireAlertService` runtime path. Rehire detection,
  notifications and archive actions are no longer executed by the watcher,
  employee services or web routes.
- [x] Preserved the retired implementation as future-reference documentation
  in [`deprecated rehire alert service`](../archive/deprecated/REHIRE_ALERT_SERVICE.md).
- [x] Removed legacy rehire-alert tests and notification behavior; any future
  rehire policy must be created as a user-owned Business Rule.
- [x] Regression suite after retirement: **229 passed, 1 skipped**.
- [x] Removed unreachable legacy orchestration bodies from
  `application/business_rule_service.py`; BEFORE row preparation now lives with
  the execution orchestrator instead of the compatibility facade.
- [x] Focused execution regression: **58 passed, 1 skipped**; full regression:
  **229 passed, 1 skipped**.
- [x] Removed source-file parsing from rule execution. `BEFORE` now queries the
  staged `ingestion_records` and relational source facts by `batch_id`, leaving
  file formats, report readers and adapter selection to the ingestion layer.
- [x] Updated the pipeline contract, administration copy and architecture docs
  to describe `BEFORE` as staged-database evaluation before the `AFTER` phase.
- [x] Added the source-neutral `EvidenceRepository` contract. Rule execution
  now consumes `NormalizedRecord` values reconstructed from generic ingestion
  and star-schema tables, with no source adapter imports.
- [x] Moved the rule source/field catalog to `dim_source`, `dim_field` and
  `source_field_mapping`; migration `0022_source_rule_catalog` seeds the
  current configuration and ingestion persists mappings for new normalized
  fields.
- [x] Updated migration and legacy-runtime tests for the governed catalog;
  full regression suite: **229 passed, 1 skipped**.
- [x] Moved the Rules service and rule-context configuration implementation
  into `application/rules/`, while retaining compatibility facades at their
  former application paths.
- [x] Full regression after the package move: **232 passed, 1 skipped**.
- [x] Extracted rule-definition persistence into
  `application/rules/repositories/rule_repository.py`; the application
  service remains responsible for configuration, orchestration and
  presentation behavior.

Next implementation step: introduce an explicit staging-to-promotion boundary
in the ingestion engine. The current adapters already persist normalized
evidence before rules run, but still own their completion markers and source
fact writes; promotion must become a separate generic lifecycle operation
before `BEFORE` is allowed to influence future ingestion behavior.

## Objective

Organize the Business Rules subsystem without performing a functional rewrite or breaking existing imports, web routes, tests, or persisted data.

The main business invariant remains:

> Rules are advisory-only. They may generate results, findings, notifications, audit evidence, and review projections, but they must never block or undo an import.

## Current state

The largest concentration point was application/business_rule_service.py. Its
implementation now lives in application/rules/service.py; the old module is a
compatibility facade. The service still contains these responsibilities while
the next extraction is planned:

- Rule CRUD and configuration.
- Condition JSON construction and validation.
- Condition evaluation.
- Compatibility access to source-specific ingestion remains outside the rules
  package; the rule engine consumes only staged evidence.
- Direct SQLAlchemy/SQLite access.
- Finding and quarantine creation.
- Queries, summaries, and UI data.

Main files inspected:

- application/rules/service.py
- application/business_rule_service.py (compatibility facade)
- application/condition_evaluator.py
- application/rules/base.py
- application/rules/registry.py
- application/rules/configured_business_rules.py
- application/rules/configuration.py
- application/rule_configuration_service.py (compatibility facade)
- application/ingestion/orchestrator.py
- infrastructure/sqlite/orm.py
- interfaces/web/admin_routes.py
- templates/admin/business_rules.html

Current subsystem baseline:

~~~
28 passed
~~~

Tests executed:

~~~
tests/test_business_rule_service.py
tests/test_rule_configuration.py
tests/test_pipeline_rules.py
~~~

## Target architecture

Use a modular monolith organized by responsibility, without a full rewrite:

~~~
iam_automation/
├── domain/
│   └── rules/
│       ├── evaluator.py
│       ├── models.py
│       ├── conditions.py
│       └── calendar.py
│
├── application/
│   └── rules/
│       ├── service.py
│       ├── configuration.py
│       ├── execution.py
│       ├── evidence.py
│       ├── catalog.py
│       └── pipeline.py
│
├── infrastructure/
│   └── sqlite/
│       └── repositories/
│           ├── rule_repository.py
│           └── finding_repository.py
│
└── interfaces/
    └── web/
        └── admin_routes.py
~~~

Do not create empty files merely to satisfy the tree. Every move must have a real responsibility and tests that justify it.

## Incremental plan

### Phase 1: characterization and protection

- Keep the existing tests with minimal changes.
- Add pure evaluator tests where coverage is missing.
- Explicitly confirm that a matching rule does not block ingestion.
- Confirm that the condition JSON and operator semantics do not change.

### Phase 2: extract the pure evaluator

Gradually move the logic from application/condition_evaluator.py to domain/rules/evaluator.py.

The domain evaluator must accept:

~~~
condition + evaluation context
~~~

and return an evaluation result with trace information.

It must preserve:

- all
- any
- not
- Legacy field/operator/value shape.
- field, literal, and derived operands.
- Existing operators.
- Date comparisons.
- business_days_between.
- Invalid-condition validation.

The new domain layer must not import SQLAlchemy, SQLite, ORM, Flask, routes, templates, or source adapters.

During the transition, keep application/condition_evaluator.py as a compatibility facade that re-exports the new evaluator.

### Phase 3: separate application rule orchestration

Split the responsibilities of BusinessRuleService into small modules, only where the size and dependencies justify it:

- service.py: facade and coordination.
- configuration.py: rules, versions, calendars, and metadata.
- execution.py: batch evaluation and finding generation.
- queries.py: listings, summaries, and review queries.
- evidence.py: source-neutral staged evidence retrieval.
- catalog.py: database-backed source and field catalog.
- pipeline.py: BEFORE/AFTER lifecycle integration.

Keep application/business_rule_service.py as a compatibility facade for existing routes, services, and tests.

### Phase 4: extract source evidence

Completed with the narrower, safer boundary required by the pipeline:

~~~
class EvidenceRepository(Protocol):
    def batch_for_id(self, session, batch_id: str) -> IngestionBatch | None:
        ...
~~~

The repository reconstructs normalized values from generic staging and source
fact tables. File readers and normalizers remain owned by ingestion adapters;
the rules engine does not receive or interpret report paths.

### Phase 5: SQLite repositories and catalogs

Extract only the boundaries that provide value:

- rule_repository.py: rules, versions, and persisted configuration.
- finding_repository.py: findings and their statuses.

The source/field catalog is now DB-backed through `RuleCatalogRepository` and
the `0022_source_rule_catalog` migration. Adding a governed source or field
should be a data/configuration change plus an ingestion mapping, not a change
to rule evaluation code.

### Contract stabilization checkpoint

- [x] Phase A — stabilize `dim_source`, `dim_field`,
  `source_field_mapping`, `import_batches` and `ingestion_records` as the
  persistence backing for the hand-off.
- [x] Phase B — make the Rules Engine consume `IngestionBatch` and
  `NormalizedRecord` without file readers, report names, file paths or adapter
  imports. The pipeline `RuleContext` now carries batch identity only.
- [x] Close the contract escape hatches: batch/record metadata are typed,
  adapter results are reduced to `batch_id`, and mappings carry `mapping_id`
  and `field_id`.
- [ ] Phase C — implement the future Ingestion Engine for discovery, format
  adapters, mapping UI, normalization and staging. This phase is intentionally
  out of scope for the current refactor.

Compatibility note: new rule versions persist stable `source_id` and
`field_id` values. The legacy source labels and field keys remain alongside
those IDs for display and backward compatibility, while historical versions
still resolve through their legacy values. No new filtering should add more
string-based scope logic; a later, explicitly approved backfill can remove the
legacy keys once external consumers are confirmed.

Do not change:

- Tables.
- Migrations.
- Column names.
- The meaning of existing persisted JSON formats. New versions may add
  catalog identifiers without invalidating historical versions.

Quarantine logic must remain an advisory review projection, not an import rejection mechanism.

### Phase 6: cleanup

- Search callers with rg before deleting files.
- Remove duplication only after confirming that no imports remain.
- Keep legacy facades while external consumers still exist.
- Run the complete test suite after every meaningful move.

## Required tests

Add pure domain tests with no database, filesystem, Flask application, or adapters:

- Simple conditions.
- all/AND.
- any/OR.
- not.
- Field versus literal.
- Field versus field.
- Derived operands.
- Dates and calendars.
- Malformed conditions.
- Existing operator semantics.

Keep integration tests proving that:

1. A matching rule produces an advisory result/finding.
2. The adapter continues running.
3. The import completes normally.
4. A rule failure does not undo the adapter result.

The existing safety test is:

~~~
tests/test_pipeline_rules.py::PipelineRuleTests::test_before_rule_never_blocks_adapter_execution_in_phase_one
~~~

## Refactoring boundaries

- Do not redesign the condition JSON.
- Do not turn advisory rules into blocking rules.
- Do not modify the SQLite schema.
- Do not remove legacy Access code yet.
- Do not perform a repository-wide rename.
- Do not create a generic ingestion framework.
- Do not mix UI changes with domain extraction.

## Recommended first implementation commit

The first implementation commit should contain only:

1. The pure evaluator under domain/rules.
2. The compatibility facade in application/condition_evaluator.py.
3. Unit tests without external dependencies.
4. Existing tests with no functional changes.

After confirming the complete suite, continue with the separation of BusinessRuleService.
