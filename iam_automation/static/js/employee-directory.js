// -----------------------------------------------------------------------------
// File: iam_automation/static/js/employee-directory.js
// Purpose: Provides the employee-directory component of IAM Automation.
// Responsibilities: Provides the file-level implementation used by the application.
// Dependencies: Browser DOM APIs and application markup/data attributes.
// Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
// Author: Miguel Fernandez.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
// -----------------------------------------------------------------------------

(function () {
  "use strict";

  function initEmployeeDirectory() {
    var search = document.querySelector("[data-employee-search]");
    var status = document.querySelector("[data-employee-status]");
    var vendor = document.querySelector("[data-employee-vendor]");
    var reset = document.querySelector("[data-employee-reset]");
    var rows = Array.prototype.slice.call(document.querySelectorAll("[data-employee-row]"));
    var empty = document.getElementById("employeeNoMatches");
    var count = document.getElementById("employeeResultCount");
    var summary = document.getElementById("employeeFilterSummary");

    if (!search || !status || !vendor || !rows.length) return;

    function applyFilters() {
      var query = search.value.trim().toLowerCase();
      var selectedStatus = status.value;
      var selectedVendor = vendor.value;
      var visible = 0;
      rows.forEach(function (row) {
        var matchesQuery = !query || row.dataset.search.indexOf(query) !== -1;
        var matchesStatus = selectedStatus === "ALL" || row.dataset.status === selectedStatus;
        var matchesVendor = selectedVendor === "ALL" || row.dataset.vendor === selectedVendor;
        var show = matchesQuery && matchesStatus && matchesVendor;
        row.classList.toggle("d-none", !show);
        if (show) visible += 1;
      });
      if (empty) empty.classList.toggle("d-none", visible !== 0);
      if (count) count.textContent = visible;
      if (summary) {
        var activeFilters = [];
        if (query) activeFilters.push('matching “' + search.value.trim() + '”');
        if (selectedStatus !== "ALL") activeFilters.push(selectedStatus.replaceAll("_", " ").toLowerCase());
        if (selectedVendor !== "ALL") activeFilters.push(selectedVendor);
        summary.textContent = activeFilters.length ? "Showing employees " + activeFilters.join(" · ") : "Showing all canonical employees";
      }
    }

    search.addEventListener("input", applyFilters);
    status.addEventListener("change", applyFilters);
    vendor.addEventListener("change", applyFilters);
    if (reset) reset.addEventListener("click", function () {
      search.value = "";
      status.value = "ALL";
      vendor.value = "ALL";
      applyFilters();
      search.focus();
    });
    applyFilters();
  }

  document.addEventListener("DOMContentLoaded", initEmployeeDirectory);
})();
// #endfile
