# Validation, Salesforce, Retention and Technical Handoff

**Status:** Backlog  
**Priority:** 1–2  
**Owners:** Miguel Fernandez, IAM Team, Salesforce Team, Sofia Moya  
**Targets:** 2026-09-04 for Salesforce validation; 2026-09-11 for retention tests and handoff  
**Estimate:** 14 hours combined testing (8 hours history/retention + 6 hours Salesforce/Data Loader) + 3 hours SOP/handoff  
**Planned branch:** `chore/september-validation-handoff`

## Objective

Validate the implemented IAM flows against approved Salesforce/Data Loader formats, confirm history and retention behavior, and package operational evidence for handoff.

## Scope

- Execute the approved Salesforce export template through a controlled Data Loader validation.
- Confirm columns, values, permissions and download/load behavior with Salesforce Team.
- Test rehire, merge, retention, archive, backup, recovery and regression scenarios.
- Provide Sofia with technical steps, preconditions, evidence expectations, recovery instructions and support limits.

## Dependencies and operational items

- Salesforce confirms final workbook/template, access and Data Loader process.
- Sofia confirms the five-day inactivity report and its format.
- Amanda owns the Report Studio roster-lock consolidation test; IAM supports data or defects if needed.
- Sophie receives duplicate-roster evidence for the biweekly meeting when requested.
- Vendor communication/access remains delayed as an operational control until the flow stabilizes.

## Tasks

- Validate Salesforce mapping against the approved template and record discrepancies.
- Run controlled export/download/load checks without bypassing publication controls.
- Build and execute a matrix for merge, rehire, retention, archive, backup and regression.
- Record defects, decisions, owners and evidence links.
- Update the Salesforce guide and prepare the SOP/handoff package.

## Acceptance criteria

- Salesforce Team accepts the tested template, mapping and Data Loader steps, or all blockers have owners and next actions.
- History and retention tests show required snapshots, aliases and audit evidence are preserved.
- Backup/recovery and regression results are recorded.
- SOP includes prerequisites, responsible roles, expected evidence, recovery and support boundaries.
- Open defects and stakeholder decisions are visible in the backlog before closure.

## Test cases

- Approved Salesforce export with valid and invalid values.
- Download and controlled Data Loader validation.
- Rehire, duplicate merge, retention and archive scenarios.
- Backup, restore/recovery and checksum verification.
- Full regression and permission checks for affected routes.

## Risks and decisions pending

- A late Salesforce template change can affect mappings and estimates.
- Missing administrative access blocks end-to-end validation.
- Retention, legal hold or export-evidence requirements may expand scope.
