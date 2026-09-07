/* Keep background refreshes from replacing an import or its unacknowledged result. */
(function () {
  'use strict';

  var pendingImports = new Set();
  var closingRequests = new WeakSet();

  function timelineBusy() {
    return pendingImports.size > 0 || document.querySelector('.source-import-task') !== null;
  }

  // This event precedes hx-sync, so a second click cannot abort an import
  // that is already running on the server.
  document.addEventListener('htmx:confirm', function (event) {
    if (event.detail.elt.matches('.source-import-form') && timelineBusy()) {
      event.preventDefault();
    }
  });

  document.addEventListener('htmx:configRequest', function (event) {
    var timeline = document.getElementById('source-timeline');
    if (timeline && event.detail.elt.matches('[data-import-close]')) {
      event.detail.path = timeline.getAttribute('hx-get');
    }
  });

  document.addEventListener('htmx:beforeRequest', function (event) {
    var detail = event.detail;
    var source = detail.elt;
    var timeline = document.getElementById('source-timeline');
    if (!timeline || !source) return;

    if (source.matches('[data-import-close]')) {
      closingRequests.add(detail.xhr);
    } else if (detail.target === timeline && timelineBusy()) {
      event.preventDefault();
    } else if (source.matches('.source-import-form')) {
      pendingImports.add(detail.xhr);
    }
  });

  document.addEventListener('htmx:beforeSwap', function (event) {
    var detail = event.detail;
    if (!detail.target || detail.target.id !== 'source-timeline') return;
    // The timer may have started before Import was clicked. Check again when
    // its response arrives, not just when the polling request is issued.
    if (!closingRequests.has(detail.xhr) && timelineBusy()) {
      detail.shouldSwap = false;
    }
  });

  document.addEventListener('htmx:afterRequest', function (event) {
    pendingImports.delete(event.detail.xhr);
  });

  document.addEventListener('htmx:afterSettle', function (event) {
    if (!closingRequests.has(event.detail.xhr)) return;
    closingRequests.delete(event.detail.xhr);
    var timeline = document.getElementById('source-timeline');
    if (!timeline) return;
    // Closing can remove a tall result and entire completed file cards.
    // Restore focus without scrolling, then return to the workflow heading
    // after HTMX and table initialization have finished changing its height.
    var heading = document.getElementById('source-timeline-heading');
    if (heading) heading.focus({preventScroll: true});
    window.scrollTo({top: Math.max(0, window.scrollY + timeline.getBoundingClientRect().top - 24), behavior: 'instant'});
  });
})();
