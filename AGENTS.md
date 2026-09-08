# IAM Automation — Project Instructions for Codex

These instructions apply to this repository. Read them together with the active
architecture, operating model, work-tracking documents and the user's request.

## 1. Product boundary: Phase 1 is read-only review

The current delivery phase is **Phase 1 — Read-only Employee & Evidence Review**.
New features must remain read-only with respect to authoritative employee,
vendor and source platforms.

Allowed new capabilities include:

- Viewing, searching, filtering, sorting and paginating synchronized evidence.
- Read-only reconciliation, comparison, history, lineage, discrepancy and duplicate views.
- Advisory business-rule evaluation, findings and quarantine evidence.
- Local staging and ingestion of source files when it follows the existing ingestion contract.
- Read-only CSV/XLSX exports and diagnostic views.

Do not introduce new behavior that:

- Applies, approves, merges, corrects or publishes employee changes to an authoritative platform.
- Sends corrective actions, access changes or ITSM actions to another system.
- Treats a rule finding or quarantine record as an ingestion blocker.
- Mutates canonical employee identity or source facts as a side effect of viewing or evaluating data.
- Adds a write workflow merely because a button or form would be convenient.

If a requested feature requires an authoritative write, treat it as a future-phase
boundary. Explain the conflict and ask for explicit scope approval before implementing it.

### Rule evaluation semantics

- Business rules are advisory and non-blocking in Phase 1.
- `BEFORE` and `AFTER` describe where evaluation occurs in the local ingestion pipeline;
  they do not grant permission to block an import or modify an authoritative system.
- Findings belong in the local quarantine/evidence model and must preserve the rule,
  source, employee, field and batch lineage needed for review.

## 2. Preserve the existing ITSM and workflow surface

The existing ITSM/request, approval, notification, audit and administrative code is
an active compatibility surface. Do not delete, rename, disable, replace or silently
rewrite it while adding new functionality.

- Preserve existing ITSM routes, services, database tables, migrations, templates,
  permissions and user-visible workflows.
- Do not remove legacy compatibility paths just because a newer star-schema or
  read-only screen exists.
- Prefer additive changes, adapters and deprecation notes over breaking migrations.
- If shared code must change, preserve the old contract and add regression coverage.
- Do not erase existing data, audit evidence, request history or source lineage.

This repository may contain transitional legacy readers and writers. Their presence
is intentional until the migration is explicitly completed and validated; do not
clean them up opportunistically.

## 3. Data, database and runtime safety

- Treat Access, published SQLite and source files as versioned evidence/snapshots
  according to the existing architecture; do not invent a new source of truth.
- Preserve source lineage, batch identity, timestamps, identifiers and raw evidence
  needed to explain a result.
- Prefer additive schema migrations. Never drop tables or columns, rewrite history,
  or reset a runtime database unless the user explicitly requests that exact operation.
- Keep append-only source facts and existing compatibility projections intact.
- Do not modify `runtime.sqlite`, WAL/SHM files, watcher manifests, watcher health files
  or publish-pending artifacts as part of ordinary feature work.
- Never commit local runtime state, credentials, generated backups or user data.
- Validate authorization and CSRF protection on every existing or new mutating route.

## 4. Frontend standard: polished, accessible server-rendered UI

Use the existing Flask/Jinja, Bootstrap/CSS and HTMX patterns before introducing a
new frontend framework or component system.

### Interaction rules

- Prefer HTMX requests plus server-rendered partials for tabs, filters, forms,
  status changes, deletes, pagination and other incremental interactions.
- Use explicit `hx-target`, `hx-swap`, loading indicators and useful empty/loading/error states.
- Keep a normal POST/GET fallback when practical so the server remains authoritative
  and the page remains usable without HTMX.
- Never use native browser `alert()`, `confirm()` or `prompt()` for application UI.
- Use the project's custom confirmation/loading UI for destructive or long-running
  actions. Do not add `hx-confirm` if it would fall back to the browser's native dialog.
- Keep HTMX behavior delegated or re-initialized after `htmx:afterSwap`; swapped
  content must not lose its interactions.

### Visual and accessibility rules

- Build a clear hierarchy: page purpose, status/summary, primary action, then details.
- Use human labels in the main UI. Put technical keys, JSON and raw conditions inside
  an optional details/disclosure area rather than making them the primary experience.
- Use semantic headings, labels, table headers, buttons and links; do not use clickable
  `div` elements when a native control is appropriate.
- Support keyboard navigation, visible focus, sensible focus after HTMX swaps,
  `aria-live` for result/status changes and accessible dialog semantics.
- Maintain readable contrast, responsive layouts, useful whitespace and clear visual
  states for active, disabled, draft, warning, error, loading and empty conditions.
- Design tables for real users: concise columns, readable descriptions, responsive
  overflow, human-friendly badges and a deliberate mobile fallback.
- Reuse existing design tokens, CSS classes, spacing, buttons, badges and modal patterns.
  Add a new style only when an existing pattern cannot express the requirement.
- Do not hide important information behind color alone, hover-only behavior or a
  technical identifier.
- Avoid inline JavaScript when a small module under `iam_automation/static/js/` can
  be reused and tested.

### Frontend implementation workflow

1. Inspect the existing route, template, partial, CSS and JavaScript pattern first.
2. Identify the smallest server-rendered partial that can be swapped independently.
3. Implement the accessible full-page state and the HTMX partial/fallback together.
4. Reuse existing loading, confirmation, table and notification components.
5. Verify initial load, HTMX swap, validation error, empty state, permission denial
   and non-JavaScript fallback.
6. Add or update a regression test for the route/contract and perform a visual smoke
   check when a local browser is available.

## 5. Engineering and change discipline

- Inspect before editing. Preserve unrelated user changes and runtime artifacts.
- Make the smallest coherent change; avoid opportunistic refactors.
- Keep business logic in application/services, route handlers thin and templates
  focused on presentation.
- Prefer explicit contracts and typed/domain values over duplicated string literals.
- Do not hard-code report columns when the governed field catalog can describe them.
- Keep migrations, adapters, rule definitions and compatibility fallbacks explainable.
- Update relevant documentation when behavior or a phase boundary changes.

## 6. Verification checklist

Before handing off a change:

- Run `git diff --check` and inspect the final diff.
- Run the focused tests for the affected route/service.
- Run the full suite with `.venv\Scripts\python.exe -m pytest -q` when practical.
- Check that no new native browser dialogs or authoritative writes were introduced.
- Confirm that existing ITSM/request/approval/audit behavior and compatibility paths
  remain present.
- Report any tests not run and any remaining scope or data-risk clearly.

Do not commit, push, reset, delete data or alter branches unless the user explicitly
requests that repository operation.
