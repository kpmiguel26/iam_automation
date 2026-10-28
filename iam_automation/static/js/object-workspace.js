(function () {
  'use strict';

  function filterPropertyCards(input) {
    var query = input.value.trim().toLocaleLowerCase();
    var cards = Array.from(document.querySelectorAll('[data-object-property-card]'));
    var visible = 0;
    cards.forEach(function (card) {
      var matches = !query || (card.dataset.searchText || '').toLocaleLowerCase().includes(query);
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    document.querySelectorAll('[data-object-property-group]').forEach(function (group) {
      group.hidden = !group.querySelector('[data-object-property-card]:not([hidden])');
    });
    var count = document.getElementById('object-property-count');
    if (count) count.textContent = query ? visible + ' of ' + cards.length + ' values' : cards.length + ' values';
    var empty = document.getElementById('object-property-no-match');
    if (empty) empty.hidden = visible > 0;
  }

  function statusFor(target) {
    if (!target || !target.id) return null;
    return document.getElementById(target.id + '-error')
      || (/^(evidence|history)-body-/.test(target.id) ? target : null);
  }

  document.body.addEventListener('htmx:beforeRequest', function (event) {
    var target = event.detail && event.detail.target;
    var status = statusFor(target);
    if (!status) return;
    target.setAttribute('aria-busy', 'true');
    if (status !== target) status.classList.add('d-none');
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    var target = event.detail && event.detail.target;
    var status = statusFor(target);
    if (!status) return;
    target.setAttribute('aria-busy', 'false');
    if (status === target && event.detail.successful) return;
    if (!event.detail.successful) {
      if (/^(evidence|history)-body-/.test(target.id)) {
        var message = document.createElement('div');
        message.className = 'alert alert-danger mb-0';
        message.setAttribute('role', 'alert');
        message.textContent = 'We could not load this source observation. Refresh the page and reopen it to try again.';
        target.replaceChildren(message);
        return;
      }
      status.textContent = 'We could not update these results. Your current information is still shown. Please try again.';
      status.classList.remove('d-none');
    }
  });

  document.addEventListener('input', function (event) {
    if (event.target && event.target.matches('#object-property-filter')) filterPropertyCards(event.target);
  });

  document.addEventListener('toggle', function (event) {
    var details = event.target;
    if (!details.matches || !details.matches('[data-object-table-details]') || !details.open) return;
    window.requestAnimationFrame(function () {
      var table = details.querySelector('table');
      if (table && window.DataTable && window.DataTable.isDataTable(table)) {
        new window.DataTable(table).columns.adjust().draw(false);
      }
    });
  }, true);
}());
