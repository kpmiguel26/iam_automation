(function () {
  'use strict';

  function openLibraryModal(target) {
    if (!target) return;
    var modalElement = target.querySelector('#deleteReportTemplateModal');
    if (!modalElement || modalElement.dataset.libraryModalOpened === 'true') return;
    modalElement.dataset.libraryModalOpened = 'true';
    if (window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }
  }

  function syncFolderPicker(picker) {
    if (!picker) return;
    var parent = picker.querySelector('[name="folder_parent_path"]:checked');
    var name = picker.querySelector('[data-folder-child-name]');
    var output = picker.querySelector('[data-folder-create-path]');
    var preview = picker.querySelector('[data-folder-create-preview]');
    if (!name || !output) return;
    var childName = name.value.trim();
    var parentPath = parent ? parent.value.trim() : '';
    output.value = childName ? [parentPath, childName].filter(Boolean).join('/') : '';
    output.disabled = !childName;
    if (preview) {
      preview.textContent = childName
        ? 'New folder path: ' + output.value
        : 'Choose a parent and enter a name to create a folder.';
    }
  }

  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target ? event.detail.target : event.target;
    if (!target || target.id !== 'template-modal-region') return;
    openLibraryModal(target);
  });

  var modalRegion = document.getElementById('template-modal-region');
  if (modalRegion && window.MutationObserver) {
    new MutationObserver(function () { openLibraryModal(modalRegion); })
      .observe(modalRegion, {childList: true});
  }

  function syncTimezoneMode(root) {
    if (!root) return;
    var mode = root.querySelector('[data-timezone-mode]');
    if (!mode) return;
    root.querySelectorAll('[data-custom-timezone]').forEach(function (input) {
      input.disabled = mode.value !== 'CUSTOM';
      input.required = mode.value === 'CUSTOM';
    });
  }

  function syncObjectTemplate(root) {
    if (!root || !root.matches('#objectTemplateSettingsForm')) return;
    var sources = Array.from(root.querySelectorAll('[data-object-source]'));
    var selectedSources = new Set(sources.filter(function (input) { return input.checked; }).map(function (input) { return input.value; }));
    var selectedSourceInputs = sources.filter(function (input) { return input.checked; });
    var earliestSource = selectedSourceInputs.sort(function (left, right) {
      return Number(left.dataset.ingestionOrder || '2147483647') - Number(right.dataset.ingestionOrder || '2147483647');
    })[0] || null;
    var identities = Array.from(root.querySelectorAll('[data-object-identity]'));
    identities.forEach(function (input) {
      var sourceSelected = selectedSources.has(input.dataset.sourceId);
      input.disabled = !sourceSelected;
      if (!sourceSelected) input.checked = false;
    });
    var selectedStrong = identities.filter(function (input) { return input.checked && input.dataset.strength === 'STRONG'; });
    var selectedStrongRefs = new Set(selectedStrong.map(function (input) { return input.value; }));
    var strongSources = new Set(selectedStrong.map(function (input) { return input.dataset.sourceId; }));
    var matchGroups = Array.from(root.querySelectorAll('[data-object-match-group]'));
    matchGroups.forEach(function (group, groupIndex) {
      var sourceSelect = group.querySelector('[data-object-match-source]');
      var anchorSelect = group.querySelector('[data-object-match-anchor]');
      if (!sourceSelect || !anchorSelect) return;
      Array.from(sourceSelect.options).forEach(function (option) {
        if (option.value) {
          var mustStartAtFirst = groupIndex === 0 && selectedSources.size > 1;
          option.disabled = !selectedSources.has(option.value) || !strongSources.has(option.value) || (mustStartAtFirst && earliestSource && option.value !== earliestSource.value);
        }
      });
      if (sourceSelect.value && (!selectedSources.has(sourceSelect.value) || !strongSources.has(sourceSelect.value))) sourceSelect.value = '';
      var anchorSource = sourceSelect.value;
      Array.from(anchorSelect.options).forEach(function (option) {
        if (!option.value) return;
        var sourceId = option.dataset.sourceId || '';
        option.disabled = sourceId !== anchorSource || !selectedStrongRefs.has(option.value);
      });
      if (anchorSelect.value && (!selectedStrongRefs.has(anchorSelect.value) || !anchorSelect.selectedOptions[0] || anchorSelect.selectedOptions[0].dataset.sourceId !== anchorSource)) anchorSelect.value = '';
      var anchorChosen = Boolean(anchorSelect.value && anchorSource);
      group.querySelectorAll('[data-object-match-target]').forEach(function (input) {
        var sourceId = input.dataset.sourceId || '';
        var validTarget = anchorChosen && selectedSources.has(sourceId) && sourceId !== anchorSource && selectedStrongRefs.has(input.value);
        input.disabled = !validTarget;
        if (!validTarget) input.checked = false;
      });
      group.querySelectorAll('[data-object-match-target-report]').forEach(function (reportGroup) {
        var hasTarget = Array.from(reportGroup.querySelectorAll('[data-object-match-target]')).some(function (input) { return !input.disabled; });
        reportGroup.hidden = !hasTarget;
      });
    });
    var canLink = strongSources.size > 1;
    var addButton = root.querySelector('[data-add-object-match]');
    if (addButton) addButton.disabled = !canLink;
    var count = root.querySelector('[data-object-identifier-count]');
    if (count) {
      var selectedCount = identities.filter(function (input) { return input.checked; }).length;
      count.textContent = selectedCount + ' selected';
    }
    var empty = root.querySelector('[data-object-match-empty]');
    if (empty) empty.hidden = matchGroups.length > 0;

    var guidance = root.querySelector('[data-object-order-guidance]');
    if (guidance) {
      guidance.textContent = selectedSources.size > 1 && earliestSource
        ? 'The first link starts with ' + (earliestSource.dataset.sourceLabel || earliestSource.value) + ' · ingestion order ' + earliestSource.dataset.ingestionOrder + '. This is the earliest selected report in the saved ingestion plan.'
        : 'Select multiple report templates to see the required starting report.';
    }

    var preview = root.querySelector('[data-object-match-map-list]');
    var previewEmpty = root.querySelector('[data-object-match-map-empty]');
    if (preview && previewEmpty) {
      preview.replaceChildren();
      var adjacency = new Map();
      selectedSources.forEach(function (sourceId) { adjacency.set(sourceId, new Set()); });
      var configuredGroups = 0;
      matchGroups.forEach(function (group) {
        var anchor = group.querySelector('[data-object-match-anchor]');
        var targets = Array.from(group.querySelectorAll('[data-object-match-target]:checked'));
        var anchorOption = anchor && anchor.selectedOptions[0];
        if (!anchorOption || !anchorOption.value || !targets.length) return;
        configuredGroups += 1;
        var anchorSource = anchorOption.dataset.sourceId || '';
        targets.forEach(function (target) {
          var targetSource = target.dataset.sourceId || '';
          if (adjacency.has(anchorSource) && adjacency.has(targetSource)) {
            adjacency.get(anchorSource).add(targetSource);
            adjacency.get(targetSource).add(anchorSource);
          }
        });
        var item = document.createElement('li');
        var targetsText = targets.map(function (target) {
          return (target.dataset.sourceLabel || targetSourceName(target.dataset.sourceId)) + ' · ' + (target.dataset.fieldLabel || target.dataset.fieldKey);
        }).join('  ↔  ');
        item.textContent = (anchorOption.dataset.sourceLabel || targetSourceName(anchorSource)) + ' · ' + (anchorOption.dataset.fieldLabel || anchorOption.dataset.fieldKey) + '  ↔  ' + targetsText;
        preview.appendChild(item);
      });
      previewEmpty.hidden = configuredGroups > 0;
      var connectedCount = 0;
      if (earliestSource && adjacency.has(earliestSource.value)) {
        var visited = new Set();
        var frontier = [earliestSource.value];
        while (frontier.length) {
          var current = frontier.pop();
          if (visited.has(current)) continue;
          visited.add(current);
          (adjacency.get(current) || new Set()).forEach(function (next) { if (!visited.has(next)) frontier.push(next); });
        }
        connectedCount = visited.size;
      }
      var countSummary = root.querySelector('[data-object-match-map-summary]');
      if (!countSummary) {
        countSummary = document.createElement('p');
        countSummary.className = 'small fw-semibold mt-2 mb-0';
        countSummary.dataset.objectMatchMapSummary = '';
        preview.parentElement.appendChild(countSummary);
      }
      countSummary.textContent = configuredGroups + ' configured link group' + (configuredGroups === 1 ? '' : 's') + ' · ' + connectedCount + ' of ' + selectedSources.size + ' selected reports reachable from the first report.';
    }
  }

  function targetSourceName(sourceId) {
    var source = Array.from(document.querySelectorAll('#objectTemplateSettingsForm [data-object-source]')).find(function (item) { return item.value === sourceId; });
    return source ? (source.dataset.sourceLabel || sourceId) : sourceId;
  }

  function syncSkipRule(root) {
    if (!root) return;
    var field = root.querySelector('[data-skip-field]');
    if (!field) return;
    var enabled = Boolean(field.value);
    root.querySelectorAll('[data-skip-controls]').forEach(function (control) {
      control.hidden = !enabled;
    });
    root.querySelectorAll('[data-skip-condition], [data-skip-date]').forEach(function (input) {
      input.disabled = !enabled;
      input.required = enabled;
    });
  }

  function syncIdentityLimit(root) {
    if (!root || !root.matches('#templateSettingsForm')) return;
    var limitInput = root.querySelector('[name="identity_matching_limit"]');
    var feedback = root.querySelector('[data-identity-limit-count]');
    var saveButton = root.querySelector('button[type="submit"]');
    var rowList = root.querySelector('#identity-fields-list');
    var addButton = root.querySelector('[data-add-identity-field]');
    if (!limitInput || !feedback || !saveButton || !rowList) return;
    var limit = Number(limitInput.value);
    var validLimit = Number.isInteger(limit) && limit > 0;
    var rows = Array.from(rowList.querySelectorAll('[data-identity-row]'));
    if (validLimit && rows.length > limit) {
      rows.slice(limit).forEach(function (row) { row.remove(); });
      rows = Array.from(rowList.querySelectorAll('[data-identity-row]'));
    }
    var selectedCount = Array.from(rowList.querySelectorAll('select[name$="_key"]'))
      .filter(function (select) { return select.value.trim() !== ''; }).length;
    var overLimit = !validLimit || selectedCount > limit;
    feedback.textContent = selectedCount + ' selected · ' + rows.length + ' rows / ' + (validLimit ? limit : '—') + ' max';
    feedback.classList.toggle('text-danger', overLimit);
    feedback.classList.toggle('text-secondary', !overLimit);
    saveButton.disabled = overLimit;
    if (addButton) addButton.disabled = !validLimit || rows.length >= limit;
  }

  document.body.addEventListener('change', function (event) {
    if (event.target && event.target.matches('[name="folder_parent_path"]')) {
      syncFolderPicker(event.target.closest('[data-folder-picker]'));
    }
    if (event.target && event.target.matches('[name="folder_path"]')) {
      var picker = event.target.closest('[data-folder-picker]');
      var childName = picker && picker.querySelector('[data-folder-child-name]');
      if (childName) childName.value = '';
      syncFolderPicker(picker);
    }
    if (event.target && event.target.matches('[data-timezone-mode]')) {
      syncTimezoneMode(event.target.closest('#templateSettingsForm'));
    }
    if (event.target && event.target.matches('[data-skip-field]')) {
      syncSkipRule(event.target.closest('#templateSettingsForm'));
    }
    if (event.target && (event.target.matches('[name="identity_matching_limit"]') || event.target.matches('#identity-fields-list select[name$="_key"]'))) {
      syncIdentityLimit(event.target.closest('#templateSettingsForm'));
    }
    if (event.target && event.target.matches('[data-object-source], [data-object-identity], [data-object-match-source], [data-object-match-anchor], [data-object-match-target]')) {
      syncObjectTemplate(event.target.closest('#objectTemplateSettingsForm'));
    }
  });

  document.body.addEventListener('input', function (event) {
    if (event.target && event.target.matches('[data-folder-child-name]')) {
      syncFolderPicker(event.target.closest('[data-folder-picker]'));
    }
  });

  document.body.addEventListener('click', function (event) {
    var removeButton = event.target.closest('[data-remove-object-match]');
    if (removeButton) {
      var row = removeButton.closest('[data-object-match-group]');
      var settingsForm = removeButton.closest('#objectTemplateSettingsForm');
      if (row) row.remove();
      syncObjectTemplate(settingsForm);
    }
  });

  document.body.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (target) target.querySelectorAll('[data-folder-picker]').forEach(syncFolderPicker);
    if (target && target.id === 'object-match-list') {
      syncObjectTemplate(target.closest('#objectTemplateSettingsForm'));
    }
    if (target && target.id === 'identity-fields-list') {
      syncIdentityLimit(document.querySelector('#templateSettingsForm'));
    }
  });

  document.body.addEventListener('htmx:configRequest', function (event) {
    var trigger = event.detail && event.detail.elt;
    if (!trigger) return;
    if (trigger.matches('[data-add-identity-field]')) {
      event.detail.parameters.index = trigger.dataset.nextIndex || '0';
      return;
    }
    if (trigger.matches('[data-add-object-match]')) event.detail.parameters.index = trigger.dataset.nextIndex || '0';
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var trigger = event.detail && event.detail.elt;
    if (!trigger || !event.detail.successful) return;
    if (trigger.matches('[data-add-identity-field], [data-add-object-match]')) {
      trigger.dataset.nextIndex = String(Number(trigger.dataset.nextIndex || '0') + 1);
      syncObjectTemplate(trigger.closest('#objectTemplateSettingsForm'));
    }
  });

  syncTimezoneMode(document.getElementById('templateSettingsForm'));
  document.querySelectorAll('[data-folder-picker]').forEach(syncFolderPicker);
  syncSkipRule(document.getElementById('templateSettingsForm'));
  syncIdentityLimit(document.getElementById('templateSettingsForm'));
  syncObjectTemplate(document.getElementById('objectTemplateSettingsForm'));
}());
