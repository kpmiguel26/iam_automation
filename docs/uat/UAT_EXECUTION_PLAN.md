# UAT Execution Plan — IAM Automation Phase 1

## Executive summary

The repository contains meaningful Phase 1 implementation, but the highest-risk decisions are still business-owned. Identity matching, canonical promotion, source precedence, rehire, no-hire, export eligibility, and read-only scope must be settled before UAT can become a sign-off exercise.

| Measure | Result |
|---|---:|
| Confirmed rules | 13 |
| Implied rules | 13 |
| Assumptions encoded in code | 14 explicit inventory rows marked **ASSUMPTION CURRENTLY ENCODED**; several overlap with implied/partial classifications |
| Business decisions still required | 49 open questions |
| UAT scenarios ready | 9 |
| Scenarios blocked by business decision | 21 exclusively business-blocked; 2 additional scenarios have both business and technical blockers |
| Scenarios blocked technically | 3 technically impacted scenarios (two also require business decisions) |
| Scenarios not implemented | 3 |

The counts are intentionally non-exclusive where a scenario has both a technical and a business blocker. “Assumptions encoded” is a marker count, not a separate rule classification; it overlaps with implied and partially implemented rules.

## Recommended execution waves

### Wave 1 — Core identity

Run UAT-001, UAT-002, UAT-003, UAT-006, UAT-008, UAT-009, and UAT-017. First approve identity keys, required fields, canonical Worker grain, and creation authority. Use a controlled golden dataset with stable IDs, deliberate conflicts, missing fields, and history.

**Exit criteria:** identity decision matrix approved; no unexplained canonical creation, split, or merge; every source row has batch and lineage evidence.

### Wave 2 — Duplicate and reconciliation

Run UAT-004, UAT-005, UAT-007, UAT-014, UAT-015, and UAT-016. Include exact duplicates, near duplicates, source-only records, conflicting fields, and reordered/late-arriving files.

**Exit criteria:** duplicate definition, possible-match threshold, field-level precedence, freshness policy, and exception ownership are approved; results are order-independent where required.

### Wave 3 — Exception and lifecycle handling

Run UAT-011, UAT-012, UAT-013, UAT-018, UAT-019, UAT-020, UAT-022, UAT-023, and UAT-032. Include rehire boundary dates, holidays, identifier/name changes, deactivation/reactivation, no-hire, and manual review.

**Exit criteria:** rehire calendar and Worker/engagement policy approved; no-hire policy exists or is explicitly deferred with risk acceptance; exceptions have owners, SLAs, and disposition evidence.

### Wave 4 — Security and read-only enforcement

Run UAT-027, UAT-028, and UAT-029 in a production-like configuration. Test both UI and protected endpoints, including direct mutation attempts. Confirm development auto-approval is disabled.

**Exit criteria:** signed role/permission matrix; separation of duties; read-only boundary technically enforced or writer scope explicitly approved; no unauthorized mutation.

### Wave 5 — Export and audit

Run UAT-024, UAT-025, UAT-026, UAT-033, and UAT-035. Reconcile control totals, row grain, inclusion/exclusion, Salesforce mappings, audit events, and local/global notification behavior.

**Exit criteria:** export contract and eligibility matrix signed; Salesforce boundary accepted; audit event/retention standard approved; local notifications never become shared database data; only publication generates global signal.

### Wave 6 — Production readiness

Run UAT-030, UAT-031, UAT-034, and UAT-036. Validate backup/restore, merge recovery, integration boundaries, checksum/concurrency, publication, and five-minute global publication throttling.

**Exit criteria:** RPO/RTO/retention agreed; integration inventory has owners; publication/rollback approvals documented; release checklist and residual-risk acceptance complete.

## Entry criteria

- A versioned test build and disposable database/snapshot are available.
- Representative, privacy-safe fixtures exist for every source and lifecycle case.
- Stakeholder owners are named for Identity, Data, Lifecycle, Security, Reporting, Audit, Operations, Salesforce, and Product.
- The current requirements tracker has been reconciled with repository evidence.
- The expected result for each scenario is either approved or explicitly marked blocked.

## Test data and evidence standard

Each UAT run should retain source files, file hashes, import batch IDs, row/control totals, match signals, discrepancy IDs, Worker/engagement/identifier IDs, before/after snapshots, approval notes, audit events, notification files, export files, checksums, and screenshots of role/access results. Use synthetic identifiers and never place production personal data in the repository.

## Defect and decision handling

1. Log a technical defect when actual behavior differs from an approved expected result.
2. Log a business decision when the repository makes a choice but stakeholders have not approved it.
3. Do not close a business ambiguity by changing the test expected result.
4. For an unresolved critical identity/security/export risk, mark the scenario blocked and obtain named risk acceptance before release.
5. Link each final decision to the relevant rule, question, scenario, and implementation change.

## UAT sign-off recommendation

Phase 1 should not be signed off until Q-001, Q-007, Q-010, Q-018, Q-021, Q-024, Q-035, Q-036, Q-039, Q-042, and Q-043 are answered. If any is deferred, the Product Owner and the affected IAM owner must record scope, workaround, residual risk, and target phase.

## Top 10 questions for the next stakeholder meeting

1. Which identifier is authoritative across every source, and which identifiers are source-local?
2. What evidence is required before two records may be treated as the same person?
3. Is Phase 1 strictly read-only, and which writer routes must be disabled?
4. What is the field-by-field source precedence matrix?
5. Does the 30-day rehire rule use calendar or business days, and which boundaries are included?
6. Does a rehire reuse the Worker with a new engagement, or create a new Worker?
7. What is the no-hire source, match rule, override process, and audit requirement?
8. Who may create an unknown Worker, and what evidence is mandatory?
9. What is the exact/possible duplicate policy, including merge authority and reversibility?
10. Which statuses and exception states are eligible for each export, and must each eligible Worker appear exactly once?

## Final checklist

- [ ] Identity matching and identifier equivalence approved.
- [ ] Canonical Worker/Employee model and creation authority approved.
- [ ] Source precedence, freshness, and duplicate policy approved.
- [ ] Rehire, no-hire, non-standard onboarding, and lifecycle rules approved.
- [ ] Missing/conflicting data ownership and SLA approved.
- [ ] Read-only boundary and role matrix technically verified.
- [ ] Export grain, completeness, Salesforce boundary, and mappings approved.
- [ ] Audit, retention, local notification, and recovery policy approved.
- [ ] Future integration dependencies explicitly excluded or accepted.
- [ ] Critical residual risks accepted by named owners.
