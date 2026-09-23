(function () {
  'use strict';

  function updateGuidance() {
    var form = document.getElementById('identity-guidance-form');
    var guidance = document.getElementById('identity-guidance');
    if (!form || !guidance) return;

    var roleChoice = form.querySelector('input[name="identity_role"]:checked');
    var role = roleChoice ? roleChoice.value : 'EVIDENCE_ONLY';
    var sourcePermission = form.querySelector('#identity-can-create');
    var mayCreate = role === 'IDENTITY_SEED' && !!sourcePermission && sourcePermission.checked;
    var limit = Number(guidance.dataset.identityLimit || 3);
    var selectedCount = 0;
    var strongMatchingCount = 0;
    var createAuthorizedFields = 0;

    form.querySelectorAll('[data-identity-field]').forEach(function (card) {
      var include = card.querySelector('.source-field-toggle');
      var match = card.querySelector('.identity-match-checkbox');
      var strength = card.querySelector('[data-identity-strength]');
      var create = card.querySelector('[data-identity-create]');
      var dataType = card.querySelector('[data-field-type]');
      var typeGuidance = card.querySelector('[data-field-type-guidance]');
      var included = !!include && include.checked;
      var isMatch = !!match && match.checked;
      var isCreate = !!create && create.checked;
      var isIdentity = isMatch || isCreate;

      if (isMatch && included) selectedCount += 1;
      if (isMatch && included && strength && strength.value === 'STRONG') strongMatchingCount += 1;
      if (isCreate && isMatch && included && strength && strength.value === 'STRONG') createAuthorizedFields += 1;
      if (match) {
        match.disabled = !included || role === 'EVIDENCE_ONLY' || (!isMatch && selectedCount >= limit);
      }
      if (strength) strength.disabled = !included || role === 'EVIDENCE_ONLY' || !isMatch;
      if (create) {
        create.disabled = !included || !isMatch || !mayCreate || !strength || strength.value !== 'STRONG';
        if (create.disabled) create.checked = false;
      }
      if (dataType) {
        if (isIdentity && dataType.value !== 'string') dataType.value = 'string';
        dataType.disabled = !included || isIdentity;
      }
      if (typeGuidance) typeGuidance.hidden = !isIdentity;
      card.classList.toggle('is-identity-field', isIdentity && included);
    });

    // Recalculate after applying field dependencies so the summary reflects
    // the current included fields, including any disabled identity choices.
    selectedCount = Array.from(form.querySelectorAll('.identity-match-checkbox'))
      .filter(function (input) {
        var card = input.closest('[data-identity-field]');
        var include = card && card.querySelector('.source-field-toggle');
        return input.checked && include && include.checked;
      }).length;
    var countLabel = document.getElementById('identity-matching-count');
    if (countLabel) {
      countLabel.textContent = selectedCount + ' of ' + limit + ' identity fields selected';
      countLabel.setAttribute('aria-label', 'Identity matching fields: ' + selectedCount + '/' + limit);
    }

    form.querySelectorAll('.identity-role-card').forEach(function (card) {
      var input = card.querySelector('.identity-role-choice');
      card.classList.toggle('is-selected', !!input && input.checked);
    });
    var permissionPanel = form.querySelector('.identity-source-permission');
    if (permissionPanel) permissionPanel.classList.toggle('is-unavailable', role !== 'IDENTITY_SEED');

    var modeGuidance = document.getElementById('identity-mode-guidance');
    if (modeGuidance) {
      if (role === 'IDENTITY_SEED' && mayCreate) {
        var readyToCreate = strongMatchingCount >= 2 && createAuthorizedFields >= 2;
        modeGuidance.textContent = 'To create Employee UUIDs, select at least 2 included Strong IDs for matching and authorize both for creation. Current: ' + strongMatchingCount + '/2 Strong IDs selected; ' + createAuthorizedFields + '/2 authorized.';
        modeGuidance.classList.toggle('needs-attention', !readyToCreate);
      } else if (role === 'IDENTITY_SEED') {
        modeGuidance.textContent = 'This report can help find an existing employee with at least 1 Strong ID. New Employee UUID creation is not authorized.';
        modeGuidance.classList.toggle('needs-attention', strongMatchingCount < 1);
      } else if (role === 'IDENTITY_ENRICHMENT') {
        modeGuidance.textContent = 'To link this report to existing employees, select at least 1 included Strong ID for matching. This report cannot propose a new Employee UUID.';
        modeGuidance.classList.toggle('needs-attention', strongMatchingCount < 1);
      } else {
        modeGuidance.textContent = 'This report is retained as evidence. Identity matching and new Employee UUID creation are disabled.';
        modeGuidance.classList.remove('needs-attention');
      }
    }
  }

  document.addEventListener('change', function (event) {
    if (event.target.closest && event.target.closest('#identity-guidance-form')) updateGuidance();
  }, true);
  document.addEventListener('DOMContentLoaded', updateGuidance);
  document.addEventListener('htmx:afterSwap', updateGuidance);
  updateGuidance();
}());
