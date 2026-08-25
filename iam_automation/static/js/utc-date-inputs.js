// -----------------------------------------------------------------------------
// File: iam_automation/static/js/utc-date-inputs.js
// Purpose: Provides the utc-date-inputs component of IAM Automation.
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

(() => {
  document.querySelectorAll("form[data-utc-date-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const startDate = form.querySelector("[data-start-date]");
      const expiryDate = form.querySelector("[data-expiry-date]");
      const startOutput = form.querySelector("[data-start-output]");
      const expiryOutput = form.querySelector("[data-expiry-output]");
      if (!startDate.value || !expiryDate.value) {
        event.preventDefault();
        return;
      }

      const now = new Date();
      const pad = (value) => String(value).padStart(2, "0");
      const startTime = `${pad(now.getHours())}:${pad(now.getMinutes())}:00`;
      const start = new Date(`${startDate.value}T${startTime}`);
      const expiry = new Date(`${expiryDate.value}T23:59:59`);
      if (Number.isNaN(start.getTime()) || Number.isNaN(expiry.getTime()) || expiry <= start) {
        event.preventDefault();
        expiryDate.setCustomValidity("Expiration date must be after the start date.");
        expiryDate.reportValidity();
        return;
      }
      expiryDate.setCustomValidity("");
      startOutput.value = start.toISOString().replace("Z", "+00:00");
      expiryOutput.value = expiry.toISOString().replace("Z", "+00:00");
    });
  });
})();
// #endfile
