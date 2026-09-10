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

  function syncConditionRow(row) {
    if (!row) return;
    row.querySelectorAll('[data-condition-field-source]').forEach(function (source) {
      var field = source.closest('.row')?.querySelector('[data-condition-field-select][name="' + source.name.replace('_source', '_field') + '"]');
      if (!field) field = source.parentElement.parentElement.querySelector('[data-condition-field-select]');
      if (!field) return;
      var selected = field.value;
      field.querySelectorAll('option[data-condition-source]').forEach(function (option) {
        option.hidden = option.dataset.conditionSource !== source.value;
      });
      if (!field.value || field.selectedOptions[0]?.hidden) {
        var first = field.querySelector('option[data-condition-source="' + source.value + '"]:not([hidden])');
        if (first) field.value = first.value;
      }
    });
    var leftKind = row.querySelector('[data-condition-left-kind]');
    var rightKind = row.querySelector('[data-condition-right-kind]');
    var leftField = row.querySelectorAll('[data-condition-left-field]');
    var leftLiteral = row.querySelector('[data-condition-left-literal]');
    var leftDerived = row.querySelectorAll('[data-condition-left-derived]');
    var rightField = row.querySelectorAll('[data-condition-right-field]');
    var rightLiteral = row.querySelector('[data-condition-right-literal]');
    leftField.forEach(function (item) { item.hidden = !leftKind || leftKind.value !== 'field'; });
    if (leftLiteral) leftLiteral.hidden = !leftKind || leftKind.value !== 'literal';
    leftDerived.forEach(function (item) { item.hidden = !leftKind || leftKind.value !== 'derived'; });
    rightField.forEach(function (item) { item.hidden = !rightKind || rightKind.value !== 'field'; });
    if (rightLiteral) rightLiteral.hidden = !rightKind || rightKind.value !== 'literal';
  }

  function syncConditionEditor(root) {
    var scope = root || document;
    var mode = scope.querySelector('[data-condition-mode]');
    var simple = scope.querySelector('[data-simple-condition]');
    var explicit = scope.querySelector('[data-explicit-condition]');
    var isExplicit = mode && mode.value === 'explicit';
    if (simple) {
      simple.hidden = isExplicit;
      simple.querySelectorAll('input, select, textarea').forEach(function (control) {
        control.disabled = isExplicit;
        if (isExplicit) control.required = false;
      });
      if (!isExplicit) syncRuleValue(scope);
    }
    if (explicit) explicit.hidden = !isExplicit;
    scope.querySelectorAll('[data-condition-row]').forEach(syncConditionRow);
  }

  function addConditionRow(button) {
    var builder = button && button.closest('[data-explicit-condition]');
    var rows = builder && builder.querySelector('[data-condition-rows]');
    var source = rows && rows.querySelector('[data-condition-row]');
    if (!rows || !source) return;
    var clone = source.cloneNode(true);
    clone.querySelectorAll('input').forEach(function (input) { input.value = ''; });
    clone.querySelectorAll('select').forEach(function (select) { select.selectedIndex = 0; });
    var heading = clone.querySelector('strong');
    if (heading) heading.textContent = 'Comparison ' + (rows.children.length + 1);
    var remove = clone.querySelector('[data-remove-condition-row]');
    if (!remove) {
      remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn btn-sm btn-link text-danger p-0';
      remove.textContent = 'Remove';
      remove.setAttribute('data-remove-condition-row', '');
      var header = clone.querySelector('.d-flex');
      if (header) header.appendChild(remove);
    }
    rows.appendChild(clone);
    syncConditionRow(clone);
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-rule-operator]")) syncRuleValue(event.target.closest("form"));
    if (event.target.matches("[data-rule-name-form] select, [data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
    if (event.target.matches("[data-condition-mode]")) syncConditionEditor(event.target.closest("form"));
    if (event.target.matches("[data-condition-left-kind], [data-condition-right-kind], [data-condition-field-source]")) syncConditionRow(event.target.closest("[data-condition-row]"));
  });
  document.addEventListener("click", function (event) {
    if (event.target.matches("[data-add-condition-row]")) addConditionRow(event.target);
    if (event.target.matches("[data-remove-condition-row]")) {
      var row = event.target.closest('[data-condition-row]');
      if (row && row.parentElement && row.parentElement.children.length > 1) row.remove();
    }
  });
  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
  });
  document.addEventListener("submit", function (event) {
    if (event.target.matches("[data-rule-name-form]")) syncRuleName(event.target);
  });
  document.addEventListener("DOMContentLoaded", function () { syncRuleValue(document); syncRuleName(document); syncConditionEditor(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { syncRuleValue(event.target); syncRuleName(event.target); syncConditionEditor(event.target); });
}());
