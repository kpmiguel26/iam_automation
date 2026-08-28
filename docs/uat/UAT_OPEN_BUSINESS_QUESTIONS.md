# UAT Open Business Questions — IAM Automation Phase 1

Every question below requires an accountable stakeholder decision before the related UAT result can be signed off. The “current assumption” column describes repository behavior, not an approved requirement.

## Identity matching

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-001 | Which identifier is the authoritative identity key across all sources? | Controls matching, canonical creation, rehire, merge, and export. | Multiple strong IDs are accepted and some are aliased. | Wrong identity joins or splits. | IAM Identity Owner |
| Q-002 | Are NUID, NPN, Employee Number, Vendor Employee ID, Worker ID, and Buyer Reference truly equivalent, or only source-local? | Controls cross-source joins. | `_match_types` aliases several values. | Unrelated people can merge. | IAM Data Owner |
| Q-003 | May email match an employee when no strong identifier matches? | Controls fallback matching. | Email is a fallback signal. | Reused/shared email causes false merge. | IAM Identity + Security |
| Q-004 | May exact first/last name match an employee? Under what extra evidence? | Controls ambiguous and common-name cases. | Exact normalized names are fallback signals. | Same-name people merge. | IAM Identity Owner |
| Q-005 | What evidence and threshold define a possible duplicate? | Needed for candidate reports and manual review. | No fuzzy score or threshold exists. | Duplicates remain hidden or are merged inconsistently. | IAM Identity Owner |

## Canonical employee rules

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-006 | What exactly is a Worker versus an Employee in business terms? | Defines grain of canonical views, exports, and reporting. | Worker is stable identity; Employee is a view. | Wrong row counts and lifecycle model. | IAM Solution Owner |
| Q-007 | When may an unmatched source record create a canonical Worker? | Controls unauthorized identity creation. | Approved RSR unmatched rows can create ACTIVE Workers. | False employees enter master data. | IAM Identity Owner |
| Q-008 | Does every new Worker require human approval, and which role may approve? | Controls promotion and audit. | Promotion/admin routes exist; role policy is inconsistent. | Unapproved records become canonical. | IAM Governance Owner |
| Q-009 | What fields are mandatory for canonical creation versus source staging? | Defines valid record and quarantine behavior. | Required fields are source-specific. | Incomplete employees are exported. | IAM Data Owner |

## Source precedence

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-010 | Which source owns status, manager, name, email, role, dates, and identifiers? | Needed for every conflict and export. | Report preference is Roster Lock > RSR > AccessNow, not field-specific. | Wrong values reach downstream. | IAM Data Governance |
| Q-011 | Is source precedence different for current status, historical evidence, and effective-dated changes? | Prevents one priority rule from overriding lifecycle history. | Shared status rank exists. | Terminated users may appear active. | IAM Lifecycle Owner |
| Q-012 | Which timestamp wins: effective, updated, created, received, or file date? | Controls late corrections and order independence. | Different services use different timestamps. | Results change with load order. | IAM Data Owner |
| Q-013 | How fresh must each source be before it is considered usable? | Controls stale-data warnings and export readiness. | No complete freshness policy found. | Exports rely on outdated data. | IAM Operations Owner |

## Duplicate handling

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-014 | What is an exact duplicate: same ID, same full row, same normalized identity, or same business event? | Defines duplicate reports and supersession. | Normalized signals and newest created time are used. | Corrections or duplicates are misclassified. | IAM Data Owner |
| Q-015 | Should the newest record always win, or only when its effective date is newer? | Controls current profile selection. | Newest same-source created-time record wins. | Bad late row overrides valid data. | Source Owners |
| Q-016 | Who can merge two Workers, what evidence is required, and is merge reversible? | Controls permanent identity consequences. | Merge route exists and preserves evidence; approval policy is open. | Irreversible false merge. | IAM Identity + Audit |
| Q-017 | What happens to requests, access, audit, exports, and identifiers after a merge? | Defines downstream referential integrity. | Evidence is preserved; all downstream behavior is not defined. | Broken references and audit gaps. | IAM Solution Owner |

## Rehire

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-018 | Does “30-day rehire” mean calendar days or business days? | Changes alert eligibility. | Code uses business days. | Early/late access decisions. | IAM Lifecycle Owner |
| Q-019 | Are day zero and day thirty included? | Defines boundary cases. | Code includes 0 and 30. | Inconsistent boundary outcomes. | IAM Lifecycle Owner |
| Q-020 | Which termination and rehire dates are authoritative? | Controls rehire matching. | Code falls back to created timestamps if dates are missing. | Wrong rehire classification. | IAM Data Owner |
| Q-021 | Does a rehire reuse the Worker and add an engagement, or create a new Worker? | Defines identity history and access. | Architecture favors stable Worker/engagements; broad policy open. | Duplicate identities or lost history. | IAM Identity Owner |
| Q-022 | What happens after the 30-day window? | Needed for UAT-012 and onboarding. | No complete rule found. | Silent new identity or unsafe merge. | IAM Lifecycle Owner |
| Q-023 | Which holidays and business calendar apply? | Controls elapsed business days. | Optional `REHIRE_HOLIDAYS`; invalid entries are ignored. | Calendar drift changes eligibility. | IAM Operations Owner |

## No-hire policy

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-024 | What is the authoritative no-hire/blacklist source and matching key? | Controls eligibility. | No complete enforcement found. | Ineligible person onboarded. | IAM Compliance Owner |
| Q-025 | Does a possible match block onboarding or only require review? | Defines false-positive treatment. | No rule. | Either unsafe onboarding or unfair blocking. | IAM Compliance + HR |
| Q-026 | Who may override a no-hire decision and what evidence is retained? | Controls governance and audit. | No rule. | Unauthorized exception or audit failure. | IAM Governance Owner |

## Non-standard onboarding

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-027 | How are contractors, transfers, interns, vendors, and exceptions represented? | Defines source route and canonical eligibility. | No complete policy found. | Population gaps and bad exports. | IAM Process Owner |
| Q-028 | Which team owns an employee absent from the standard roster? | Needed for exception remediation. | Ownership is not encoded. | Exceptions remain orphaned. | IAM Operations Owner |
| Q-029 | Can non-standard workers appear in Salesforce or other exports? | Controls downstream scope. | Export eligibility is not fully defined. | Unapproved downstream accounts. | Salesforce/Data Owners |

## Missing and conflicting data

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-030 | What is the disposition for a missing required field: reject, quarantine, hold, or create with warning? | Controls promotion and export. | Ingestion rejects/quarantines; business disposition is open. | Silent omissions or bad records. | IAM Data Owner |
| Q-031 | Who owns each exception and what is its SLA? | Makes reconciliation operational. | Overdue request notification exists; exception ownership/SLA is incomplete. | Stale unresolved data. | IAM Operations Owner |
| Q-032 | Should a conflicting non-empty value block all updates or only that field? | Controls safe partial updates. | RSR conflicts exclude automatic apply; other updates are selective. | One conflict blocks too much or overwrites too much. | IAM Data Governance |
| Q-033 | How should a person present in only one source be classified? | Controls discrepancy severity and export. | Coverage fields exist; policy absent. | False completeness. | IAM Data Owner |
| Q-034 | How are future-dated changes handled? | Controls current versus pending profile. | No global effective-date behavior found. | Premature activation/deactivation. | IAM Lifecycle Owner |

## Access and security

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-035 | Is Phase 1 strictly read-only, or are promotion, merge, approval, publish, and restore allowed? | Determines whether writer routes must be disabled. | Docs say read-only; routes expose writers. | Unauthorized production changes. | IAM Security + Product Owner |
| Q-036 | Which role may decide requests and approve publication? | Controls separation of duties. | Service permits admins; role catalog says reviewers decide. | Privilege conflict. | IAM Governance Owner |
| Q-037 | What production authentication and user-provisioning method is mandatory? | Controls user identity and authorization. | Local login/CSV; dev auto-approval defaults true. | Unauthorized access. | IAM Security Owner |
| Q-038 | May an administrator approve their own request or merge? | Controls segregation of duties. | No explicit self-approval rule found. | Fraud/compliance exposure. | IAM Governance Owner |

## Export and reporting

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-039 | What is the required export grain: Worker, engagement, source row, or request? | Defines completeness and duplicate expectations. | Canonical report is one row per Worker; Salesforce uses latest approved request. | Consumers misread files. | IAM Reporting Owner |
| Q-040 | Which statuses and exception states are included or excluded from each export? | Controls access and downstream actions. | Filters vary by report/export path. | Inactive or unresolved users exported. | IAM Data Owner |
| Q-041 | Are Salesforce defaults (US, Pacific time, `en_US`, generated alias/federation ID) approved? | Prevents incorrect downstream identity data. | Defaults are hardcoded. | Bad Salesforce accounts. | Salesforce Owner |
| Q-042 | Is Salesforce handoff manual XLSX only for Phase 1, or is API provisioning expected? | Sets acceptance boundary. | No API; export-only implementation. | False production-readiness sign-off. | Salesforce + IAM Solution Owners |

## Audit and evidence

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-043 | Which actions must be audited, for how long, and who may read audit data? | Defines compliance evidence. | Daily JSONL with core fields; retention incomplete. | Failed audit or unverifiable decision. | IAM Audit/Compliance |
| Q-044 | Is append-only JSONL sufficient, or is tamper evidence/cryptographic immutability required? | Determines audit architecture. | No cryptographic protection found. | Evidence can be challenged. | IAM Compliance |
| Q-045 | Are local notification files private, backed up, retained, and excluded from shared publication? | Confirms the local/global notification model. | `.iam_notifications` is local; policy not documented. | Cross-user leakage or lost operational context. | IAM Operations + Security |

## Ownership and maintenance

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-046 | Who owns source schemas, mapping changes, holiday calendars, and precedence matrices? | Prevents silent rule drift. | Mappings/configuration are in code/config. | Changes occur without UAT. | IAM Operations Owner |
| Q-047 | Who approves requirement changes and maintains the requirements tracker? | Aligns “Pending” tracker with delivered behavior. | Tracker remains all Pending while code/tests are advanced. | No authoritative baseline. | Product Owner |

## Production readiness

| ID | Question | Why it matters / dependent behavior | Current assumption in code | Risk if undefined | Recommended stakeholder |
|---|---|---|---|---|---|
| Q-048 | Which downstream integrations are genuinely required for Phase 1 sign-off? | Defines technical dependencies and exclusions. | AD/Azure, Salesforce, CXOne, NICE, SQL, orchestrator are future/placeholder areas. | Incomplete launch with hidden dependencies. | IAM Solution Owner |
| Q-049 | What are the recovery RPO/RTO, backup retention, and publication rollback requirements? | Determines operational readiness. | Backups/checksums/restore exist; target objectives are absent. | Prolonged outage or wrong snapshot restored. | IAM Operations Owner |

## TOP QUESTIONS FOR NEXT IAM MEETING

1. Which identifier is authoritative across every source, and which identifiers are merely source-local?
2. What evidence is required before two source records may be treated as the same person?
3. Is Phase 1 strictly read-only, and if so, which promotion, merge, approval, publish, and restore routes must be disabled?
4. What is the field-by-field source precedence matrix for status, name, manager, email, role, identifiers, and dates?
5. Does the 30-day rehire rule use calendar days or business days, and which boundaries/dates are included?
6. Does a rehire reuse the existing Worker with a new engagement, or create a new Worker?
7. What is the approved no-hire source, matching rule, override process, and audit requirement?
8. Who may create an unknown canonical Worker, and what approval/evidence is mandatory?
9. What is the approved policy for exact and possible duplicates, including merge authority and reversibility?
10. Which statuses and exception states are eligible for each export, and must every eligible Worker appear exactly once?
11. Who owns missing-source and conflicting-data exceptions, and what are the resolution SLAs?
12. Which role may approve requests and publication, and is self-approval prohibited?
13. Is Salesforce Phase 1 export-only XLSX, or is live API provisioning required for sign-off?
14. What audit retention and tamper-evidence standard is required, including local notification files?
