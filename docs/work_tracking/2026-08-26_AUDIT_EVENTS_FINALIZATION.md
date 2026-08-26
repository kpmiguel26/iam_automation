# Audit Events Finalization

**Status:** Backlog  
**Priority:** 1  
**Owner:** Miguel Fernandez  
**Target:** 2026-09-11  
**Estimate:** 8 hours  
**Planned branch:** `feature/audit-events-finalization`

## Objective

Complete audit-event coverage for the IAM administrative and worker-history flows so every meaningful success and failure is traceable without modifying append-only evidence.

## Scope

- Review `audit.py`, `audit_service.py`, administrative routes and existing audit tests.
- Ensure events capture actor, role, team/context, action, entity, outcome, timestamp and correlation ID.
- Cover successful, rejected, unauthorized and failed operations, including duplicate merge events.
- Confirm retention and archive behavior with the approved policy.

## Dependencies

- Final audit and retention rules.
- Correlation-ID conventions used by the application.
- Merge event contract from the canonical-profile merge feature.

## Tasks

- Inventory existing event types and identify uncovered routes/services.
- Define required metadata and stable event names.
- Add missing success/error audit writes and automated tests.
- Verify append-only behavior and evidence retention.
- Update the relevant administrator/audit guide.

## Acceptance criteria

- Each in-scope operation emits an event with actor, action, entity, result, timestamp and correlation ID.
- Unauthorized and validation failures are auditable without exposing sensitive data.
- Existing events remain readable and append-only.
- Retention/archive tests demonstrate that required evidence is not deleted.

## Test cases

- Successful administrative change.
- Unauthorized request and rejected validation.
- Failed publication/export with recovery details.
- Duplicate merge event linked to both source and surviving profiles.
- Archive/retention operation preserves required evidence.

## Risks and decisions pending

- Stakeholders must confirm legal-hold and retention exceptions.
- Event naming changes may affect reports or downstream audit consumers.
