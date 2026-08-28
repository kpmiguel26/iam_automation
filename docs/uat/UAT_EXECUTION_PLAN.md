# UAT Execution Plan — IAM Automation Phase 1

## Executive summary

IAM Automation Phase 1 is accepted in this package as a read-only identity reconciliation and audit product. It detects, classifies, preserves, and explains evidence. Humans decide; authoritative source platforms execute.

| Measure | Result |
|---|---:|
| Phase 1 Core rules | 34 |
| Phase 1 Platform rules | 8 |
| Phase 2 Writer rules | 5 |
| Future Integration rules | 4 |
| Out-of-scope rules | 1 |
| Phase 1 UAT scenarios ready | 9 |
| Phase 1 scenarios blocked by business decisions | 20 |
| Phase 1 scenarios blocked technically | 3 |
| Phase 1 scenarios not implemented | 1 |
| Phase 2 scenarios deferred | 2 |
| Future-integration scenarios deferred | 2 |
| Business questions remaining | 48 |
| Questions in next-meeting agenda | 10 |

The scenario counts are based on the scope matrix in `UAT_TEST_SCENARIOS.md`; deferred Phase2/Future scenarios do not block Phase 1 sign-off. The three technical blockers include two scenarios marked “Blocked by technical dependency” and one Phase 1 capability marked “Not implemented.” Some scenarios may be technically runnable while their expected finding interpretation remains a business decision.

## Previously identified blockers that disappeared after the scope clarification

- “Is Phase 1 read-only?” is no longer an open business question. It is an approved scope decision and a technical acceptance gate.
- Promotion, authoritative employee creation, merge execution, apply, approval, ITSM, provisioning, and downstream source mutation no longer block Phase 1; they are deferred writer/future capabilities.
- Rehire, no-hire, deactivation, and reactivation are no longer treated as Phase 1 actions. They remain detection/finding scenarios only.
- Salesforce live API provisioning no longer blocks Phase 1. The Phase 1 boundary is evidence export/manual handoff; live API is future integration.
- A source conflict no longer automatically requires a winning source. The platform may report discrepancy, expected difference, latency, insufficient evidence, or policy-relevant finding.
- Canonical Worker creation is no longer described as hiring or authoritative employee creation. It is an internal analytical identity representation.

## Execution waves

### Wave 1 — Ingestion & lineage

Run UAT-001, UAT-008, UAT-009, UAT-010, and UAT-017.

Verify source files, batch identity, schema validation, quarantine, row counts, no silent loss, source snapshot metadata, lineage, analytical unmatched findings, and historical evidence. Use privacy-safe fixtures from every approved source.

**Exit criteria:** every input row is accepted, quarantined, or rejected with evidence; batch/file/source metadata is reproducible; no authoritative source is changed.

### Wave 2 — Identity reconciliation

Run UAT-002, UAT-003, UAT-004, UAT-005, UAT-018, and UAT-019.

Verify strong identifiers, approved aliases, fallback signals, deterministic match explanations, ambiguity, exact duplicates, possible duplicates, identifier changes, and name changes. A canonical identity is analytical only.

**Exit criteria:** approved identity evidence matrix exists; uncertain matches are surfaced; no silent merge, split, hire, or provisioning decision occurs.

### Wave 3 — Cross-source audit

Run UAT-006, UAT-007, UAT-014, UAT-015, UAT-016, UAT-020, UAT-024, and UAT-025.

Verify coverage, source conflicts, timestamps, refresh cadence, data age, source latency, expected differences, finding classification, report grain, control totals, and reproducibility. Do not force a winner without an approved field-level authority rule.

**Exit criteria:** every comparison has temporal context and one of `CONSISTENT`, `EXPECTED_DIFFERENCE`, `SOURCE_LATENCY`, `INSUFFICIENT_EVIDENCE`, `DISCREPANCY`, or `POLICY_RELEVANT_FINDING`.

### Wave 4 — Lifecycle findings

Run UAT-011, UAT-012, UAT-013, UAT-022, UAT-023, and UAT-032.

Verify potential rehire detection, conflicting status observations, missing-source conditions, no-hire findings, and human review of findings. The system must not approve/reject hire, terminate, reactivate, change access, or enforce policy.

**Exit criteria:** rehire/date/calendar parameters are approved; source latency and absence windows are approved; findings contain enough evidence for human action outside Phase 1.

### Wave 5 — Review, evidence & exports

Run UAT-026 and UAT-035.

Verify human review state, evidence/history, audit trace, report completeness, and local-versus-global notifications. Salesforce-specific output is deferred and is not a Phase 1 account change.

**Exit criteria:** evidence is complete, reproducible, and attributable; local operational notifications do not enter shared/database state; only analytical snapshot publication creates the global signal.

### Wave 6 — Platform safety

Run UAT-027, UAT-028, UAT-029, UAT-030, and UAT-036.

Verify authoritative mutation prevention, production authentication, least privilege, audit logging, backup/recovery, checksums, versioned data, and technical publication/distribution of the read-only analytical database.

**Exit criteria:** no Phase 1 path can mutate authoritative lifecycle/source data or execute a business decision; approved users can review only what their role permits; technical snapshot distribution is distinguishable from business-change publication.

## Entry criteria

- Versioned Phase 1 build and disposable analytical database/snapshot.
- Privacy-safe fixtures for all approved source formats and lifecycle observations.
- Named owners for identity, data, lifecycle, security, reporting, audit, operations, and product decisions.
- Approved finding-class vocabulary and initial source refresh/latency inventory.
- Production-like authentication with development auto-approval disabled.

## Evidence standard

Retain source files and hashes, batch IDs, row/control totals, schema/quarantine outcomes, match signals, canonical analytical IDs, source observations, snapshot/effective/received timestamps, finding class, discrepancy IDs, review notes, audit events, local notification files, export files, checksums, and screenshots of access-control results. Do not use production personal data in the test repository.

## Sign-off gates

Phase 1 sign-off requires:

1. Identity keys, aliases, fallback behavior, and ambiguity treatment approved.
2. Cross-source coverage expectations, latency windows, and absence semantics approved.
3. Conflict classification and expected differences approved; no unapproved silent overwrite.
4. Rehire detection parameters approved, with detection explicitly separated from action.
5. Finding severity and review evidence requirements approved.
6. Export grain, completeness, exclusions, and reproducibility approved.
7. Technical read-only enforcement proven for authoritative systems.
8. Authentication, authorization, audit, recovery, and analytical snapshot distribution proven.
9. Phase2 writer and future integrations recorded as deferred and non-blocking.

## Deferred scenarios

See [PHASE2_WRITER_DEFERRED_SCENARIOS.md](future/PHASE2_WRITER_DEFERRED_SCENARIOS.md). Those scenarios must not be included in the Phase 1 exit gate.

## Top stakeholder decisions

See [UAT_NEXT_MEETING_DECISIONS.md](UAT_NEXT_MEETING_DECISIONS.md) for the reduced ten-item agenda. The detailed 48-question backlog remains in [UAT_OPEN_BUSINESS_QUESTIONS.md](UAT_OPEN_BUSINESS_QUESTIONS.md).
