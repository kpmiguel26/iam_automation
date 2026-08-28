# UAT Rules Inventory — IAM Automation Phase 1

## Purpose and scope

This inventory records business behavior found in the repository, whether it is approved, implied, partially implemented, missing, or contradictory. It is a discovery artifact for stakeholder validation, not a statement that every rule is approved. Phase 1 is intended to emphasize read-only ingestion, reconciliation, canonical employee views, history, discrepancy review, and exports. ITSM workflow and live downstream writes remain out of scope unless explicitly identified as a dependency.

Markers used throughout this package:

- **BUSINESS DECISION REQUIRED** — the repository does not provide an authoritative business answer.
- **ASSUMPTION CURRENTLY ENCODED** — implementation chooses an outcome without clear stakeholder approval.
- **CONTRADICTION** — two repository sources describe different behavior.

## Classification summary

| Classification | Count |
|---|---:|
| Confirmed | 13 |
| Implied | 13 |
| Partially implemented | 14 |
| Missing | 6 |
| Contradictory | 5 |
| Mixed classification (missing / partially implemented) | 1 |
| **Total rules** | **52** |

“Confirmed” means the behavior is consistently documented and implemented; it does not mean the business has formally signed it off. All unresolved policy choices remain subject to IAM validation.

## Rules

| ID | Business area | Rule description | Source / implementation evidence | Classification | IAM validation? | Risk if misunderstood |
|---|---|---|---|---|---|---|
| R-001 | Phase scope | Phase 1 should provide read-only employee/evidence review, reconciliation, canonical views, history, and exports. | `ARCHITECTURE.md`; `README.md`; `application/*` review routes | Contradictory — **CONTRADICTION** | Yes | Writers may be enabled in a phase intended only for review. |
| R-002 | Source ingestion | Master Roster is staged from XLSX and requires Employee Number and Employee Name. | `application/master_roster_ingestion_service.py`; `tests/test_master_roster_ingestion.py` | Confirmed | Yes | Invalid roster may enter reconciliation. |
| R-003 | Source ingestion | Roster Lock is staged from XLSX and keyed by vendor name plus vendor employee ID. | `application/roster_lock_ingestion_service.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Records can be lost or incorrectly treated as new. |
| R-004 | Source ingestion | AccessNow accepts CSV/XLSX files and groups rows by AccessNow employee ID. | `application/accessnow_ingestion_service.py`; tests | Confirmed | Yes | Multiple rows may be collapsed incorrectly. |
| R-005 | Source ingestion | RSR requires supplier reference, worker ID, and worker fields. | `application/rsr_supplier_worker_details.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | A valid supplier record may be quarantined. |
| R-006 | Identity matching | Strong identifiers are preferred: AccessNow employee ID, RSR worker ID, vendor employee ID, buyer reference, and master identifiers. | `application/source_reconciliation.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Wrong source records can become one person. |
| R-007 | Identity matching | Certain identifiers are aliased across sources, including NUID, employee number, vendor ID, and buyer reference. | `source_reconciliation.py:_match_types` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Same-looking identifiers may not be equivalent. |
| R-008 | Identity matching | More than one strong identifier match creates a conflict instead of automatic selection. | `source_reconciliation.py`; RSR tests | Confirmed | Yes | Safe conflict handling may be bypassed later. |
| R-009 | Identity matching | Email and exact normalized first/last name are fallback match signals. | `source_reconciliation.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Common names or reused email can merge people. |
| R-010 | Identity matching | No fuzzy scoring or confidence threshold is currently implemented. | `source_reconciliation.py` | Confirmed | Yes | “Possible duplicate” cannot be consistently triaged. |
| R-011 | Canonical identity | A Worker is the stable internal identity and Employee is a view over engagements, identifiers, profiles, and lineage. | `docs/architecture/WORKER_EMPLOYEE_CANONICAL_ARCHITECTURE.md`; `orm.py` | Confirmed | Yes | Rehire and history may create a second identity. |
| R-012 | Canonical identity | A source record with no match can become an ACTIVE worker after approval. | `rsr_supplier_worker_details.py`; `employee_service.py:_promote_record` | Partially implemented | Yes | Unverified people may be promoted. |
| R-013 | Canonical identity | Canonical duplicate candidates are grouped by normalized full name. | `employee_service.py:list_canonical_duplicates` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Different people with the same name may be presented as duplicates. |
| R-014 | Canonical identity | A merge preserves evidence and supersedes the duplicate rather than deleting evidence. | `employee_service.py:merge_workers`; worker history docs/tests | Confirmed | Yes | Audit and downstream references may be lost. |
| R-015 | Canonical identity | Automatic merge is not authorized; merge requires a review/decision path. | merge plan docs; routes and service | Partially implemented | Yes | A user may merge identities without policy authority. |
| R-016 | Source precedence | Report preferred engagement priority is Roster Lock, then RSR, then AccessNow, then recency/completeness. | `report_service.py:_preferred_engagement` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Exports may show a source the business does not trust. |
| R-017 | Source precedence | There is no approved global precedence matrix for every field and lifecycle state. | `REQUIREMENTS_GAP_REVIEW.md`; meeting notes | Missing — **BUSINESS DECISION REQUIRED** | Yes | Conflicting source values cannot be adjudicated consistently. |
| R-018 | Duplicate handling | Exact duplicate source signals are summarized; newest same-source record is current and earlier records are superseded. | `employee_service.py`; source duplicate tests | Confirmed | Yes | A late correction may be hidden or an erroneous row may win. |
| R-019 | Duplicate handling | Cross-source corroboration is treated as one worker when signals resolve to one identity. | `employee_service.py` duplicate summary | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Corroboration can be mistaken for identity proof. |
| R-020 | Duplicate handling | Fuzzy/possible duplicate workflow, score, threshold, and reviewer outcome are not implemented. | `source_reconciliation.py`; duplicate report docs | Missing — **BUSINESS DECISION REQUIRED** | Yes | Duplicate people may remain separate or be merged wrongly. |
| R-021 | Status | Status aliases map TERM/TERMINATED/TERMINATION to TERMINATED and DEACT/DISABLED/INACTIVE to DEACTIVATED. | `status_catalog.py` | Confirmed | Yes | Source status semantics may be flattened. |
| R-022 | Status | Status precedence ranks ACTIVE before DEACTIVATED before TERMINATED. | `status_catalog.py`; AccessNow ingestion | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | A stale active row could revive a terminated person. |
| R-023 | Status | AccessNow termination rows can override status and termination date while preserving sparse fields. | `accessnow_ingestion_service.py` | Partially implemented | Yes | Conflicting lifecycle events may be resolved incorrectly. |
| R-024 | Status | Conflicting status records are not governed by an approved effective-date rule. | source status tests; requirements tracker | Partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Access can remain active after termination or be disabled early. |
| R-025 | Required data | Required fields are source-specific and currently enforced mainly at ingestion boundaries. | ingestion services; tracker REQ-007/008 | Partially implemented | Yes | “Valid employee” differs by source. |
| R-026 | Missing data | Missing/invalid rows are quarantined or rejected, but remediation ownership and SLA are not defined. | `quarantine`, ingestion tests, operating model | Partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Exceptions accumulate without accountability. |
| R-027 | Unknown employee | An unknown RSR worker can be approved into a new ACTIVE worker. | `rsr_supplier_worker_details.py` | Partially implemented — **ASSUMPTION CURRENTLY ENCODED** | Yes | Supplier records can create unauthorized identities. |
| R-028 | Non-standard onboarding | The repository has no complete policy for employees outside the standard roster flow. | requirements gaps; meeting notes | Missing — **BUSINESS DECISION REQUIRED** | Yes | Contractors, transfers, or exceptions are omitted or misclassified. |
| R-029 | Rehire | Rehire alert compares an inactive AccessNow worker with Roster Lock and uses business days. | `rehire_alert_service.py`; `business_calendar.py` | Partially implemented | Yes | A rehire may be treated as new or as a duplicate. |
| R-030 | Rehire | Alert window is inclusive from 0 through 30 elapsed business days; fallback uses record-created timestamps when dates are absent. | `rehire_alert_service.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Wrong date source changes eligibility. |
| R-031 | Rehire | The tracker says “30-day rehire,” but does not resolve calendar vs business days, start/end inclusion, or effective-date source. | REQ-001; rehire tests/docs | Contradictory — **CONTRADICTION** | Yes | Incorrect rehire classification and access timing. |
| R-032 | No-hire | Blacklist/no-hire policy, matching key, override, expiry, and enforcement point are not implemented as a complete rule. | REQ-003; meeting notes; no complete service | Missing — **BUSINESS DECISION REQUIRED** | Yes | Ineligible individuals may be onboarded. |
| R-033 | Historical identity | Identifier history and immutable profile versions are intended to preserve old values and lineage. | `worker_history_service.py`; architecture docs | Confirmed | Yes | Name/ID changes can erase evidence. |
| R-034 | Identifier changes | The business meaning of changed employee number, NUID, NPN, or email is undefined. | identifier model; requirements gaps | Missing — **BUSINESS DECISION REQUIRED** | Yes | A changed identifier may split or merge workers. |
| R-035 | Profile changes | Name and manager changes are represented as source/profile changes, but effective-date and approval rules are open. | `employee_service.py`; source update tests | Partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Reports show stale or unauthorized relationships. |
| R-036 | Role/access changes | Role changes are requestable in the model, but downstream access application is future/ITSM scope. | `change_request.py`; README; requirements | Partially implemented — **CONTRADICTION** | Yes | UAT may mistake a request record for actual access change. |
| R-037 | Deactivation | Deactivation exists in statuses and request operations, but source authority and timing are not final. | `status_catalog.py`; `change_request.py`; REQ-005/053 | Partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Leavers retain access or active users are disabled. |
| R-038 | Reactivation | Reactivation behavior and required proof are not defined separately from active status ingestion. | code/status; no complete rule | Missing — **BUSINESS DECISION REQUIRED** | Yes | A terminated user may be silently reactivated. |
| R-039 | Exports | Reports provide one row per canonical worker with source/coverage/discrepancy fields. | `report_service.py`; report tests | Confirmed | Yes | Consumers may assume a different grain. |
| R-040 | Exports | Salesforce output is an export-only XLSX, not a Salesforce API integration. | `salesforce_export_service.py`; Salesforce guide | Confirmed | Yes | Stakeholders may expect live provisioning. |
| R-041 | Exports | Salesforce export uses only latest approved CREATE/UPDATE request per entity. | `salesforce_export_service.py` | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Older valid changes may be omitted. |
| R-042 | Exports | Salesforce export has hardcoded/default country, timezone, locale, alias, and federation mappings. | `salesforce_export_service.py`; guide | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | Wrong regional or identity values reach downstream loaders. |
| R-043 | Audit | Audit events are append-oriented daily JSONL with actor, entity, before/after, result, error, and correlation ID. | `audit.py`; audit finalization doc | Confirmed | Yes | Evidence may not prove who approved or published. |
| R-044 | Audit | Cryptographic immutability, retention, export, and completeness monitoring are not fully implemented. | `audit.py`; `2026-08-26_AUDIT_EVENTS_FINALIZATION.md` | Partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Audit evidence may fail compliance review. |
| R-045 | Read-only | UI text and architecture describe read-only review, but promotion, apply, merge, approval, publish, and restore routes exist. | `ARCHITECTURE.md`; `admin_routes.py`; `employee_routes.py` | Contradictory — **CONTRADICTION** | Yes | Production data can be changed unexpectedly. |
| R-046 | Security | Roles include requester, reviewer, administrator/writer, and auditor; permissions are not consistently aligned. | `SECURITY.md`; `role_catalog.py`; `identity.py` | Contradictory — **CONTRADICTION** | Yes | Unauthorized approvals, merges, or exports. |
| R-047 | Security | Local SQLite login and approved-user CSV are used; development auto-approval defaults true and Windows identity is primarily traceability. | `identity.py`; startup/config docs | Implied — **ASSUMPTION CURRENTLY ENCODED** | Yes | A non-production authentication path can be used in production. |
| R-048 | Publication | Database publish uses checksum/concurrency checks and local backups, and emits a global publication signal. | `runtime_sync.py`; `admin_routes.py`; notification services | Partially implemented | Yes | Users can run different versions or miss a critical publication. |
| R-049 | Notifications | Operational notifications are local JSON under `.iam_notifications`; only database publication is global and throttled to five minutes. | `local_notification_store.py`; `shared_notification_store.py`; notification tests | Confirmed | Yes | Local privacy, backup, or alert visibility assumptions may be wrong. |
| R-050 | Recovery | Local refresh/publish creates backups and supports restore/versioned data behavior. | `runtime_sync.py`; recovery tests | Partially implemented | Yes | Recovery may restore the wrong snapshot or omit local evidence. |
| R-051 | Requests / workflow | Requests use immutable JSON, status transitions, approval notes, and a publication queue; ITSM is not a Phase 1 live integration. | `change_request.py`; `request_service.py`; README | Contradictory — **CONTRADICTION** | Yes | UAT may sign off a workflow that is not operationally in scope. |
| R-052 | Salesforce / integrations | Salesforce, CXOne, NICE, AD/Azure, SQL, and orchestrator are primarily future or export assumptions, not completed live integrations. | requirements REQ-060..066; Salesforce guide; README | Missing / partially implemented — **BUSINESS DECISION REQUIRED** | Yes | Production readiness is overstated and handoffs fail. |

## High-risk interpretation

The most dangerous ambiguity is not a missing screen; it is identity adjudication. The application can select or create a canonical identity using aliases, email, name, recency, source priority, or an approval route before IAM has formally approved those choices. The second major ambiguity is phase scope: the repository contains writer-like routes while architecture documentation describes a read-only phase. These two issues must be resolved before sign-off.
