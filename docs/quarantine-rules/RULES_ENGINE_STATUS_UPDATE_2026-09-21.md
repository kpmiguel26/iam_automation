# Weekly Rules Engine and Application Modernization Update

**Reporting date:** September 21, 2026  
**Prepared for:** Weekly written project update  
**Prepared by:** Miguel Alejandro Fernandez Arteaga  
**Program phase:** Phase 1 — Read-only Employee and Evidence Review

## Executive summary

Work continues on the transition from the original MVP design to a more
flexible and sustainable application. The rules engine is no longer dependent
on one specific business scenario or report format. It can now support
configurable review criteria, different data sources, calendar settings and
versioned rule definitions.

The application also has a dedicated Business Rules area where authorized
users can create draft rules, test them, activate approved rules and review
the resulting items in Quarantine. This gives the team a controlled way to
review data quality and business exceptions without changing authoritative
employee records.

The overall initiative is **in progress**. The core foundation is in place;
the remaining work is focused on completing the user documentation, expanding
the configuration experience, strengthening auditability and validating the
solution with representative business data.

## Progress against the requested initiatives

### 1. Making the application more flexible and application agnostic

**Status: In progress — foundation completed.**

The rules engine can now evaluate general business conditions instead of
depending on a single hard-coded rule. This means that future rules can be
created for different reports, sources and business situations without
building a new piece of application logic for every rule.

The current design supports:

- Different source reports and governed fields.
- Reusable review criteria such as missing values, matching values, ranges and
  date comparisons.
- Multiple conditions within one business rule.
- Operating calendars, holidays and time-zone settings.
- Draft, test, active and review states.

This is an important step toward allowing the application to grow as new
reports and business requirements are introduced.

### 2. Separating the application components

**Status: Completed for the rules-engine workstream.**

The rules functionality has been separated into clear areas for:

- Rule definitions and versions.
- Rule configuration.
- Rule execution.
- Business-condition evaluation.
- Evidence and findings.
- Calendar and time settings.
- Data access and repositories.

This structure makes the application easier to maintain and gives future
developers a clearer path for adding or changing functionality. Existing
compatibility paths and the broader ITSM, approval, notification and audit
surfaces remain in place.

### 3. Documenting the rules and supporting users

**Status: In progress.**

A working [Quarantine Rules Catalog](./RULES_CATALOG.md) is available. It
documents the current naming convention, source selection, rule timing,
recommended starter rules, testing steps and activation process.

The documentation still needs to be expanded into a formal administrator SOP
and user-friendly reference guide. These materials will explain how to create,
test, activate and review rules using business language, with practical
examples and troubleshooting guidance.

### 4. Maintaining the Phase 1 operating boundary

**Status: Confirmed and preserved.**

Rules continue to be advisory during Phase 1. A rule finding is an item for
human review; it does not stop an import, change an employee record, correct
source data, approve a change or publish information to an authoritative
system. Any future corrective-action workflow remains outside the current
phase.

## Business status overview

| Workstream | Status | Business interpretation |
|---|---|---|
| Configurable business rules | In progress | The application can support reusable rules; additional business examples and validation are needed. |
| Application and ingestion flexibility | In progress | The foundation supports multiple sources, with further source mappings and representative files still required. |
| Code separation and maintainability | Completed for rules workstream | Rules, configuration, execution, evidence and calendar responsibilities are separated. |
| Quarantine review | Implemented | Reviewers can see affected records, source details, severity and supporting evidence. |
| Rule testing and activation | Implemented | Rules can remain in draft while they are tested before activation. |
| Calendar and time-zone handling | Implemented with follow-up | Settings are available; historical reproducibility needs one additional version-control improvement. |
| Rule-language documentation and SOP | In progress | A catalog exists; the formal training and operating package remains to be completed. |
| Export column improvements | Separate workstream | This item is not being represented as completed by the rules-engine work. |
| Dedicated reporting engine | Future evaluation | CSV and Excel exports remain the interim reporting approach. |
| AccessNow historical retention | Decision pending | The retention period still requires business confirmation. |

## Current business value

The work completed so far provides the following benefits:

- Reduces the need for custom development for every new review rule.
- Creates a consistent place for users to review exceptions.
- Preserves the source, batch and record context needed to investigate a
  finding.
- Allows a rule to be tested before it is put into active use.
- Supports future growth across multiple reports and source systems.
- Maintains a clear separation between review activity and authoritative data
  changes.

## Items requiring continued attention

The following items remain open before the rules capability should be
considered fully operational:

1. **Complete the user experience.** The internal rules capability is currently
   more flexible than the guided screen. The screen needs to expose the full
   range of supported business scenarios in a simple, business-friendly way.

2. **Strengthen historical traceability.** Complex findings should retain
   enough context to explain how the conclusion was reached, including the
   exact calendar version used for a historical evaluation.

3. **Validate with representative business data.** Additional testing is
   needed with linked records from Roster Lock, Master Roster and AccessNow,
   including the proposed 30-day rehire review scenario.

4. **Complete operating documentation.** The SOP, rule-language guide,
   troubleshooting content and training examples are still required for a
   successful handoff to administrators and reviewers.

5. **Confirm related business decisions.** Export formatting, reporting needs
   and historical retention must be reviewed separately with the appropriate
   stakeholders.

## Next steps

For the next work period, the planned priorities are:

- Finalize the plain-language rule definitions and examples.
- Expand testing across the supported business conditions and source types.
- Improve the guided rule-creation experience.
- Confirm exact calendar-version handling for historical findings.
- Complete an end-to-end validation using representative source batches.
- Draft the administrator SOP and user training material.
- Review the separate export, reporting and retention decisions with business
  stakeholders.


## Technical validation record

The status above is based on a review of the rules-engine implementation,
administration routes, Quarantine templates, current work tracking and the
existing rules catalog.

Focused verification completed successfully:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_rule_configuration.py tests/test_pipeline_rules.py tests/test_domain_rule_evaluator.py tests/test_condition_evaluator.py tests/test_rules_ingestion_boundary.py
25 passed in 5.96s
```