# Four-source match findings

**Reviewed:** 2026-09-24

**Scope:** The four latest saved report-template drafts in the local configuration library and their corresponding SharePoint simulation fixtures.

**Purpose:** Identify data-backed identifier links for the Template Object's user-configured cross-report relationships.

## Sources reviewed

| Saved report template | Fixture | Rows reviewed |
|---|---|---:|
| Companyname Teletech Report 07302026 | [`CompanyName_TELETECH_report_07302026.csv`](../../tests/fixtures/sharepoint_simulated/acessnow/CompanyName_TELETECH_report_07302026.csv) | 634 |
| Kaiser Master Roster 2026 09 22T0610 | [`Kaiser_Master_Roster_2026-09-22T0610.xlsx`](../../tests/fixtures/sharepoint_simulated/master_roster/Kaiser_Master_Roster_2026-09-22T0610.xlsx) | 1,017 |
| Rsr Supplier Worker Details | [`RSR Supplier Worker Details -- .xlsx`](../../tests/fixtures/sharepoint_simulated/rsrsuplierworkerdetails/RSR%20Supplier%20Worker%20Details%20--%20.xlsx) | 617 |
| Nses Roster Lock Submission Form June 1st up to July 22nd | [`NSES Roster Lock - Submission Form_June 1st up to July 22nd (1).xlsx`](../../tests/fixtures/sharepoint_simulated/rosterlocks/NSES%20Roster%20Lock%20-%20Submission%20Form_June%201st%20up%20to%20July%2022nd%20%281%29.xlsx) | 79 |

The saved CompanyName template points to a CSV fixture; the other three are
Excel workbooks. The workbook header rows were located from their actual sheet
layouts. The Kaiser workbook has two source columns both labelled `LogonID`;
its composed header context distinguishes `NUID · LogonID` from `NPN · LogonID`.

## Data-backed overlaps

Counts below are distinct, non-empty values that matched after trimming
surrounding whitespace and ignoring letter case. Raw identifiers and names are
intentionally omitted from this note.

| Source field A | Source field B | Shared values | Finding |
|---|---|---:|---|
| CompanyName `Nuid` | Kaiser `NUID · LogonID` | 518 | Strong direct bridge supported by the data and by the configured Strong identity fields. |
| Kaiser `Employee Number` | NSES `Vendor employee ID` | 51 | Strong candidate bridge; the business meaning of both columns should be confirmed. |
| Kaiser `NPN · LogonID` | RSR `NPN` | 25 | Exact-value overlap. NPN is not currently configured as an identity in either template. |
| Kaiser `NPN · LogonID` | NSES `NPN` | 23 | Exact-value overlap. NPN is not currently configured as an identity in either template. |
| RSR `NPN` | NSES `NPN` | 22 | Exact-value overlap. |

Twenty distinct NPN values occur in all three of Kaiser, RSR and NSES. There is
no single identifier value shared across all four sources. Exact full-name
values also did not intersect across all four. Name fields have different
shapes (`Employee Name`, first/last name pairs and `Worker`) and remain
supporting evidence rather than a unique cross-source key.

## Candidate relationship layout

These links form a connected graph across all four reports:

1. Anchor on Kaiser `NUID · LogonID` and match CompanyName `Nuid`.
2. Anchor on Kaiser `NPN · LogonID` and match RSR `NPN` plus NSES `NPN` in one
   one-to-many group.

The Template Object settings UI can express the second link as one anchor with
two target identifiers. The current saved source identity settings do not expose
NPN for matching, so those report templates would first need NPN selected as a
match identifier. NPN should remain text in the template so identifier formatting
is preserved. Before treating it as Strong, a report owner must confirm it is
stable and does not identify different people in the same source.

Kaiser `Employee Number` ↔ NSES `Vendor employee ID` is an additional possible
link with 51 shared values. Confirm that these fields represent the same worker
identifier before adding it; matching values alone do not establish business
meaning.

The RSR template currently selects `Buyer Reference` as its Strong identifier.
The reviewed cross-report IDs did not establish it as the bridge to these other
reports. `Worker ID` is present as a source field but was not configured as an
identity in the saved template. Its business meaning and uniqueness need review
before using it for matching.

## Method and limits

- Compared the saved included-field definitions with the actual fixture headers.
- Counted exact normalized-value overlaps for the candidate identifier columns;
  no personal values were written to this document.
- This is a configuration finding, not an ingestion or identity-resolution run.
- Matching permissions were not changed and no Template Object relationships
  were saved as part of this review.
- Overlap counts do not prove uniqueness, ownership, or semantic equivalence.
  The proposed NPN and employee-number links need business confirmation before
  being configured as Strong relationships.
