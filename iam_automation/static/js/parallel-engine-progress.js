(function () {
  'use strict';

  function updateProgress(panel, data) {
    var message = panel.querySelector('[data-progress-message]');
    var count = panel.querySelector('[data-progress-count]');
    var progress = panel.querySelector('[role="progressbar"]');
    var bar = panel.querySelector('[data-progress-bar]');
    var total = Number(data.total || 0);
    var processed = Number(data.processed || 0);
    var percent = total > 0 ? Math.min(100, Math.round(processed * 100 / total)) : 0;

    panel.hidden = false;
    panel.classList.toggle('engine-import-progress-running', data.status === 'RUNNING');
    panel.classList.toggle('engine-import-progress-queued', data.status === 'QUEUED');
    if (message) {
      message.textContent = data.status === 'QUEUED' && data.queue_position
        ? 'Queued for processing - position ' + data.queue_position
        : (data.message || 'Import is running');
    }
    if (progress) progress.setAttribute('aria-valuenow', String(percent));
    if (bar) {
      bar.style.width = (data.status === 'QUEUED' ? 18 : (total > 0 ? percent : 8)) + '%';
      bar.classList.toggle('progress-bar-animated', data.status === 'RUNNING');
      bar.classList.toggle('progress-bar-striped', data.status === 'RUNNING');
      bar.classList.toggle('bg-info', data.status === 'QUEUED');
      if (data.status === 'FAILED') bar.classList.add('bg-danger');
      if (data.status === 'COMPLETED') bar.classList.add('bg-success');
    }

    if (count) {
      if (data.status === 'QUEUED') {
        count.textContent = 'This file will start automatically when earlier work finishes.';
      } else if (total > 0) {
        var rowText = data.current_row ? 'Processing row ' + data.current_row + ' of ' + total + ' · ' : '';
        count.textContent = rowText + processed + ' of ' + total + ' rows completed · ' + Number(data.created || 0) +
          ' new objects · ' + Number(data.linked || 0) + ' linked · ' +
          Number(data.quarantined || 0) + ' for review';
      } else {
        count.textContent = 'Preparing file and rules…';
      }
    }
  }

  async function poll(panel) {
    try {
      var response = await fetch(panel.dataset.progressUrl, {
        credentials: 'same-origin', headers: { 'Accept': 'application/json' }
      });
      var data = await response.json();
      updateProgress(panel, data);
      if (data.status === 'QUEUED' || data.status === 'RUNNING') {
        window.setTimeout(function () { poll(panel); }, 700);
      } else if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        var form = panel.closest('article, tr');
        if (form) form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = true; });
        window.setTimeout(function () { window.location.reload(); }, 1400);
      }
    } catch (_error) {
      var message = panel.querySelector('[data-progress-message]');
      if (message) message.textContent = 'Progress update temporarily unavailable; the import continues on the server.';
      window.setTimeout(function () { poll(panel); }, 1500);
    }
  }

  function startVisibleProgress(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-engine-progress]:not([hidden])').forEach(function (panel) {
      if (panel.dataset.polling === 'true') return;
      panel.dataset.polling = 'true';
      poll(panel);
    });
  }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('[data-engine-process-form]')) return;
    event.preventDefault();
    if (form.dataset.engineStarted === 'true') return;
    form.dataset.engineStarted = 'true';
    var container = form.closest('article, tr');
    var panel = container && container.querySelector('[data-engine-progress]');
    var button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    if (panel) {
      panel.hidden = false;
      panel.classList.add('engine-import-progress-running');
      var message = panel.querySelector('[data-progress-message]');
      if (message) message.textContent = 'Authorizing and starting import…';
    }

    fetch(form.action, {
      method: 'POST', credentials: 'same-origin', body: new FormData(form),
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.message || 'Import could not be started.');
        if (panel && data.progress_url) {
          panel.dataset.progressUrl = data.progress_url;
          updateProgress(panel, data);
          poll(panel);
        }
      });
    }).catch(function (error) {
      if (button) button.disabled = false;
      if (form.dataset) form.dataset.engineStarted = 'false';
      if (panel) updateProgress(panel, { status: 'FAILED', message: error.message || 'Import could not be started.' });
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    startVisibleProgress(document);
  });
  document.addEventListener('htmx:afterSwap', function (event) { startVisibleProgress(event.target); });
}());
