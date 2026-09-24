(function () {
  'use strict';

  function openLibraryModal(target) {
    if (!target) return;
    var modalElement = target.querySelector('#templateIdentityModal, #templateBehaviorModal, #objectTemplateModal, #deleteReportTemplateModal');
    if (!modalElement || modalElement.dataset.libraryModalOpened === 'true') return;
    modalElement.dataset.libraryModalOpened = 'true';
    if (window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }
    syncTimezoneMode(modalElement);
    syncSkipRule(modalElement);
    syncIdentityLimit(modalElement);
    syncObjectTemplate(modalElement);
  }

  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target ? event.detail.target : event.target;
    if (!target || target.id !== 'template-modal-region') return;
    openLibraryModal(target);
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var requestElement = event.detail && event.detail.elt;
    if (!requestElement || !requestElement.matches('[hx-get*="template-object/settings"]') || !event.detail.successful) return;
    window.requestAnimationFrame(function () {
      openLibraryModal(document.getElementById('template-modal-region'));
    });
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
    if (!root || !root.matches('#objectTemplateModal')) return;
    var sources = Array.from(root.querySelectorAll('[data-object-source]'));
    var selectedSources = new Set(sources.filter(function (input) { return input.checked; }).map(function (input) { return input.value; }));
    var identities = Array.from(root.querySelectorAll('[data-object-identity]'));
    identities.forEach(function (input) {
      var sourceSelected = selectedSources.has(input.dataset.sourceId);
      input.disabled = !sourceSelected;
      if (!sourceSelected) input.checked = false;
    });
    var selectedStrong = identities.filter(function (input) { return input.checked && input.dataset.strength === 'STRONG'; });
    var selectedStrongRefs = new Set(selectedStrong.map(function (input) { return input.value; }));
    var strongSources = new Set(selectedStrong.map(function (input) { return input.dataset.sourceId; }));
    root.querySelectorAll('[data-object-match-group]').forEach(function (group) {
      var sourceSelect = group.querySelector('[data-object-match-source]');
      var anchorSelect = group.querySelector('[data-object-match-anchor]');
      if (!sourceSelect || !anchorSelect) return;
      Array.from(sourceSelect.options).forEach(function (option) {
        if (option.value) option.disabled = !selectedSources.has(option.value) || !strongSources.has(option.value);
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
    if (empty) empty.hidden = root.querySelectorAll('[data-object-match-group]').length > 0;
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
    if (!root || !root.matches('#templateIdentityModal')) return;
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
    if (event.target && event.target.matches('[data-timezone-mode]')) {
      syncTimezoneMode(event.target.closest('.modal'));
    }
    if (event.target && event.target.matches('[data-skip-field]')) {
      syncSkipRule(event.target.closest('.modal'));
    }
    if (event.target && (event.target.matches('[name="identity_matching_limit"]') || event.target.matches('#identity-fields-list select[name$="_key"]'))) {
      syncIdentityLimit(event.target.closest('.modal'));
    }
    if (event.target && event.target.matches('[data-object-source], [data-object-identity], [data-object-match-source], [data-object-match-anchor], [data-object-match-target]')) {
      syncObjectTemplate(event.target.closest('#objectTemplateModal'));
    }
  });

  document.body.addEventListener('click', function (event) {
    var removeButton = event.target.closest('[data-remove-object-match]');
    if (removeButton) {
      var row = removeButton.closest('[data-object-match-group]');
      var modal = removeButton.closest('#objectTemplateModal');
      if (row) row.remove();
      syncObjectTemplate(modal);
    }
  });

  document.body.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === 'object-match-list') {
      syncObjectTemplate(target.closest('#objectTemplateModal'));
    }
    if (target && (target.id === 'identity-fields-list' || target.id === 'template-modal-region')) {
      syncIdentityLimit(document.querySelector('#templateIdentityModal'));
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
      syncObjectTemplate(trigger.closest('#objectTemplateModal'));
    }
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var form = event.detail && event.detail.elt;
    if (!form || !form.matches('form[action*="identity-settings"], form[data-template-config-save]') || !event.detail.successful) return;
    if (document.querySelector('#template-modal-region .alert-danger[role="alert"]')) return;
    var modalElement = form.closest('.modal');
    if (modalElement && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalElement).hide();
    }
  });
}());
