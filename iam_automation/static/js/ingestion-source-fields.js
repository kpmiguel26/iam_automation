(function () {
  'use strict';

  function updateIncludedCount(form) {
    if (!form) return;
    var counter = form.querySelector('[data-included-field-count]');
    if (!counter) return;
    var total = Number(counter.dataset.totalFields || 0);
    var included = Array.from(form.querySelectorAll('.source-field-toggle'))
      .filter(function (input) { return input.checked; }).length;
    counter.textContent = included + ' of ' + total + ' included';
  }

  function updateFieldPreview(event) {
    var control = event.target;
    if (control.matches && control.matches('[data-field-key-preview]')) {
      var keyPreview = document.getElementById(control.dataset.fieldKeyPreview);
      if (keyPreview) keyPreview.textContent = control.value.trim() || 'Not set';
    }
    if (control.matches && control.matches('[data-field-type-preview]')) {
      var typePreview = document.getElementById(control.dataset.fieldTypePreview);
      var selectedOption = control.options[control.selectedIndex];
      if (typePreview && selectedOption) typePreview.textContent = selectedOption.textContent.split(' · ')[0];
    }
    if (control.matches && control.matches('[data-field-cleanup-preview]')) {
      var cleanupPreview = document.getElementById(control.dataset.fieldCleanupPreview);
      var cleanupOption = control.options[control.selectedIndex];
      if (cleanupPreview && cleanupOption) cleanupPreview.textContent = cleanupOption.textContent.split(' · ')[0].trim();
    }
  }

  document.addEventListener('input', updateFieldPreview);
  document.addEventListener('change', updateFieldPreview);

  document.addEventListener('change', function (event) {
    var toggle = event.target;
    if (!toggle.matches || !toggle.matches('.source-field-toggle')) return;
    var label = toggle.closest('.source-field-toggle-label');
    var stateLabel = label && label.querySelector('[data-field-inclusion-label]');
    if (stateLabel) stateLabel.textContent = toggle.checked ? 'Included' : 'Not included';
    updateIncludedCount(toggle.closest('#source-schema-form'));
  });

  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (target && (target.id === 'sample-workspace' || target.querySelector('[data-included-field-count]'))) {
      updateIncludedCount(document.getElementById('source-schema-form'));
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    updateIncludedCount(document.getElementById('source-schema-form'));
  });
}());
