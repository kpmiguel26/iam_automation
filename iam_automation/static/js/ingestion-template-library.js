(function () {
  'use strict';

  document.body.addEventListener('htmx:afterSwap', function (event) {
    if (!event.detail || !event.detail.target || event.detail.target.id !== 'template-modal-region') return;
    var modalElement = document.querySelector('#templateIdentityModal, #templateBehaviorModal');
    syncTimezoneMode(modalElement);
    syncSkipRule(modalElement);
    if (modalElement && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }
  });

  function syncTimezoneMode(root) {
    if (!root) return;
    var mode = root.querySelector('[data-timezone-mode]');
    if (!mode) return;
    root.querySelectorAll('[data-custom-timezone]').forEach(function (input) {
      input.disabled = mode.value !== 'CUSTOM';
      input.required = mode.value === 'CUSTOM';
    });
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

  document.body.addEventListener('change', function (event) {
    if (event.target && event.target.matches('[data-timezone-mode]')) {
      syncTimezoneMode(event.target.closest('.modal'));
    }
    if (event.target && event.target.matches('[data-skip-field]')) {
      syncSkipRule(event.target.closest('.modal'));
    }
  });

  document.body.addEventListener('htmx:configRequest', function (event) {
    var trigger = event.detail && event.detail.elt;
    if (!trigger || !trigger.matches('[data-add-identity-field]')) return;
    event.detail.parameters.index = trigger.dataset.nextIndex || '0';
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var trigger = event.detail && event.detail.elt;
    if (!trigger || !trigger.matches('[data-add-identity-field]') || !event.detail.successful) return;
    trigger.dataset.nextIndex = String(Number(trigger.dataset.nextIndex || '0') + 1);
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var form = event.detail && event.detail.elt;
    if (!form || !form.matches('form[action*="identity-settings"], form[data-template-config-save]') || !event.detail.successful) return;
    var modalElement = form.closest('.modal');
    if (modalElement && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalElement).hide();
    }
  });
}());
