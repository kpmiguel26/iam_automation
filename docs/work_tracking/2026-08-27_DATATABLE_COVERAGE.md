# DataTable coverage — 2026-08-27

## Objective

Standardize the tables rendered by the web application so users can search,
sort, paginate, view all loaded rows, copy, and export data without a CDN or a
second server process.

## Implementation

- DataTables 2.3.5, Bootstrap integration, Buttons and JSZip are served from
  `iam_automation/static/vendor/datatables`.
- `iam_automation/static/js/data-tables.js` initializes every flat table with a
  header and rectangular body rendered by the application.
- The shared controls provide 10, 25, 50, 100 and **All** page sizes, global
  table search, column sorting, Copy, CSV and Excel export.
- Existing page-specific filters remain authoritative for employee status,
  vendor, source, engagement, update window, source-import result and report
  definitions.
- Report Studio keeps its specialized column filters, date handling and export
  controls; the vendor libraries are now loaded once by the base template.

## Coverage and loading behavior

| Area | Table behavior |
| --- | --- |
| Employee directory | Existing server-side filters remain. `all=1` loads the complete matching set so DataTables can paginate, sort and export it locally. |
| Source updates | Files up to 1,000 rows load all observations automatically; larger files retain server pagination and offer an explicit “Load all rows” action. |
| Reports and new-hire readiness | Local DataTables controls and exports apply to the rendered report rows. |
| Requests and approval/publication queues | Search, sorting, pagination and exports apply to the rendered queue. |
| Administration, audit, identities and configuration previews | Search, sorting, pagination and exports apply to the rendered rows. |
| Expandable history/detail tables | Kept as ordinary HTML when the body uses `colspan`/detail rows, because those tables are not rectangular DataTables inputs. |

## Boundary

Client-side export includes the rows currently loaded in the page. For a
complete employee-directory export, use the directory’s `all=1` view first.
Large source files intentionally require an explicit load-all action to avoid
loading thousands of observations during normal navigation.

## Validation

- Python compilation: passed.
- Full regression suite: **161 passed**.
