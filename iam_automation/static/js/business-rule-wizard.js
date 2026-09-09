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

  function reportCode(label) {
    var words = String(label || "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .match(/[A-Za-z0-9]+/g) || [];
    return words.map(function (word) { return word.charAt(0).toUpperCase(); }).join("") || "[Report code]";
  }

  function buildRuleName(form) {
    var phase = (form.querySelector('input[name="phase"]') || {}).value || "[Execution phase]";
    var sourceSelect = form.querySelector('select[name="source_system"]');
    var sourceOption = sourceSelect && sourceSelect.options[sourceSelect.selectedIndex];
    var sourceKey = sourceOption && sourceOption.value || (form.querySelector('input[name="source_system"]') || {}).value;
    var sourceLabel = sourceOption && sourceOption.dataset.sourceLabel || form.dataset.ruleSourceLabel || sourceKey || "";
    var source = reportCode(sourceLabel);
    var fieldSelect = form.querySelector('select[name="field"]');
    var fieldOption = fieldSelect && fieldSelect.options[fieldSelect.selectedIndex];
    var field = fieldOption && fieldOption.value || (form.querySelector('input[name="field"]') || {}).value || "[Field affected]";
    var numberInput = form.querySelector('[data-rule-number]');
    var nameInput = form.querySelector('[data-rule-descriptive-name]');
    var rawNumber = numberInput && numberInput.value || "";
    var number = /^\d+$/.test(rawNumber) && Number(rawNumber) > 0
      ? String(Number(rawNumber)).padStart(3, "0")
      : "[number]";
    var name = nameInput && nameInput.value.trim() || "[name]";
    return [phase, source, number, field, name].join(" - ");
  }

  function syncRuleName(root) {
    var scope = root || document;
    var form = scope.matches && scope.matches('[data-rule-name-form]')
      ? scope
      : scope.querySelector('[data-rule-name-form]');
    if (!form) return;
    var generated = buildRuleName(form);
    var preview = form.querySelector('[data-rule-name-preview]');
    var hidden = form.querySelector('[data-rule-generated-name]');
    if (preview) preview.textContent = generated;
    if (hidden) hidden.value = generated;
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-rule-operator]")) syncRuleValue(event.target.closest("form"));
    if (event.target.matches("[data-rule-name-form] select, [data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
  });
  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
  });
  document.addEventListener("submit", function (event) {
    if (event.target.matches("[data-rule-name-form]")) syncRuleName(event.target);
  });
  document.addEventListener("DOMContentLoaded", function () { syncRuleValue(document); syncRuleName(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { syncRuleValue(event.target); syncRuleName(event.target); });
}());
