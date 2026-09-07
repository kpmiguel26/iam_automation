# IW-001 — Import workflow refresh race and Close scroll

Status: Implemented and verified locally; Windows acceptance pending.
Branch: `fix/import-workflow-refresh-scroll` (includes `5cd07c6`).

## Problem and correction

On `/employees/source-updates`, the ten-second timeline poll only checked for
an import when issuing its request. A response requested just before Import
could still replace the timeline while the POST was staging the workbook.

The workflow now synchronizes Import with the timeline request, cancels an
outstanding refresh and rejects stale timeline responses while a POST or an
unacknowledged task result exists. A guard before HTMX synchronization prevents
a second Import from aborting the first. Task progress polling remains active.
The actual submit button is disabled during preparation, and the generic form
loader is excluded so this operation uses its inline indicator consistently.

Close replaces the timeline only on explicit acknowledgement. After HTMX
settles the new layout, it focuses the workflow heading without browser focus
scrolling and positions the timeline 24 pixels below the viewport top. The
request uses the timeline's current URL to retain Needs attention/Recent files.
The already-imported message now has a working inline Close action instead of
attempting to dismiss a nonexistent Bootstrap modal.

## Verification

- `node --test tests/test_source_import_workflow.cjs`: 6 passed. Covers late
  responses, concurrent submissions, task/result retention, Close/view/scroll,
  failed-POST retry and background refresh without focus or scroll changes.
- `.venv/bin/python -m pytest tests/test_webapp.py -q`: 11 passed, 1 skipped.
- Chromium via Playwright CLI, using the production partials, bundled HTMX and
  new controller against a loopback Flask fixture with synthetic data:
  refresh delayed two seconds; import preparation delayed three seconds;
  task completion after five seconds; result retained for another eleven
  seconds. The submit button and indicator remained active during preparation;
  Close removed the result and positioned the timeline at 24px with heading
  focus. Expected HTMX request-abort messages accompanied the cancelled poll.
- The fixture does not access the runtime database or SharePoint. Browser
  verification was on macOS Chromium, not native Windows or OneDrive timing.

## Windows acceptance

1. Stop IAM Automation in the launcher, fetch and switch to this branch, and
   pull with `--ff-only`. Start the app and reload Source updates with Ctrl+F5.
2. Import a pending file, preferably one that takes longer than ten seconds.
   Preparation/progress must remain visible; repeated clicks must not start
   another import. The result must remain until Close is clicked.
3. Scroll down through a long result, then Close. The workflow should return
   near the top of the viewport instead of jumping to the page footer.
4. Repeat in Recent 25 files; Close must retain that view. Verify a subsequent
   pending file can still be imported and background refresh resumes.
