# Duplicate Profile Export Report

**Status:** Completed — engineering scope; stakeholder validation pending
**Priority:** 1  
**Owner:** Miguel Fernandez  
**Target:** 2026-09-04  
**Estimate:** 12 hours  
**Planned branch:** `feature/duplicate-profile-report`

## Objective

Provide an exportable report that gives IAM and stakeholders enough evidence to review and resolve duplicate worker profiles.

## Scope

- Review `report_service.py`, `report_routes.py`, `templates/reports/duplicates.html` and report tests.
- Consolidate duplicate candidates and their source evidence.
- Use the existing export convention where possible; otherwise provide the approved CSV/XLSX format.
- Include date, source, identifiers, duplicate status, conflict indicators and recommendation.

## Dependencies

- Approved duplicate-detection rules and report columns.
- Canonical worker identifiers and source-lineage fields.
- Existing worker-history and duplicate-merge evidence.

## Tasks

- Confirm duplicate grouping and recommendation rules.
- Implement the consolidated query and administrative view.
- Add export generation and stable column ordering.
- Include source references and unresolved conflicts.
- Add fixture-based report tests and permission checks.

## Acceptance criteria

- Authorized users can view and download the duplicate report.
- Each row contains sufficient identifiers and evidence for a merge decision.
- The report distinguishes candidate, reviewed, merged and unresolved states.
- Exported data matches the filtered on-screen result.
- Report generation is auditable and does not modify worker records.

## Test cases

- Single duplicate pair and multi-record duplicate cluster.
- Conflicting identifiers or incomplete source data.
- Reviewed, merged and unresolved records.
- Empty result and large result set.
- Unauthorized access and CSV/XLSX content validation.

## Risks and decisions pending

- Incorrect duplicate rules can create unsafe merge recommendations.
- Final columns and format require stakeholder approval.

## Engineering closure — 2026-08-27

- Implemented authenticated duplicate index and review flow with explicit survivor selection, mandatory reason, transactional merge, audit event and superseded-worker history.
- Implemented the consolidated read-only duplicate report with stable columns and matching web, CSV and XLSX output.
- Verified duplicate groups, source evidence, conflict indicators, recommendation rows and authorization behavior.
- Focused verification passed: **18 tests** in `tests/test_worker_history.py` and `tests/test_report_service.py`.
- The report is ready for stakeholder review. Final closure depends on approval of duplicate rules, columns and export format; no stakeholder approval is inferred by this technical closure.
