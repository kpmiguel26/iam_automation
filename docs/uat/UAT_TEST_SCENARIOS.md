# UAT Test Scenarios — IAM Automation Phase 1

These scenarios are discovery-oriented. “Actual behavior” records what the current repository does; it is not automatically the expected business result. Any unresolved policy is marked **BUSINESS DECISION REQUIRED**.

## Scope classification matrix

| UAT ID | Scope classification | Phase 1 sign-off treatment |
|---|---|---|
| UAT-001 | PHASE1_CORE | In scope |
| UAT-002 | PHASE1_CORE | In scope; analytical identity only |
| UAT-003 | PHASE1_CORE | In scope |
| UAT-004 | PHASE1_CORE | In scope |
| UAT-005 | PHASE1_CORE | In scope |
| UAT-006 | PHASE1_CORE | In scope |
| UAT-007 | PHASE1_CORE | In scope |
| UAT-008 | PHASE1_CORE | In scope |
| UAT-009 | PHASE1_CORE | In scope; unmatched analytical finding only |
| UAT-010 | PHASE1_CORE | In scope |
| UAT-011 | PHASE1_CORE | In scope; detection only |
| UAT-012 | PHASE1_CORE | In scope; detection only |
| UAT-013 | PHASE1_CORE | In scope; finding only, no enforcement |
| UAT-014 | PHASE1_CORE | In scope |
| UAT-015 | PHASE1_CORE | In scope |
| UAT-016 | PHASE1_CORE | In scope |
| UAT-017 | PHASE1_CORE | In scope |
| UAT-018 | PHASE1_CORE | In scope |
| UAT-019 | PHASE1_CORE | In scope |
| UAT-020 | PHASE1_CORE | In scope |
| UAT-021 | PHASE2_WRITER | Deferred; must not block Phase 1 |
| UAT-022 | PHASE1_CORE | In scope; finding only |
| UAT-023 | PHASE1_CORE | In scope; finding only |
| UAT-024 | PHASE1_CORE | In scope |
| UAT-025 | PHASE1_CORE | In scope |
| UAT-026 | PHASE1_PLATFORM | In scope |
| UAT-027 | PHASE1_PLATFORM | In scope; technical gate |
| UAT-028 | PHASE1_PLATFORM | In scope |
| UAT-029 | PHASE1_PLATFORM | In scope |
| UAT-030 | PHASE1_PLATFORM | In scope |
| UAT-031 | PHASE2_WRITER | Deferred; must not block Phase 1 |
| UAT-032 | PHASE1_CORE | In scope; human review of findings |
| UAT-033 | FUTURE_INTEGRATION | Deferred; Salesforce-specific handoff does not block Phase 1 |
| UAT-034 | FUTURE_INTEGRATION | Deferred; must not block Phase 1 |
| UAT-035 | PHASE1_PLATFORM | In scope |
| UAT-036 | PHASE1_PLATFORM | In scope for technical snapshot distribution |

## Status legend

- **Ready for UAT** — executable with representative data and no unresolved decision that changes the expected result.
- **Blocked by business decision** — technical path exists, but expected outcome is not approved.
- **Blocked by technical dependency** — required capability or environment is absent.
- **Not implemented** — the requested behavior is outside current implementation.

## Scenario cards

### Core identity and ingestion

#### UAT-001 — Standard employee ingestion
- **Objective:** Confirm a valid employee file is accepted, staged, traceable, and visible for review.
- **Preconditions:** Clean Phase 1 environment; source file owner identified.
- **Test data:** Valid Master Roster, Roster Lock, AccessNow, and/or RSR rows with required fields.
- **Steps:** Load each source; inspect import batch; inspect staged record; open reconciliation/report view.
- **Expected result:** Valid rows are accepted, source and batch are retained, and no downstream write occurs.
- **Actual behavior currently implemented:** Master Roster/Roster Lock/AccessNow/RSR staging exists; source-specific validation and quarantine run.
- **Pass / failure:** Pass if counts, source, batch, and evidence reconcile; fail on silent loss, unexpected promotion, or write.
- **Owner / evidence:** IAM Data Owner; files, batch IDs, row counts, screenshots, logs.
- **Status:** Ready for UAT.

#### UAT-002 — Canonical analytical identity resolution from one unambiguous record
- **Objective:** Confirm that a single valid source observation can be represented by one internal canonical analytical identity.
- **Preconditions:** A source record with a unique approved identifier; no authoritative source write capability.
- **Test data:** New employee with no existing Worker and complete required fields.
- **Steps:** Stage; reconcile; resolve the match; inspect analytical Worker, identifier, source observation, lineage, and history.
- **Expected result:** One analytical identity is represented with traceability and no duplicate; no authoritative employee or lifecycle decision is made.
- **Actual behavior currently implemented:** Existing promotion paths can create an ACTIVE Worker; this is a future writer concern and must not be used as Phase 1 acceptance.
- **Pass / failure:** Pass if analytical representation is deterministic and evidenced; fail if the result implies hire, provisioning, or source mutation.
- **Owner / evidence:** IAM Data Owner / Reviewer; analytical Worker ID, source record, match trace, audit event, evidence export.
- **Status:** Ready for UAT.

#### UAT-003 — Multiple source records for the same employee
- **Objective:** Confirm records from multiple sources resolve to one Worker only when identity evidence is sufficient.
- **Preconditions:** Matching identifiers across at least three sources.
- **Test data:** Same employee with equivalent and non-equivalent identifiers.
- **Steps:** Ingest; reconcile; inspect match signals, lineage, profile, and discrepancy output.
- **Expected result:** **BUSINESS DECISION REQUIRED** — IAM must define which identifiers establish identity and when a conflict blocks resolution.
- **Actual behavior currently implemented:** Strong matches are collected; multiple strong matches create conflict; email/name are fallback signals.
- **Pass / failure:** Pass only after IAM approves expected resolution for each data combination.
- **Owner / evidence:** IAM Identity Owner; match trace, conflict record, canonical view.
- **Status:** Blocked by business decision.

#### UAT-004 — Exact duplicate source records
- **Objective:** Confirm exact same-source duplicates do not create multiple current profiles.
- **Preconditions:** Duplicate detection enabled.
- **Test data:** Byte-identical and normalized-identical rows, plus a later correction.
- **Steps:** Load duplicates; inspect summary; identify current/superseded row; rerun ingestion.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define whether newest, latest effective date, or source authority wins.
- **Actual behavior currently implemented:** Same-source records are grouped by normalized signals; newest created-time record is current and earlier rows superseded.
- **Pass / failure:** Pass only if approved winner, repeatability, and evidence are demonstrated.
- **Owner / evidence:** Source Owner; source files, hashes, duplicate report, audit history.
- **Status:** Blocked by business decision.

#### UAT-005 — Fuzzy / possible duplicate
- **Objective:** Confirm near matches are surfaced for human review without an unsafe automatic merge.
- **Preconditions:** Two Workers with similar names/email/identifiers.
- **Test data:** Same name/different ID; typo; reused email; transliteration; missing identifiers.
- **Steps:** Ingest; run duplicate report; review candidate; attempt merge only through authorized route.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define match score, threshold, evidence, and reviewer decision.
- **Actual behavior currently implemented:** No fuzzy score or confidence threshold; canonical candidates are grouped by normalized full name.
- **Pass / failure:** Pass only if candidate and non-match behavior are approved and repeatable.
- **Owner / evidence:** IAM Identity Owner; candidate list, match explanation, reviewer decision.
- **Status:** Blocked by business decision.

#### UAT-006 — Conflicting employee status
- **Objective:** Confirm status conflicts are identified and resolved according to effective business dates.
- **Preconditions:** Same person has ACTIVE, DEACTIVATED, and/or TERMINATED records.
- **Test data:** Conflicting statuses with source timestamps, effective dates, and ingestion order variations.
- **Steps:** Ingest in different orders; inspect status, discrepancy, and history.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define source authority and effective-date precedence.
- **Actual behavior currently implemented:** Status aliases normalize; rank is ACTIVE, DEACTIVATED, TERMINATED; AccessNow termination rows can override.
- **Pass / failure:** Fail if result changes merely because file order changes, unless approved.
- **Owner / evidence:** IAM Lifecycle Owner; inputs, resulting status, timestamps, audit events.
- **Status:** Blocked by business decision.

#### UAT-007 — Conflicting source profile data
- **Objective:** Confirm conflicting names, managers, emails, and identifiers are visible and not silently overwritten.
- **Preconditions:** One matched Worker with conflicting non-empty source fields.
- **Test data:** Conflicting manager/name/email/role values and source timestamps.
- **Steps:** Reconcile; inspect discrepancy; preview update; attempt apply.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define field-level precedence and approval requirement.
- **Actual behavior currently implemented:** Conflicting RSR profiles are excluded from automatic apply; source update preview shows deltas and usually preserves populated canonical fields.
- **Pass / failure:** Pass if every field has an approved disposition and no silent loss.
- **Owner / evidence:** IAM Data Owner; discrepancy, preview, decision note, before/after.
- **Status:** Blocked by business decision.

#### UAT-008 — Missing required fields
- **Objective:** Confirm incomplete records are rejected/quarantined with actionable reasons.
- **Preconditions:** Quarantine and import audit available.
- **Test data:** Missing Employee Number, name, source key, invalid status, malformed date, blank identifiers.
- **Steps:** Load each variant; inspect batch result, quarantine, error reason, and retry behavior.
- **Expected result:** Invalid data is not promoted; the failed row and reason are recoverable.
- **Actual behavior currently implemented:** Required-field checks and quarantine exist at source boundaries.
- **Pass / failure:** Pass if no silent drop and retry does not duplicate valid rows.
- **Owner / evidence:** Source Owner; rejected file, row-level reason, batch log.
- **Status:** Ready for UAT (source-specific field list still needs confirmation).

#### UAT-009 — Unknown source observation
- **Objective:** Confirm an unknown source observation is surfaced as an analytical unmatched finding/candidate and is not treated as an authoritative employee.
- **Preconditions:** Source record has no Worker match.
- **Test data:** Valid-looking new RSR/AccessNow record and an unauthorized/ambiguous record.
- **Steps:** Stage; inspect unmatched finding; inspect candidate evidence, lineage, and audit; verify no authoritative action is available.
- **Expected result:** Unmatched evidence remains visible as `INSUFFICIENT_EVIDENCE` or another approved finding; no hire/reject/provisioning action occurs.
- **Actual behavior currently implemented:** RSR unmatched records can be promoted into an ACTIVE Worker through an existing writer path; that path is **DEFERRED — PHASE2_WRITER**.
- **Pass / failure:** Pass if only an analytical finding/candidate exists; fail on automatic or authoritative creation.
- **Owner / evidence:** IAM Identity Owner; unmatched record, match trace, finding, source lineage.
- **Status:** Blocked by technical dependency.

#### UAT-010 — Employee outside standard roster flow
- **Objective:** Determine how contractors, transfers, exceptions, and non-standard workers enter reconciliation.
- **Preconditions:** Business examples and ownership assigned.
- **Test data:** At least one non-standard onboarding case.
- **Steps:** Submit through available intake; attempt matching, exception, and export.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define eligibility, owner, identifiers, and route.
- **Actual behavior currently implemented:** No complete non-standard onboarding policy.
- **Pass / failure:** Pass only when a documented route and expected output exist.
- **Owner / evidence:** IAM Process Owner; approved exception procedure and resulting record.
- **Status:** Blocked by business decision.

### Lifecycle and reconciliation

#### UAT-011 — Rehire within 30 days
- **Objective:** Confirm the same person is treated as a rehire, not an accidental new identity, within the approved window.
- **Preconditions:** Inactive AccessNow worker and matching Roster Lock row.
- **Test data:** Termination and roster dates at 0, 1, 29, and 30 days, including holidays.
- **Steps:** Ingest; run alert; inspect elapsed-day calculation, matching, status, and archive action.
- **Expected result:** **BUSINESS DECISION REQUIRED** — calendar/business days and boundary rules are unresolved.
- **Actual behavior currently implemented:** Inclusive 0–30 business-day alert; weekdays only; optional holiday list; fallback to created timestamps if dates missing.
- **Pass / failure:** Pass only after date semantics are approved and boundary cases agree.
- **Owner / evidence:** IAM Lifecycle Owner; dates, calendar, alert, resulting Worker/engagement.
- **Status:** Blocked by business decision.

#### UAT-012 — Rehire after 30 days
- **Objective:** Confirm a rehire beyond the window follows the approved identity/engagement rule.
- **Preconditions:** Same person with prior inactive Worker and later source record.
- **Test data:** 31 business days, 31 calendar days, and materially later rehire.
- **Steps:** Ingest; reconcile; inspect match, engagement, and notification.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define whether prior Worker is reused, new engagement added, or new Worker proposed.
- **Actual behavior currently implemented:** Rehire alert only handles the 0–30 business-day window; broader lifecycle policy is absent.
- **Pass / failure:** Fail if system silently creates or merges without approved rule.
- **Owner / evidence:** IAM Lifecycle Owner; match trace, engagement history, decision.
- **Status:** Blocked by business decision.

#### UAT-013 — No-hire employee
- **Objective:** Confirm a no-hire/blacklist record prevents or quarantines onboarding as intended.
- **Preconditions:** Approved test no-hire record and safe test environment.
- **Test data:** Exact match, possible match, expired entry, and override case.
- **Steps:** Ingest onboarding record; observe match, quarantine, alert, and export behavior.
- **Expected result:** **BUSINESS DECISION REQUIRED** — key, expiry, override, and enforcement point must be defined.
- **Actual behavior currently implemented:** No complete no-hire enforcement was found.
- **Pass / failure:** Not passable until the rule is implemented and approved.
- **Owner / evidence:** IAM Compliance/Lifecycle Owner; protected test data, decision, outcome.
- **Status:** Not implemented.

#### UAT-014 — Employee present in one source but missing from another
- **Objective:** Confirm missing cross-source coverage becomes a discrepancy with correct ownership.
- **Preconditions:** Two source snapshots with intentionally missing person.
- **Test data:** Worker in AccessNow only, Roster Lock only, RSR only, and Master Roster only.
- **Steps:** Load snapshots; run reconciliation/report; inspect discrepancy and export inclusion.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define which absence is exceptional and expected resolution time.
- **Actual behavior currently implemented:** Reports expose source coverage and open discrepancies; no full policy/SLA was found.
- **Pass / failure:** Pass only if discrepancy type, severity, owner, and export treatment are approved.
- **Owner / evidence:** IAM Data Owner; snapshots, coverage report, discrepancy assignment.
- **Status:** Blocked by business decision.

#### UAT-015 — Source conflict and field-level classification
- **Objective:** Confirm a conflicting field is classified as authority, discrepancy, expected difference, source latency, or insufficient evidence only when evidence supports it.
- **Preconditions:** Same Worker with conflicting source values.
- **Test data:** Conflicting names, manager, status, email, role, and dates by source.
- **Steps:** Reconcile; generate canonical/report/export views; compare selected values.
- **Expected result:** Without an approved field-level authority rule, both observations remain visible as `DISCREPANCY`, `EXPECTED_DIFFERENCE`, `SOURCE_LATENCY`, or `INSUFFICIENT_EVIDENCE`; the platform does not silently overwrite evidence.
- **Actual behavior currently implemented:** Report engagement preference uses Roster Lock > RSR > AccessNow plus completeness/recency; this is an encoded heuristic, not an approved universal winner.
- **Pass / failure:** Pass if the classification and evidence are consistent; fail if an unapproved source silently wins.
- **Owner / evidence:** IAM Data Owner; precedence matrix, report, export, audit.
- **Status:** Blocked by business decision.

#### UAT-016 — Source freshness, latency, and timestamp conflict
- **Objective:** Confirm stale and current records are handled predictably.
- **Preconditions:** Source records with different created, updated, effective, and received timestamps.
- **Test data:** Late-arriving correction, stale active record, future-dated change, missing timestamp.
- **Steps:** Load in varying order; compare canonical/report/history output.
- **Expected result:** Snapshot date, effective date, received/imported date, and data age remain distinct; a mismatch is `SOURCE_LATENCY` until the approved window expires, not automatically a discrepancy.
- **Actual behavior currently implemented:** Some paths use created time, updated time, or effective fields; no global policy found — **ASSUMPTION CURRENTLY ENCODED**.
- **Pass / failure:** Pass if results expose temporal evidence and approved latency semantics; fail if load order alone creates a business conclusion.
- **Owner / evidence:** IAM Data Owner; timestamps, run order, selected value, history.
- **Status:** Blocked by business decision.

#### UAT-017 — Historical identity records
- **Objective:** Confirm old identifiers, names, engagements, and profile versions remain searchable and traceable.
- **Preconditions:** Worker with at least two profile versions and an old identifier.
- **Test data:** Name change, identifier change, rehire engagement, superseded source row.
- **Steps:** Inspect current view, history, lineage, and audit; search using current and historical identifier.
- **Expected result:** Historical evidence is retained and current identity is distinguishable.
- **Actual behavior currently implemented:** Immutable profile versions, identifiers, engagements, lineage, and snapshots exist.
- **Pass / failure:** Pass if no history is deleted or confused with current value.
- **Owner / evidence:** IAM Audit/Data Owner; history export, lineage, screenshots.
- **Status:** Ready for UAT.

#### UAT-018 — Employee identifier change
- **Objective:** Confirm an identifier change updates history without splitting or merging the wrong Worker.
- **Preconditions:** Existing canonical Worker and approved source correction.
- **Test data:** Changed Employee Number/NUID/NPN/email, reused old value, and conflicting new value.
- **Steps:** Ingest; review match; inspect identifier history and duplicate candidates.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define which identifier changes preserve identity and required approval.
- **Actual behavior currently implemented:** Identifier history model exists; matching aliases may treat IDs as equivalent.
- **Pass / failure:** Fail on silent split/merge or loss of old identifier.
- **Owner / evidence:** IAM Identity Owner; old/new identifiers, decision, history.
- **Status:** Blocked by business decision.

#### UAT-019 — Name change
- **Objective:** Confirm a legitimate name change does not create a duplicate.
- **Preconditions:** Worker with strong stable identifier and changed name.
- **Test data:** Legal name change, typo correction, same name/different person.
- **Steps:** Ingest; reconcile; inspect current profile, history, and duplicate report.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define proof and precedence for name changes.
- **Actual behavior currently implemented:** Exact name is a fallback signal; history supports versioning; source updates generally avoid overwriting populated fields.
- **Pass / failure:** Pass only if business-approved identity key and update path are followed.
- **Owner / evidence:** IAM Identity/Data Owner; source proof, profile versions, discrepancy.
- **Status:** Blocked by business decision.

#### UAT-020 — Manager change
- **Objective:** Confirm manager changes are visible, dated, and attributed to the correct source.
- **Preconditions:** Existing Worker with manager in one or more sources.
- **Test data:** Valid change, conflicting change, manager unavailable, circular hierarchy.
- **Steps:** Load; inspect delta preview, canonical/report output, history, and export.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define authority, effective date, and hierarchy validation.
- **Actual behavior currently implemented:** Source update preview and profile deltas exist; no final manager policy found.
- **Pass / failure:** Fail on silent overwrite or undated change.
- **Owner / evidence:** IAM Data Owner; before/after, source timestamp, approval.
- **Status:** Blocked by business decision.

#### UAT-021 — Role/access change request (deferred writer scenario)
- **Objective:** Distinguish a recorded request from an actual downstream access change.
- **Preconditions:** Requester/reviewer accounts; downstream sandbox if required.
- **Test data:** Create, update, deactivate, and role-change requests.
- **Steps:** Submit and approve request; inspect status, publication queue, and downstream result.
- **Expected result:** **DEFERRED — PHASE2_WRITER.** Phase 1 may report a role/access observation or finding only; it does not approve, apply, or execute the change.
- **Actual behavior currently implemented:** Request operations and approval/publication structures exist; downstream live integrations are future.
- **Pass / failure:** Fail if UAT claims access changed when only a request/export exists.
- **Owner / evidence:** IAM Process Owner; request JSON, approval, queue, downstream handoff.
- **Status:** Deferred — PHASE2_WRITER; does not block Phase 1.

#### UAT-022 — Deactivated employee
- **Objective:** Confirm deactivation is visible and does not get undone by stale active data.
- **Preconditions:** Worker with deactivation/termination evidence.
- **Test data:** Deactivated person with later stale ACTIVE row and no later effective event.
- **Steps:** Ingest; reconcile; inspect status, report, export eligibility, and alert.
- **Expected result:** **BUSINESS DECISION REQUIRED** — source authority and timing.
- **Actual behavior currently implemented:** Status normalization/ranking exists; AccessNow termination handling exists.
- **Pass / failure:** Fail if stale active row silently wins.
- **Owner / evidence:** IAM Lifecycle Owner; dates, status history, output.
- **Status:** Blocked by business decision.

#### UAT-023 — Reactivated employee
- **Objective:** Confirm reactivation requires the correct evidence and preserves prior history.
- **Preconditions:** Terminated/deactivated Worker and later active record.
- **Test data:** Authorized reactivation, accidental active feed, and rehire case.
- **Steps:** Ingest; inspect match, status, engagement, and audit.
- **Expected result:** **BUSINESS DECISION REQUIRED** — distinguish reactivation from rehire and define proof.
- **Actual behavior currently implemented:** Active status can rank above deactivated/terminated; no dedicated reactivation policy found.
- **Pass / failure:** Fail on silent reactivation.
- **Owner / evidence:** IAM Lifecycle Owner; source evidence, decision, engagement history.
- **Status:** Blocked by business decision.

### Outputs, security, and operations

#### UAT-024 — Analytical evidence export generation
- **Objective:** Confirm authorized users can generate the required Phase 1 reports and evidence exports.
- **Preconditions:** Approved test data; export directory; authorized role.
- **Test data:** Workers with complete, incomplete, duplicate, conflict, inactive, and historical records.
- **Steps:** Generate canonical/reconciliation and evidence exports; inspect naming, format, population, and audit.
- **Expected result:** Export completes, has stable schema, and does not write live downstream systems.
- **Actual behavior currently implemented:** Report service provides analytical report output; Salesforce-specific export is documented separately as future integration.
- **Pass / failure:** Pass if format, scope, and authorization meet signed specification.
- **Owner / evidence:** IAM Data/Reporting Owner; files, checksums, row counts, audit event.
- **Status:** Ready for UAT (business format/sign-off still required).

#### UAT-025 — Export completeness
- **Objective:** Confirm every eligible canonical Worker appears exactly once and exceptions are accounted for.
- **Preconditions:** Reconciled fixture with known expected population.
- **Test data:** Full fixture plus unmatched, quarantined, duplicate, inactive, and missing-source cases.
- **Steps:** Generate export; reconcile row count and IDs to expected population; inspect exclusions.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define eligible population and treatment of exceptions/inactive workers.
- **Actual behavior currently implemented:** Reports target one row per canonical Worker; Salesforce-specific request export is deferred and not used for Phase 1 completeness.
- **Pass / failure:** Fail on unexplained omission, duplicate, or inclusion.
- **Owner / evidence:** IAM Data Owner; control totals, exception list, exported IDs.
- **Status:** Blocked by business decision.

#### UAT-026 — Audit trail for Phase 1 platform actions
- **Objective:** Confirm ingestion, reconciliation, finding review, evidence export, analytical snapshot publication, and recovery events are attributable.
- **Preconditions:** Audit logging enabled; test users with distinct roles.
- **Test data:** One successful and one failed action in each Phase 1 flow.
- **Steps:** Execute actions; query JSONL audit; compare actor, entity, before/after, result, error, correlation ID.
- **Expected result:** Required Phase 1 platform actions have actor, entity, result, evidence, and correlation data; retention, immutability, required event catalog, and access remain **BUSINESS DECISION REQUIRED**.
- **Actual behavior currently implemented:** Append-oriented daily JSONL includes the listed fields; cryptographic immutability/retention are not complete.
- **Pass / failure:** Fail on missing actor, outcome, or correlation for a material action.
- **Owner / evidence:** IAM Audit/Compliance Owner; audit files, event IDs, retention proof.
- **Status:** Blocked by business decision.

#### UAT-027 — Authoritative mutation prevention
- **Objective:** Prove Phase 1 technically prevents authoritative lifecycle mutation while allowing internal analytical/runtime mutation.
- **Preconditions:** Production-like deployment, read-only role, administrator role, and audit access.
- **Test data:** Existing Worker and source records.
- **Steps:** Attempt hire/reject, terminate/reactivate, provision/deprovision, source-platform writes, automatic business decisions, and direct API mutation; separately verify ingestion, reconciliation, lineage, review state, evidence, snapshot publication, and restore.
- **Expected result:** Authoritative business mutation is technically impossible from Phase 1. Analytical/technical mutation is permitted. Technical publication of the read-only analytical database is not business-change publication.
- **Actual behavior currently implemented:** Routes exist for promotion, apply, merge, approval, publish, and restore; architecture says read-only. This is a repository contradiction requiring a gate/composition boundary, not a Phase 1 business decision.
- **Pass / failure:** Pass only when no authoritative mutation path is reachable; fail on any source-system write or automatic business outcome.
- **Owner / evidence:** IAM Security Owner; permission matrix, API responses, audit, database diff.
- **Status:** Blocked by technical dependency.

#### UAT-028 — Unauthorized user access
- **Objective:** Confirm unapproved users cannot log in or access sensitive employee data.
- **Preconditions:** Approved and unapproved test accounts; production authentication configuration.
- **Test data:** Local account, approved CSV entry, unknown user, expired/deactivated user.
- **Steps:** Attempt login and protected route access; inspect denial and audit.
- **Expected result:** Access follows approved identity provider and role policy; denial is logged without data leakage.
- **Actual behavior currently implemented:** Local SQLite login and approved-user CSV exist; development auto-approval defaults true.
- **Pass / failure:** Pass only in production-like configuration with auto-approval disabled and strong auth verified.
- **Owner / evidence:** IAM Security Owner; auth config, access matrix, logs.
- **Status:** Ready for UAT in production-like security configuration.

#### UAT-029 — Role-based access
- **Objective:** Confirm requester, reviewer, administrator/writer, auditor, and temporary elevation permissions match policy.
- **Preconditions:** One test user per role and delegation/elevation fixtures.
- **Test data:** Actions: view, submit, review, decide, merge, publish, restore, export, audit.
- **Steps:** Execute each action as each role; compare result with approved matrix.
- **Expected result:** **BUSINESS DECISION REQUIRED** — role catalog and actual decision authority must be reconciled.
- **Actual behavior currently implemented:** `identity.py` and request service restrict decisions to admins; role catalog says reviewer reviews and decides.
- **Pass / failure:** Fail on role drift or privilege escalation.
- **Owner / evidence:** IAM Security Owner; matrix, route results, audit.
- **Status:** Blocked by business decision.

#### UAT-030 — Recovery / versioned data
- **Objective:** Confirm backup, refresh, checksum, restore, and profile-history recovery preserve approved evidence.
- **Preconditions:** Disposable test copy and known snapshot checksum.
- **Test data:** Snapshot A, changed Snapshot B, local notifications, audit, and staged records.
- **Steps:** Publish/refresh; create backup; restore A; verify checksum, workers, history, notifications, and audit.
- **Expected result:** Restore returns the selected version without silent data loss or cross-user contamination.
- **Actual behavior currently implemented:** Runtime sync creates backups, uses atomic sync, checksum checks, and restore route.
- **Pass / failure:** Pass if all required artifacts and version identity are verified.
- **Owner / evidence:** IAM Operations Owner; checksums, backup manifest, restore log, record counts.
- **Status:** Ready for UAT (retention and local-notification policy still required).

#### UAT-031 — Duplicate merge execution (deferred writer scenario)
- **Objective:** Confirm an approved merge preserves evidence and makes supersession clear.
- **Preconditions:** Two candidate Workers; authorized merge role; backup.
- **Test data:** Matching identity, conflicting profiles, engagements, identifiers, discrepancies, and audit events.
- **Steps:** Review merge plan; require reason/approval; execute; inspect survivor, superseded Worker, lineage, reports, and history.
- **Expected result:** **DEFERRED — PHASE2_WRITER.** Phase 1 only presents duplicate candidates and evidence; it does not execute an authoritative merge.
- **Actual behavior currently implemented:** Merge route/service exists and preserves evidence, but automatic merge is not authorized and read-only scope conflicts.
- **Pass / failure:** Fail on unapproved merge or broken references.
- **Owner / evidence:** IAM Identity/Audit Owner; plan, approval, before/after IDs, backup.
- **Status:** Deferred — PHASE2_WRITER; does not block Phase 1.

#### UAT-032 — Manual review / exception handling
- **Objective:** Confirm conflicts, unmatched rows, quarantine, and overdue items have an owner, status, reason, and disposition.
- **Preconditions:** Reviewer and administrator test users; exception fixtures.
- **Test data:** Quarantined row, conflict, unmatched observation, duplicate candidate, source-latency finding, and policy-relevant finding.
- **Steps:** Open exception; assign/review; record decision; resolve/reject/escalate; inspect history and notification.
- **Expected result:** **BUSINESS DECISION REQUIRED** — define SLA, owners, dispositions, and escalation.
- **Actual behavior currently implemented:** Quarantine, under-review, rejected, conflict, and overdue notification paths exist, but policy is incomplete.
- **Pass / failure:** Fail on orphaned or silently resolved exception.
- **Owner / evidence:** IAM Operations Owner; exception ID, assignment, decision note, audit.
- **Status:** Blocked by business decision.

#### UAT-033 — Salesforce evidence export boundary (deferred)
- **Objective:** Confirm the future Salesforce-format file is an evidence/handoff export and not live Salesforce provisioning.
- **Preconditions:** Future-phase export template and Salesforce sandbox contact.
- **Test data:** Approved CREATE/UPDATE requests, duplicate employee requests, missing mapping fields.
- **Steps:** Generate XLSX; validate mappings, latest-request selection, alias/federation values, and manual handoff.
- **Expected result:** **DEFERRED — FUTURE_INTEGRATION.** Any future Salesforce file must be a reproducible handoff; no Salesforce API write or account decision occurs. Template mappings/defaults require separate validation.
- **Actual behavior currently implemented:** Export-only XLSX; no Salesforce API/authentication; default country/timezone/locale and generated alias/federation mapping.
- **Pass / failure:** Fail if consumers expect live provisioning or reject mappings.
- **Owner / evidence:** Salesforce Owner + IAM Reporting Owner; file, mapping sign-off, handoff receipt.
- **Status:** Deferred — FUTURE_INTEGRATION; does not block Phase 1.

#### UAT-034 — Future integration boundaries
- **Objective:** Confirm future AD/Azure, CXOne, NICE, SQL, orchestrator, and ITSM integrations are excluded or separately accepted.
- **Preconditions:** Phase scope and handoff owners documented.
- **Test data:** One record for each future integration boundary.
- **Steps:** Attempt to locate live connector, execute export/handoff, record actual endpoint and owner.
- **Expected result:** **DEFERRED — FUTURE_INTEGRATION.** Phase 1 has no live write; each future dependency is separately owned and must not block Phase 1 sign-off.
- **Actual behavior currently implemented:** Requirements and README describe integrations as future/placeholders; live ITSM writes are not evident.
- **Pass / failure:** Fail if undocumented live side effects exist or a required handoff has no owner.
- **Owner / evidence:** IAM Solution Owner; architecture, connection inventory, handoff evidence.
- **Status:** Deferred — FUTURE_INTEGRATION; does not block Phase 1.

#### UAT-035 — Local versus global notifications
- **Objective:** Confirm operational alerts stay with the local user and only database publication creates a global signal.
- **Preconditions:** Two local users/computers, shared publication folder, notification fixtures.
- **Test data:** Ingestion error, discrepancy, source-latency finding, analytical database publication, repeated publication within five minutes.
- **Steps:** Trigger each event; inspect each local notification store and shared folder; repeat publication.
- **Expected result:** Local events are not visible to another user; publication signal is global, critical, and throttled to five minutes.
- **Actual behavior currently implemented:** Local operational JSON store under `.iam_notifications`; shared `DATABASE_SNAPSHOT_PUBLISHED` signal with five-minute throttle.
- **Pass / failure:** Fail on cross-user operational noise, DB persistence, or excessive publication signals.
- **Owner / evidence:** IAM Operations Owner; per-user files, shared signal, timestamps.
- **Status:** Ready for UAT.

#### UAT-036 — Analytical snapshot publication and version visibility
- **Objective:** Confirm technical publication of a read-only analytical database is authorized, versioned, checksum-checked, and visible to other users only as a global publication event.
- **Preconditions:** Approved snapshot, publisher role, expected checksum, second user environment.
- **Test data:** Valid snapshot, stale checksum, concurrent update, repeated publication.
- **Steps:** Publish; inspect backup, checksum, database version, global notification, and second user refresh.
- **Expected result:** Only authorized technical snapshot publication succeeds; stale/concurrent publication fails safely; global signal is not duplicated inside five minutes. This is not business-change publication.
- **Actual behavior currently implemented:** Publish route requires Application/Master role, uses checksum/concurrency checks, backups, and global signal.
- **Pass / failure:** Fail on overwrite, unauthorized publish, wrong version, or local operational leakage.
- **Owner / evidence:** IAM Operations/Security Owner; checksum, backup, route response, notifications.
- **Status:** Ready for UAT (five-minute policy confirmation required).

## Coverage notes

The scenarios intentionally separate “the code has a path” from “IAM has approved the analytical interpretation.” The highest-impact Phase 1 blockers are UAT-003 through UAT-007, UAT-011 through UAT-016, UAT-018 through UAT-020, UAT-022/023, UAT-025/026, UAT-029, and UAT-032. UAT-027 is a technical release gate. UAT-021 and UAT-031 are deferred writer scenarios; UAT-034 is a deferred integration scenario. These must not block Phase 1 sign-off and must not be converted to passing tests by choosing a convenient expected result.
