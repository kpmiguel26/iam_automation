# Template Creation, Library, and Object Template Review

**Review date:** 2026-10-01
**Scope:** Report-template creation and validation, Template Library version lifecycle, and Object Template configuration and approval.

## Summary

The primary report-template workflow has a useful validation gate: sample diagnostics block saving when they contain blocking issues, and a content digest ties later approval to the exact validated definition. Approval is also checked again in the repository.

The main lifecycle gap is in Object Template configuration. The editor builds its choices from the latest version of every report template, including drafts, but Object Template approval requires each referenced report version to be approved. This lets an administrator save an Object Template draft that cannot pass approval until the report template is approved and the Object Template is saved again.

## Findings

### P1 — Object Template accepts report drafts that cannot be approved

`card_context()` builds Object Template sources, properties, and identifiers from `list_template_cards()` without filtering on report-template status (`iam_automation/interfaces/web/ingestion_configuration_routes.py:115-157`). The library query returns the highest version number per source without restricting `status` (`iam_automation/application/ingestion/template_repository.py:30-47`). The Object Template page presents these choices as available sources without showing whether each source is a draft (`iam_automation/templates/admin/ingestion_object_template_settings.html:19-26`).

Saving the Object Template pins those selected source version IDs (`iam_automation/interfaces/web/ingestion_configuration_routes.py:730-733, 846-858`). The approval path only accepts approved report versions (`iam_automation/application/parallel_engine/templates.py:148-162`), so a selection made from a report draft produces a saved Object Template draft that approval rejects.

**Recommendation:** Offer only the latest approved report version as an Object Template source. If drafts must remain selectable for preview, label them clearly and disable saving/approval until the source is approved. Show the pinned report version and status in the Object Template review summary.

### P2 — A secondary report-template save route skips sample validation

The guided workflow validates the sample, blocks on blocking diagnostics, fingerprints the draft and sample selection, then requires the same fingerprint before saving (`iam_automation/interfaces/web/ingestion_configuration_routes.py:375-445`). However, the older root configuration POST still accepts `action=save` and calls `templates.save_draft()` after structural configuration checks only (`iam_automation/interfaces/web/ingestion_configuration_routes.py:487-528`). That route does not require a sample inspection or sample-validation fingerprint.

The library's later settings validation and approval checks still apply, but they do not re-run the sample diagnostics. A caller using this alternate POST path can therefore produce a report-template draft without the sample-based checks the guided creation page describes.

**Recommendation:** Route all draft persistence through one server-side validation service. If sample validation is a requirement, persist a validation record tied to the sample inspection and definition digest and require it before saving or approving; otherwise make the sample check explicitly advisory in the UI.

## Improvements

### Make object-form readiness visible before submission

The Object Template POST validates selected identifiers, Strong identifier links, graph connectivity, and object-creation authorization (`iam_automation/interfaces/web/ingestion_configuration_routes.py:742-829`). The page's Save button is disabled only when there are no source options (`iam_automation/templates/admin/ingestion_object_template_settings.html:39`). As a result, incomplete configurations can be submitted and discovered only after a full-page validation response.

Add a readiness summary beside the submit button that reports missing identifiers, missing Strong links, disconnected reports, and unmet object-creation authorization. Disable submission while those client-visible requirements are unmet, while keeping the server checks authoritative. Focus the first invalid field or error summary after rejection.

### Keep sample-upload state available across application workers

Uploaded sample bytes are stored in a blueprint-local in-memory dictionary with a 30-minute expiry (`iam_automation/interfaces/web/ingestion_configuration_routes.py:61, 269-283`). This works in a single process, but a later request handled by a different application worker cannot find the artifact and returns an expired-preview response. It also means process restarts discard in-progress samples.

If this application runs with multiple workers or restarts during configuration, move temporary sample artifacts to a shared, short-lived store keyed to the authenticated session, with size limits and automatic expiry.

### Clarify draft versus approved versions in the object workflow

The library clearly labels its current report-template version as Draft or Approved (`iam_automation/templates/admin/_ingestion_template_cards.html:27-29`), but the Object Template source and identity choices omit that status (`iam_automation/interfaces/web/ingestion_configuration_routes.py:124-156`). Carry the version number, status, and validation state into these choices so the user can understand which exact configuration an object will reference.

## Existing safeguards observed

- The guided sample-mapping save blocks on blocking preview diagnostics and detects edits made after validation (`iam_automation/interfaces/web/ingestion_configuration_routes.py:400-445`).
- Report-template approval requires a validation event matching the current definition digest; the repository repeats that check in its approval update (`iam_automation/interfaces/web/ingestion_configuration_routes.py:1041-1065`, `iam_automation/application/ingestion/template_repository.py:603-639`).
- Report-template settings validate the watcher folder under the configured SharePoint root, timezone values, temporal fields, skip rules, and overall draft configuration before saving (`iam_automation/interfaces/web/ingestion_configuration_routes.py:894-979`).
- Object Template approval rechecks pinned report status/version, watcher-folder availability, identity-link rules, and object-creation authorization (`iam_automation/application/parallel_engine/templates.py:120-220`).
- Successful report-template and Object Template saves redirect to Template Library (`iam_automation/interfaces/web/ingestion_configuration_routes.py:457-463, 980-981, 858-864`).

## Review limits

This review covers the configuration routes, repositories, runtime catalog, and associated templates. The follow-up implementation moved Object Template approval into its configuration page and now offers only the latest approved report version as a source. The alternate report-template save route and the multi-worker sample-upload limitation remain open. No tests or browser walkthrough were run.

## Follow-up implementation — 2026-10-01

- **P1 addressed:** Object Template source, property, and identity choices now come from the latest approved report version. Stale source versions must be refreshed or removed before saving.
- **Approval moved to the library:** The Object Template page validates and saves the draft, then returns to Template Library. An Application Admin or Master Admin can approve that saved snapshot from its Object Template accordion. Approval still rechecks source versions, watcher folders, identity links, and object-creation authorization. The engine dashboard no longer offers Object Template approval; runtime loads the approved snapshot.
- **Status surfaced:** Template Library and Object Template settings identify the latest Object Template version as draft or approved, including approver details when available.
- **P2 remains open:** The alternate report-template POST can still save without sample validation. Temporary sample uploads also remain process-local.
