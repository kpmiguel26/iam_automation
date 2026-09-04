# Gaps, Risks and Decisions

## Highest-priority gaps

1. **Official source formats:** approve Fieldglass, Roster Lock and future Staffing Plan mappings.
2. **Canonical identity:** approve the identifier used to match a person across vendors and systems.
3. **Source precedence:** define the owner of each field when Roster Lock, Fieldglass and other systems disagree.
4. **Business validations:** define rehire, blacklist, active worker, dates, NPN and submission deadline rules.
5. **Import approval:** confirm whether bulk import approval is sufficient for matched records and how unmatched records are resolved.
6. **Publication responsibility:** confirm whether Application Admin can publish runtime SQLite or whether publication remains Master Admin-only.
7. **Downstream scope:** confirm MVP versus future scope for Salesforce, CXOne, NICE IEX, AccessNow and ServiceNow.
8. **Notification channels:** confirm whether in-app notifications are enough or whether email/Teams integration is required.

## Technical risks


### Cross-workstation behavior

The JSON-first SharePoint connector avoids direct multi-user writes to SQLite, but concurrent file sync, stale local snapshots and publication conflicts still require Windows/macOS integration testing.

### Source quality

The current RSR workbook contains non-worker footer/date rows. Quarantine is protecting the canonical data, but the adapter needs approved row-boundary rules before production use.

### Release packaging

The portable ZIP workflow exists, but Windows validation still encountered path-length and package-installation issues. A clean short-path package must be tested before handoff.

## Decisions requested in the meeting

- Approve the Worker/Employee separation and source-lineage model.
- Confirm that Roster Lock is the onboarding intake source and Fieldglass/RSR is the historical enrichment source.
- Confirm how unmatched Fieldglass workers are approved and promoted.
- Confirm final admin publication permissions.
- Approve the first official Fieldglass mapping owner and sample.
- Approve the minimum business validation rules for QA.
- Confirm the target acceptance gate for moving from QA to pilot.
