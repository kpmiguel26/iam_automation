# Tomorrow's Work: Incremental Business Rule Engine Refactor

Work date: 2026-09-18

## Objective

Organize the Business Rules subsystem without performing a functional rewrite or breaking existing imports, web routes, tests, or persisted data.

The main business invariant remains:

> Rules are advisory-only. They may generate results, findings, notifications, audit evidence, and review projections, but they must never block or undo an import.

## Current state

The largest concentration point is application/business_rule_service.py. It currently mixes:

- Rule CRUD and configuration.
- Condition JSON construction and validation.
- Condition evaluation.
- Source-specific reading for Roster Lock, Master Roster, RSR/Fieldglass, and AccessNow.
- Direct SQLAlchemy/SQLite access.
- Finding and quarantine creation.
- Queries, summaries, and UI data.

Main files inspected:

- application/business_rule_service.py
- application/condition_evaluator.py
- application/rules/base.py
- application/rules/registry.py
- application/rules/configured_business_rules.py
- application/rule_configuration_service.py
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
- evidence.py: source-specific evidence retrieval.
- pipeline.py: BEFORE/AFTER lifecycle integration.

Keep application/business_rule_service.py as a compatibility facade for existing routes, services, and tests.

### Phase 4: extract source evidence

Introduce only the minimum abstraction required, for example:

~~~
class SourceEvidenceProvider(Protocol):
    def rows_for_file(self, source_system: str, path: Path) -> list[dict]:
        ...
~~~

This boundary should hide reading for:

- Roster Lock.
- Master Roster.
- RSR/Supplier Worker Details.
- AccessNow.

Do not build a new generic ingestion framework as part of this work.

### Phase 5: SQLite repositories

Extract only the boundaries that provide value:

- rule_repository.py: rules, versions, and persisted configuration.
- finding_repository.py: findings and their statuses.

Do not change:

- Tables.
- Migrations.
- Column names.
- Persisted JSON formats.

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
