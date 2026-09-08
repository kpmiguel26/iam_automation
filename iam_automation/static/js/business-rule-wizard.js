(function () {
  "use strict";

  function syncRuleValue(root) {
    var scope = root || document;
    var group = scope.querySelector('[data-rule-value-group]');
    if (!group) return;
    var selected = scope.querySelector('[data-rule-operator]:checked');
    var value = group.querySelector('input[name="value"]');
    var help = group.querySelector('[data-rule-value-help]');
    var noValueNeeded = selected && (selected.value === "exists" || selected.value === "missing");
    group.hidden = Boolean(noValueNeeded);
    if (value) {
      value.required = !noValueNeeded;
      if (noValueNeeded) value.value = "";
    }
    if (help && selected) {
      help.textContent = selected.value === "in"
        ? "Enter several options separated by commas."
        : "Enter the value the report should be compared with.";
    }
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-rule-operator]")) syncRuleValue(event.target.closest("form"));
  });
  document.addEventListener("DOMContentLoaded", function () { syncRuleValue(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { syncRuleValue(event.target); });
}());
