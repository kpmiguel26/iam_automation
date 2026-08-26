# Duplicate Profile Export Report

**Status:** In Progress
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
