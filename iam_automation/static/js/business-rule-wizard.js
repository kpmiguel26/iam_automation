(function () {
  "use strict";

  var wizardMemory = {
    fields: {},
    conditionMode: "",
    conditionJson: ""
  };

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

  function setRequired(control, required) {
    if (!control) return;
    control.required = Boolean(required);
  }

  function syncOperandRequirements(row) {
    var operator = row.querySelector('[data-condition-operator]')?.value || '';
    var leftKind = row.querySelector('[data-condition-left-kind]');
    var rightKind = row.querySelector('[data-condition-right-kind]');
    var leftField = row.querySelector('[data-condition-left-field] select[data-condition-field-select]');
    var leftSource = row.querySelector('[data-condition-left-field] select[data-condition-field-source]');
    var leftLiteral = row.querySelector('[data-condition-left-literal] input');
    var leftDerived = row.querySelectorAll('[data-condition-left-derived]');
    var rightField = row.querySelector('[data-condition-right-field] select[data-condition-field-select]');
    var rightSource = row.querySelector('[data-condition-right-field] select[data-condition-field-source]');
    var rightLiteral = row.querySelector('[data-condition-right-literal] input');

    var leftIsField = leftKind && leftKind.value === 'field';
    var leftIsLiteral = leftKind && leftKind.value === 'literal';
    var leftIsDerived = leftKind && leftKind.value === 'derived';
    var rightIsField = rightKind && rightKind.value === 'field';
    var rightIsLiteral = rightKind && rightKind.value === 'literal';

    setRequired(leftField, leftIsField);
    setRequired(leftSource, leftIsField);
    setRequired(leftLiteral, leftIsLiteral);
    var noRightValue = operator === 'exists' || operator === 'missing';
    setRequired(rightField, rightIsField && !noRightValue);
    setRequired(rightSource, rightIsField && !noRightValue);
    setRequired(rightLiteral, rightIsLiteral && !noRightValue);

    leftDerived.forEach(function (container) {
      container.querySelectorAll('select, input').forEach(function (control) { setRequired(control, false); });
    });
    if (leftIsDerived) {
      var functionControl = row.querySelector('[name="condition_left_function"]');
      var firstKind = row.querySelector('[name="condition_left_arg1_kind"]');
      var firstIsField = firstKind && firstKind.value === 'field';
      var firstComplete = Boolean(firstKind && ((firstIsField && row.querySelector('[name="condition_left_arg1_field"]')?.value) || (!firstIsField && row.querySelector('[name="condition_left_arg1_value"]')?.value.trim())));
      var secondKind = row.querySelector('[name="condition_left_arg2_kind"]');
      var secondIsField = secondKind && secondKind.value === 'field';
      setRequired(functionControl, true);
      setRequired(firstKind, Boolean(functionControl && functionControl.value));
      setRequired(row.querySelector('[name="condition_left_arg1_source"]'), Boolean(functionControl && functionControl.value && firstIsField));
      setRequired(row.querySelector('[name="condition_left_arg1_field"]'), Boolean(functionControl && functionControl.value && firstIsField));
      setRequired(row.querySelector('[name="condition_left_arg1_value"]'), Boolean(functionControl && functionControl.value && !firstIsField));
      setRequired(secondKind, Boolean(functionControl && functionControl.value && firstComplete));
      setRequired(row.querySelector('[name="condition_left_arg2_source"]'), Boolean(firstComplete && secondIsField));
      setRequired(row.querySelector('[name="condition_left_arg2_field"]'), Boolean(firstComplete && secondIsField));
      setRequired(row.querySelector('[name="condition_left_arg2_value"]'), Boolean(firstComplete && !secondIsField));
    }
    setRequired(row.querySelector('[name="condition_operator"]'), true);
    setRequired(leftKind, true);
    setRequired(rightKind, !noRightValue);
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
    var conditionField = form.querySelector('[data-condition-json]');
    if (conditionField && !conditionField.value && wizardMemory.conditionJson) conditionField.value = wizardMemory.conditionJson;
    if (preview) preview.textContent = generated;
    if (hidden) hidden.value = generated;
  }

  function syncConditionRow(row) {
    if (!row) return;
    row.querySelectorAll('[data-condition-field-source]').forEach(function (source) {
      var field = row.querySelector('[data-condition-field-select][name="' + source.name.replace('_source', '_field') + '"]');
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
    var operator = row.querySelector('[data-condition-operator]');
    if (operator) {
      var allowedForCalculated = ['equals', 'not_equals', 'greater_than', 'less_than', 'between'];
      var calculated = leftKind && leftKind.value === 'derived';
      operator.querySelectorAll('option[value]').forEach(function (option) {
        option.hidden = calculated && allowedForCalculated.indexOf(option.value) === -1;
      });
      if (calculated && operator.selectedOptions[0]?.hidden) operator.value = '';
    }
    leftField.forEach(function (item) { item.hidden = !leftKind || leftKind.value !== 'field'; });
    if (leftLiteral) leftLiteral.hidden = !leftKind || leftKind.value !== 'literal';
    leftDerived.forEach(function (item) { item.hidden = !leftKind || leftKind.value !== 'derived'; });
    var derivedHelp = row.querySelector('[data-condition-derived-help]');
    if (derivedHelp) derivedHelp.hidden = !leftKind || leftKind.value !== 'derived';
    rightField.forEach(function (item) { item.hidden = !rightKind || rightKind.value !== 'field'; });
    if (rightLiteral) rightLiteral.hidden = !rightKind || rightKind.value !== 'literal';
    syncRightOperand(row);
    syncDerivedGuidance(row);
    syncOperandRequirements(row);
  }

  function syncDerivedGuidance(row) {
    var derived = row.querySelector('[data-condition-left-derived]');
    var leftKind = row.querySelector('[data-condition-left-kind]');
    if (!derived) return;
    if (!leftKind || leftKind.value !== 'derived') {
      derived.querySelectorAll('[data-condition-derived-step]').forEach(function (step) { step.hidden = false; });
      return;
    }
    var functionSelect = derived.querySelector('[name="condition_left_function"]');
    var arg1Kind = derived.querySelector('[name="condition_left_arg1_kind"]');
    var arg1IsField = arg1Kind && arg1Kind.value === 'field';
    var arg1Complete = Boolean(arg1Kind && ((arg1IsField && derived.querySelector('[name="condition_left_arg1_field"]')?.value) || (!arg1IsField && derived.querySelector('[name="condition_left_arg1_value"]')?.value.trim())));
    var arg2Kind = derived.querySelector('[name="condition_left_arg2_kind"]');
    var arg2IsField = arg2Kind && arg2Kind.value === 'field';
    var dateFunction = functionSelect && functionSelect.value === 'business_days_between';
    [1, 2].forEach(function (number) {
      var value = derived.querySelector('[name="condition_left_arg' + number + '_value"]');
      if (value && dateFunction) {
        value.type = 'date';
        value.placeholder = 'Choose a date';
      }
    });
    var steps = {
      'function': Boolean(functionSelect && functionSelect.value),
      'arg1-kind': Boolean(functionSelect && functionSelect.value),
      'arg1-source': Boolean(functionSelect && functionSelect.value && arg1IsField),
      'arg1-field': Boolean(functionSelect && functionSelect.value && arg1IsField),
      'arg1-value': Boolean(functionSelect && functionSelect.value && !arg1IsField),
      'arg2-kind': arg1Complete,
      'arg2-source': Boolean(arg1Complete && arg2IsField),
      'arg2-field': Boolean(arg1Complete && arg2IsField),
      'arg2-value': Boolean(arg1Complete && !arg2IsField)
    };
    derived.querySelectorAll('[data-condition-derived-step]').forEach(function (step) {
      step.hidden = !steps[step.dataset.conditionDerivedStep];
    });
  }

  function syncRightOperand(row) {
    var operator = row.querySelector('[data-condition-operator]');
    var rightKind = row.querySelector('[data-condition-right-kind]');
    var rightKindWrap = row.querySelector('[data-condition-right-kind-wrap]');
    var rightField = row.querySelectorAll('[data-condition-right-field]');
    var rightLiteral = row.querySelector('[data-condition-right-literal]');
    var rightValue = row.querySelector('[data-condition-right-value]');
    var noValue = row.querySelector('[data-condition-no-right-value]');
    var help = row.querySelector('[data-condition-right-help]');
    var operatorHelp = row.querySelector('[data-condition-operator-help]');
    var rightTitle = row.querySelector('[data-condition-right-title]');
    var rightDescription = row.querySelector('[data-condition-right-description]');
    var rightValueLabel = row.querySelector('[data-condition-right-value-label]');
    var leftIsDerived = row.querySelector('[data-condition-left-kind]')?.value === 'derived';
    var value = operator && operator.value || '';
    var noRightValue = value === 'exists' || value === 'missing';
    var literalOnly = ['contains', 'in', 'between'].indexOf(value) !== -1;
    var inputType = value === 'before' || value === 'after' ? 'date' : value === 'greater_than' || value === 'less_than' ? 'number' : 'text';
    if (literalOnly && rightKind) rightKind.value = 'literal';
    if (noRightValue && rightKind) rightKind.value = 'literal';
    if (rightKindWrap) rightKindWrap.hidden = noRightValue || literalOnly;
    rightField.forEach(function (item) { item.hidden = noRightValue || literalOnly || !rightKind || rightKind.value !== 'field'; });
    if (rightLiteral) rightLiteral.hidden = noRightValue || !rightKind || rightKind.value !== 'literal';
    if (noValue) noValue.hidden = !noRightValue;
    if (rightValue) {
      rightValue.type = inputType;
      rightValue.placeholder = value === 'in' ? 'Options separated by commas' : value === 'between' ? 'Minimum, maximum (for example: 10, 30)' : inputType === 'date' ? 'Choose a date' : inputType === 'number' ? 'Enter a number' : 'Enter text to compare';
      rightValue.title = rightValue.placeholder;
    }
    if (help) help.textContent = value === 'in' ? 'Use commas for multiple options.' : value === 'between' ? 'Enter the lower and upper values separated by a comma.' : inputType === 'date' ? 'The comparison uses a calendar date.' : '';
    if (operatorHelp) operatorHelp.textContent = noRightValue ? 'This check only inspects whether the field has a value.' : literalOnly ? 'This comparison uses a fixed value.' : 'Choose a fixed value or another report field.';
    if (rightTitle) rightTitle.textContent = leftIsDerived ? 'Expected result' : 'Compare against';
    if (rightDescription) rightDescription.textContent = leftIsDerived ? 'Compare the number produced by the calculation.' : 'Use a fixed value or another field.';
    if (rightValueLabel) rightValueLabel.textContent = leftIsDerived ? 'Expected result' : 'Value';
  }

  function setControlValue(root, selector, value) {
    var control = root.querySelector(selector);
    if (!control || value === undefined || value === null) return;
    control.value = Array.isArray(value) ? value.join(', ') : String(value);
  }

  function captureWizardForm(form) {
    if (!form || !form.matches('[data-wizard-form]')) return;
    var captured = {};
    new FormData(form).forEach(function (value, name) {
      if (name === 'csrf_token') return;
      if (!captured[name]) captured[name] = [];
      captured[name].push(String(value));
    });
    Object.keys(captured).forEach(function (name) { wizardMemory.fields[name] = captured[name]; });
    if (captured.condition_mode && captured.condition_mode[0]) wizardMemory.conditionMode = captured.condition_mode[0];
    if (captured.condition_json && captured.condition_json[0]) wizardMemory.conditionJson = captured.condition_json[0];
  }

  function ensureConditionRows(form, count) {
    var rows = form && form.querySelector('[data-condition-rows]');
    var addButton = form && form.querySelector('[data-add-condition-row]');
    while (rows && rows.children.length < count && addButton) addConditionRow(addButton);
  }

  function restoreWizardForm(form) {
    if (!form || !form.matches('[data-wizard-form]')) return;
    var fields = wizardMemory.fields || {};
    ensureConditionRows(form, (fields.condition_operator || []).length);
    Object.keys(fields).forEach(function (name) {
      var values = fields[name];
      form.querySelectorAll('[name="' + name + '"]').forEach(function (control, index) {
        if (control.type === 'checkbox' || control.type === 'radio') {
          control.checked = values.indexOf(control.value) !== -1;
        } else if (control.tagName === 'SELECT' && control.multiple) {
          Array.from(control.options).forEach(function (option) { option.selected = values.indexOf(option.value) !== -1; });
        } else if (values[index] !== undefined) {
          control.value = values[index];
        } else if (index === 0) {
          control.value = values[0] || '';
        }
      });
    });
  }

  function hydrateOperand(row, side, operand) {
    if (!operand || typeof operand !== 'object') return;
    var kindSelector = side === 'left' ? '[data-condition-left-kind]' : '[data-condition-right-kind]';
    var kind = String(operand.kind || 'literal');
    setControlValue(row, kindSelector, kind);
    if (kind === 'field') {
      setControlValue(row, '[name="condition_' + side + '_source"]', operand.source || '');
      syncConditionRow(row);
      setControlValue(row, '[name="condition_' + side + '_field"]', operand.field || '');
      return;
    }
    if (kind === 'literal') {
      setControlValue(row, '[name="condition_' + side + '_value"]', operand.value);
      return;
    }
    if (kind === 'derived' && side === 'left') {
      setControlValue(row, '[name="condition_left_function"]', operand.function || '');
      (operand.arguments || []).slice(0, 2).forEach(function (argument, index) {
        var number = index + 1;
        setControlValue(row, '[name="condition_left_arg' + number + '_kind"]', argument.kind || 'literal');
        if (argument.kind === 'field') {
          setControlValue(row, '[name="condition_left_arg' + number + '_source"]', argument.source || '');
          syncConditionRow(row);
          setControlValue(row, '[name="condition_left_arg' + number + '_field"]', argument.field || '');
        } else {
          setControlValue(row, '[name="condition_left_arg' + number + '_value"]', argument.value);
        }
      });
    }
  }

  function hydrateExplicitCondition(root) {
    var scope = root || document;
    var form = scope.querySelector('[data-condition-form]');
    var mode = form && form.querySelector('[data-condition-mode]');
    var jsonField = form && form.querySelector('[data-condition-json]');
    if (!form || !mode || mode.value !== 'explicit' || !jsonField || !jsonField.value || form.dataset.conditionHydrated === 'true') return;
    var condition;
    try { condition = JSON.parse(jsonField.value); } catch (error) { return; }
    var group = condition.all || condition.any;
    if (!Array.isArray(group) || !group.length) return;
    form.dataset.conditionHydrated = 'true';
    setControlValue(form, '[name="condition_group"]', condition.all ? 'all' : 'any');
    var rows = form.querySelector('[data-condition-rows]');
    var addButton = form.querySelector('[data-add-condition-row]');
    while (rows && rows.children.length < group.length && addButton) addConditionRow(addButton);
    if (!rows) return;
    group.forEach(function (item, index) {
      var row = rows.children[index];
      if (!row) return;
      setControlValue(row, '[name="condition_operator"]', item.operator || '');
      hydrateOperand(row, 'left', item.left);
      hydrateOperand(row, 'right', item.right);
      syncConditionRow(row);
    });
  }

  function rememberWizardState(root) {
    var scope = root || document;
    var conditionJson = scope.querySelector('[data-condition-json]');
    var conditionMode = scope.querySelector('[data-condition-mode]');
    if (conditionJson && conditionJson.value) wizardMemory.conditionJson = conditionJson.value;
    if (conditionMode && conditionMode.value) wizardMemory.conditionMode = conditionMode.value;
    if (conditionJson && conditionJson.value) wizardMemory.fields.condition_json = [conditionJson.value];
    if (conditionMode && conditionMode.value) wizardMemory.fields.condition_mode = [conditionMode.value];
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
      if (!isExplicit) {
        var simpleField = simple.querySelector('select[name="field"]');
        var simpleOperator = simple.querySelector('input[name="operator"]');
        setRequired(simpleField, true);
        setRequired(simpleOperator, true);
        syncRuleValue(scope);
      }
    }
    if (explicit) explicit.hidden = !isExplicit;
    scope.querySelectorAll('[data-condition-row]').forEach(function (row) {
      syncConditionRow(row);
      if (!isExplicit) row.querySelectorAll('input, select, textarea').forEach(function (control) { control.required = false; });
    });
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
      var header = clone.querySelector('.condition-comparison-header');
      if (header) header.appendChild(remove);
    }
    remove.hidden = false;
    remove.setAttribute('aria-label', 'Remove comparison ' + (rows.children.length + 1));
    rows.appendChild(clone);
    syncConditionRow(clone);
    renumberConditionRows(rows);
  }

  function renumberConditionRows(rows) {
    if (!rows) return;
    Array.prototype.forEach.call(rows.children, function (row, index) {
      var number = row.querySelector('.condition-comparison-number');
      var heading = row.querySelector('.condition-comparison-header strong');
      var remove = row.querySelector('[data-remove-condition-row]');
      if (number) number.textContent = index + 1;
      if (heading) heading.textContent = 'Comparison ' + (index + 1);
      if (remove) {
        remove.hidden = index === 0;
        remove.setAttribute('aria-label', 'Remove comparison ' + (index + 1));
      }
    });
  }

  function prepareHelpLinks(root) {
    var scope = root || document;
    scope.querySelectorAll('#rule-wizard [data-wizard-form]').forEach(function (form) {
      form.dataset.noLoader = 'true';
      if (form.dataset.loadingMessage) {
        form.dataset.wizardLoadingMessage = form.dataset.loadingMessage;
        delete form.dataset.loadingMessage;
      }
    });
    scope.querySelectorAll('#rule-wizard a[href*="/help/business-rules"]').forEach(function (link) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    });
    scope.querySelectorAll('#rule-wizard [hx-get]').forEach(function (control) {
      control.dataset.wizardNavigation = 'true';
      if (!control.dataset.wizardLoadingMessage) control.dataset.wizardLoadingMessage = 'Loading the previous rule step…';
    });
  }

  function showWizardLoading(host, message) {
    if (!host || host.querySelector(':scope > .rule-wizard-local-loading')) return;
    host.classList.add('is-loading');
    var loading = document.createElement('div');
    loading.className = 'rule-wizard-local-loading';
    loading.setAttribute('role', 'status');
    loading.setAttribute('aria-live', 'polite');
    loading.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>' + (message || 'Loading…') + '</span>';
    host.appendChild(loading);
  }

  function hideWizardLoading(host) {
    if (!host) return;
    host.classList.remove('is-loading');
    var loading = host.querySelector(':scope > .rule-wizard-local-loading');
    if (loading) loading.remove();
  }

  function lockWizardForm(form) {
    if (!form || form.dataset.wizardSubmitting === 'true') return;
    form.dataset.wizardSubmitting = 'true';
    showWizardLoading(form, form.dataset.wizardLoadingMessage || 'Validating the rule…');
    form.querySelectorAll('[data-wizard-submit]').forEach(function (button) {
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
    });
  }

  function unlockWizardForm(form) {
    if (!form) return;
    form.dataset.wizardSubmitting = 'false';
    hideWizardLoading(form);
    form.querySelectorAll('[data-wizard-submit]').forEach(function (button) {
      button.disabled = false;
      button.removeAttribute('aria-disabled');
    });
  }

  function lockWizardNavigation(control) {
    if (!control || control.dataset.wizardNavigationSubmitting === 'true') return;
    control.dataset.wizardNavigationSubmitting = 'true';
    control.disabled = true;
    control.setAttribute('aria-disabled', 'true');
  }

  function unlockWizardNavigation(control) {
    if (!control) return;
    control.dataset.wizardNavigationSubmitting = 'false';
    control.disabled = false;
    control.removeAttribute('aria-disabled');
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-rule-operator]")) syncRuleValue(event.target.closest("form"));
    if (event.target.matches("[data-rule-name-form] select, [data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
    if (event.target.matches("[data-condition-mode]")) syncConditionEditor(event.target.closest("form"));
    if (event.target.matches("[data-condition-left-kind], [data-condition-right-kind], [data-condition-operator], [data-condition-field-source], [name^=condition_left_arg][name$=_kind]")) syncConditionRow(event.target.closest("[data-condition-row]"));
  });
  document.addEventListener("click", function (event) {
    if (event.target.matches("[data-add-condition-row]")) addConditionRow(event.target);
    if (event.target.matches("[data-remove-condition-row]")) {
      var row = event.target.closest('[data-condition-row]');
      if (row && row.parentElement && row.parentElement.children.length > 1) {
        var rows = row.parentElement;
        row.remove();
        renumberConditionRows(rows);
      }
    }
  });
  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-rule-name-form] input")) syncRuleName(event.target.closest("form"));
    if (event.target.matches("[data-condition-row] input")) syncConditionRow(event.target.closest("[data-condition-row]"));
  });
  document.addEventListener("submit", function (event) {
    if (event.target.matches("[data-rule-name-form]")) syncRuleName(event.target);
    if (event.target.matches("[data-wizard-form]")) {
      captureWizardForm(event.target);
      lockWizardForm(event.target);
    }
  });
  document.addEventListener("DOMContentLoaded", function () { syncRuleValue(document); syncRuleName(document); rememberWizardState(document); syncConditionEditor(document); hydrateExplicitCondition(document); restoreWizardForm(document.querySelector('[data-wizard-form]')); hydrateExplicitCondition(document); syncConditionEditor(document); syncRuleName(document); prepareHelpLinks(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { syncRuleValue(event.target); syncRuleName(event.target); rememberWizardState(event.target); syncConditionEditor(event.target); hydrateExplicitCondition(event.target); restoreWizardForm(event.target.querySelector && event.target.querySelector('[data-wizard-form]')); hydrateExplicitCondition(event.target); syncConditionEditor(event.target); syncRuleName(event.target); prepareHelpLinks(event.target); });
  document.body.addEventListener("htmx:configRequest", function (event) {
    var target = event.detail.elt;
    if (!target || !target.closest || !target.closest('#rule-wizard') || !event.detail || !event.detail.parameters) return;
    captureWizardForm(target.closest('[data-wizard-form]'));
    Object.keys(wizardMemory.fields || {}).forEach(function (name) {
      var values = wizardMemory.fields[name];
      event.detail.parameters[name] = values.length === 1 ? values[0] : values;
    });
    if (wizardMemory.conditionJson) event.detail.parameters.condition_json = wizardMemory.conditionJson;
    if (wizardMemory.conditionMode) event.detail.parameters.condition_mode = wizardMemory.conditionMode;
  });
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var target = event.detail && event.detail.elt;
    if (target && target.matches && target.matches('[data-wizard-navigation]')) {
      lockWizardNavigation(target);
      showWizardLoading(document.querySelector('#rule-wizard'), target.dataset.wizardLoadingMessage || 'Loading the previous rule step…');
    }
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    var form = event.detail && event.detail.elt && event.detail.elt.closest
      ? event.detail.elt.closest('[data-wizard-form]')
      : null;
    if (form) unlockWizardForm(form);
    var navigation = event.detail && event.detail.elt && event.detail.elt.matches && event.detail.elt.matches('[data-wizard-navigation]')
      ? event.detail.elt
      : null;
    if (navigation) {
      unlockWizardNavigation(navigation);
      hideWizardLoading(document.querySelector('#rule-wizard'));
    }
  });
}());
