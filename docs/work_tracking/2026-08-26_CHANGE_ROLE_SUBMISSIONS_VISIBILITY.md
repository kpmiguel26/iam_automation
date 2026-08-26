# Change-Role Submission Visibility

**Status:** Backlog  
**Priority:** 1  
**Owner:** Miguel Fernandez  
**Target:** 2026-09-04  
**Estimate:** 10 hours  
**Planned branch:** `feature/change-role-submission-visibility`

## Objective

Allow authorized administrators to find and review change-role submissions using operational filters and linked approval/audit evidence.

## Scope

- Review `change_request.py`, `request_service.py`, administrative routes/templates and `master_audit.html`.
- Define visible states and permitted transitions.
- Support filtering by user, employee, role, date and status.
- Link each submission to its decision and audit events.
- Preserve existing authorization and export/query behavior.

## Dependencies

- Approved request-state vocabulary and permission matrix.
- Existing approval, delegation and SLA behavior.
- Final audit-event metadata.

## Tasks

- Confirm search fields, filters and result ordering.
- Add service/query support and administrative presentation.
- Show request details, decision notes and audit references.
- Enforce role-based access in routes and service methods.
- Add focused unit, authorization and route tests.

## Acceptance criteria

- Authorized users can locate submissions by all agreed filters.
- Results show current state, requester/employee/role, dates and decision context.
- Unauthorized users cannot enumerate or inspect restricted submissions.
- Every displayed decision links to auditable evidence.

## Test cases

- Filter by each supported field and combined filters.
- Empty, invalid and date-bound searches.
- Authorized administrator versus unauthorized user.
- Pending, approved, rejected, expired and delegated requests.
- Query/export result matches the underlying request records.

## Risks and decisions pending

- State names and visibility rules must be approved before UI completion.
- Large result sets may require pagination or bounded queries.
