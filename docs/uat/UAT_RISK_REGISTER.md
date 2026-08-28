# UAT Risk Register — IAM Automation Phase 1

Scoring: Probability (P) and Impact (I) are 1–5. Score = P × I. “Owner” is the stakeholder accountable for accepting or mitigating the risk; technical implementation ownership may be different.

| ID | Risk | Evidence / trigger | P | I | Score | Treatment / UAT control | Owner | Status |
|---|---|---|---:|---:|---:|---|---|---|
| UR-001 | Wrong people are joined or split because identifier equivalence and fallback matching are not approved. | `source_reconciliation.py`; aliases, email/name fallback; Q-001..005 | 4 | 5 | 20 | Approve identity key/evidence matrix; execute UAT-003/005/018/019. | IAM Identity Owner | Open — business decision |
| UR-002 | A canonical Worker is created or promoted without sufficient business authorization. | RSR unmatched approval and `_promote_record`; Q-007/008 | 4 | 5 | 20 | Gate promotion, require evidence and role separation; UAT-002/009. | IAM Governance Owner | Open |
| UR-003 | Phase 1 is described as read-only while writer routes can promote, merge, apply, approve, publish, or restore. | `ARCHITECTURE.md` vs `admin_routes.py` / `employee_routes.py` | 4 | 5 | 20 | Decide phase boundary; disable/gate routes; UAT-027. | Product + Security Owners | Open — contradiction |
| UR-004 | Status/re-hire outcomes are wrong because “30 days,” effective dates, and source precedence are undefined. | `rehire_alert_service.py`; `status_catalog.py`; REQ-001/005 | 4 | 5 | 20 | Approve calendar/date/source rules; boundary tests UAT-006/011/012/022/023. | IAM Lifecycle Owner | Open |
| UR-005 | Exports are incomplete or contain wrong people because eligibility, grain, precedence, and exception treatment are not approved. | `report_service.py`; Salesforce export; Q-039..042 | 4 | 5 | 20 | Define control totals and inclusion matrix; UAT-024/025/033. | IAM Data/Reporting Owner | Open |
| UR-006 | No-hire/blacklist policy is absent, allowing an ineligible person to proceed. | REQ-003; no complete enforcement service | 3 | 5 | 15 | Define and implement policy; UAT-013. | Compliance Owner | Open — not implemented |
| UR-007 | Duplicate merge causes irreversible identity or access corruption. | Merge route/service exists; merge policy/reversibility open | 3 | 5 | 15 | Approval, backup, evidence preservation, reversal design; UAT-031. | IAM Identity + Audit | Open |
| UR-008 | Role conflict permits unauthorized approval or publication. | `role_catalog.py` vs `identity.py` and request service | 3 | 5 | 15 | Approve permission matrix and separation of duties; UAT-028/029. | Security Owner | Open — contradiction |
| UR-009 | Development auto-approval or local authentication is used in production. | `IAM_DEV_AUTO_APPROVE_USERS` default; `identity.py` | 3 | 5 | 15 | Production configuration gate and negative access tests. | Security/Operations | Open |
| UR-010 | A stale or late-arriving source overrides a current lifecycle event. | Created/updated/effective timestamps used inconsistently | 4 | 4 | 16 | Define timestamp policy; order-independence tests UAT-006/016. | Data Governance | Open |
| UR-011 | Missing/conflicting rows are quarantined but never resolved. | Quarantine and exception paths; ownership/SLA open | 4 | 4 | 16 | Assign owners, SLA, escalation and closure evidence; UAT-008/032. | IAM Operations | Open |
| UR-012 | Historical identifier/name changes create duplicate Workers or erase history. | Identifier aliases; Worker history intended but change policy open | 3 | 5 | 15 | Approve identity continuity rules; UAT-017/018/019. | IAM Identity Owner | Open |
| UR-013 | Deactivated users are included in exports or silently reactivated. | Status rank and active fallback; reactivation policy absent | 3 | 5 | 15 | Define lifecycle states and export eligibility; UAT-022/023/025. | IAM Lifecycle Owner | Open |
| UR-014 | Salesforce handoff is misunderstood as live provisioning. | Export-only XLSX; no Salesforce API/auth | 3 | 4 | 12 | Written Phase 1 boundary and receipt-based handoff; UAT-033/034. | Salesforce Owner | Open |
| UR-015 | Hardcoded Salesforce defaults produce incorrect accounts. | Country, timezone, locale, alias, federation mapping | 3 | 4 | 12 | Obtain mapping sign-off and negative/locale fixtures. | Salesforce Owner | Open |
| UR-016 | Audit evidence cannot prove material decisions or tamper resistance. | JSONL audit; retention/cryptographic immutability incomplete | 3 | 5 | 15 | Define event catalog, retention, tamper evidence, export; UAT-026. | Compliance Owner | Open |
| UR-017 | Local operational notifications leak to another user or disappear during refresh/backup. | `.iam_notifications` local store; policy not documented | 2 | 4 | 8 | Define privacy, retention, backup, and exclusion rules; UAT-035/030. | Security + Operations | Open |
| UR-018 | Global publication notification is too frequent or not visible after a legitimate publish. | Five-minute throttle and shared signal implementation | 2 | 4 | 8 | Confirm throttle semantics and publication event contract; UAT-036. | Operations Owner | Open |
| UR-019 | Requirements tracker and implementation have no authoritative status baseline. | Tracker contains 62 Pending requirements; docs/tests show implemented foundations | 4 | 3 | 12 | Baseline requirements, mark implemented/deferred/blocked, link evidence. | Product Owner | Open — contradiction |
| UR-020 | A source schema/mapping change silently changes identity or export behavior. | Header aliases and code mappings in services/config | 3 | 4 | 12 | Assign schema owners, version mappings, regression fixtures; UAT-001/024. | Source Owners | Open |
| UR-021 | Recovery restores a technically valid but business-wrong snapshot. | Checksums/backups/restore exist; RPO/RTO/rollback policy absent | 2 | 5 | 10 | Define version selection, retention, rollback approval; UAT-030/036. | Operations Owner | Open |
| UR-022 | Live downstream integration is assumed but unavailable. | AD/Azure, CXOne, NICE, SQL, orchestrator, ITSM future/placeholder | 3 | 4 | 12 | Integration inventory and explicit Phase 1 exclusions; UAT-034. | Solution Owner | Open |
| UR-023 | Source coverage discrepancies are not actionable because absence semantics are unclear. | Report coverage fields, no source-specific SLA/disposition | 4 | 4 | 16 | Define expected presence by population and owner; UAT-014/025. | Data Owner | Open |
| UR-024 | A partial update silently retains a stale populated field. | Source update logic generally avoids overwriting populated fields | 3 | 4 | 12 | Field-level update/clear policy and before/after evidence; UAT-007/020. | Data Governance | Open |
| UR-025 | Request status/publication semantics are inconsistent with the required lifecycle. | Tracker requires published; request model lacks clear `PUBLISHED` state | 3 | 3 | 9 | Approve state machine and publication meaning; UAT-021/036. | Process Owner | Open — contradiction |
| UR-026 | Holiday/calendar configuration changes rehire eligibility without controlled maintenance. | Optional `REHIRE_HOLIDAYS`; invalid values ignored | 2 | 4 | 8 | Owner, validation, versioning, and effective date for calendar. | Operations Owner | Open |

## TOP 5 production risks

1. Wrong identity joins/splits from unapproved matching and identifier equivalence (UR-001).
2. Unauthorized canonical creation or promotion (UR-002).
3. Writer behavior conflicting with the stated read-only Phase 1 boundary (UR-003).
4. Incorrect rehire/status decisions caused by unresolved dates and precedence (UR-004).
5. Unreliable or unsafe exports caused by undefined eligibility, grain, and precedence (UR-005).

## Risk acceptance rule

No risk scored 20 should be accepted solely by passing a technical test. It requires a named business owner, written decision, test evidence, and an explicit residual-risk acceptance if implementation is deferred.
