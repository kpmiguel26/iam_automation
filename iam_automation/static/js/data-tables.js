/*
 * File: iam_automation/static/js/data-tables.js
 * Purpose: Provides the shared local DataTables behavior for application tables.
 * Responsibilities: Adds search, sorting, pagination, all-rows view, copy and CSV/XLSX export.
 * Dependencies: DataTables 2, Bootstrap 5 integration, Buttons and JSZip from static/vendor.
 */

(function () {
  'use strict';

  function isAlreadyInitialized(table) {
    return window.DataTable && typeof window.DataTable.isDataTable === 'function'
      && window.DataTable.isDataTable(table);
  }

  function hasUsableRows(table) {
    var rows = Array.from(table.querySelectorAll('tbody > tr'));
    if (!rows.length) return false;
    var columns = table.querySelectorAll('thead > tr:last-child > th, thead > tr:last-child > td').length;
    if (!columns) return false;
    // Detail rows (for example, an expandable history payload) are intentionally
    // left as ordinary HTML because DataTables requires a rectangular body.
    if (rows.some(function (row) { return row.querySelector('[colspan], [rowspan]'); })) return false;
    return rows.some(function (row) {
      return row.querySelectorAll(':scope > th, :scope > td').length === columns;
    });
  }

  function exportText(data) {
    var holder = document.createElement('div');
    var html = String(data == null ? '' : data)
      // Keep the visual separation used by stacked labels such as employee
      // name + email when DataTables strips the markup for CSV/XLSX.
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(div|p|li|tr|td|th)>/gi, '\n');
    holder.innerHTML = html;
    return (holder.textContent || holder.innerText || '').replace(/\s+/g, ' ').trim();
  }

  function tableTitle(table) {
    if (table.dataset.exportName) return table.dataset.exportName;
    var heading = table.closest('section, .surface, .modal-content');
    var title = heading && heading.querySelector('h1, h2, h3, h4, h5, h6');
    return title ? exportText(title.textContent) : (document.title || 'IAM Automation table');
  }

  function addColumnVisibilityControl(api, table) {
    var container = table.closest('.dt-container');
    var header = table.querySelector('thead > tr:last-child');
    var layoutEnd = container && container.querySelector('.dt-layout-row:first-child .dt-layout-end');
    if (!container || !header || !layoutEnd) return;

    var details = document.createElement('details');
    details.className = 'dt-columns-menu';
    var summary = document.createElement('summary');
    summary.className = 'btn btn-outline-secondary btn-sm';
    summary.textContent = 'Fields';
    summary.setAttribute('aria-label', 'Choose visible fields');
    var menu = document.createElement('div');
    menu.className = 'dt-columns-menu-panel';
    var actions = document.createElement('div');
    actions.className = 'dt-columns-menu-actions';
    var showAll = document.createElement('button');
    showAll.type = 'button';
    showAll.className = 'btn btn-link btn-sm p-0';
    showAll.textContent = 'Show all fields';
    actions.appendChild(showAll);
    menu.appendChild(actions);

    var controls = [];
    Array.from(header.children).forEach(function (headerCell, index) {
      var label = document.createElement('label');
      label.className = 'dt-column-option';
      var checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = api.column(index).visible();
      checkbox.addEventListener('change', function () {
        api.column(index).visible(checkbox.checked);
      });
      var text = document.createElement('span');
      text.textContent = exportText(headerCell.textContent) || ('Field ' + (index + 1));
      label.append(checkbox, text);
      menu.appendChild(label);
      controls.push({ checkbox: checkbox, index: index });
    });
    showAll.addEventListener('click', function () {
      api.columns().visible(true);
      controls.forEach(function (control) { control.checkbox.checked = true; });
    });
    details.append(summary, menu);
    layoutEnd.insertBefore(details, layoutEnd.firstChild);
  }

  function initializeTable(table) {
    if (!window.DataTable || isAlreadyInitialized(table)) return;
    if (table.dataset.datatable === 'off' || table.closest('.dataTables_wrapper')) return;
    if (!table.querySelector('thead') || !hasUsableRows(table)) return;

    var disabledColumns = Array.from(table.querySelectorAll('thead > tr:last-child > th, thead > tr:last-child > td'))
      .filter(function (header) {
        return header.dataset.dtOrder === 'disable' || /^(action|actions|review|decision)$/i.test(exportText(header.textContent));
      })
      .map(function (header) { return Array.from(header.parentElement.children).indexOf(header); });
    var exportOptions = {
      columns: ':visible',
      modifier: { search: 'applied', order: 'applied' },
      format: {
        header: exportText,
        body: function (data, row, column, node) {
          return exportText(node ? node.innerHTML : data);
        }
      }
    };
    var title = tableTitle(table);
    var fileName = title.toLowerCase().replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'iam-automation-table';

    var api = new DataTable(table, {
      pageLength: Number(table.dataset.pageLength || 25),
      lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, 'All']],
      order: [],
      autoWidth: false,
      columnDefs: disabledColumns.map(function (index) { return { targets: index, orderable: false }; }),
      language: {
        search: 'Filter:',
        searchPlaceholder: 'Search visible records…',
        lengthMenu: 'Rows _MENU_',
        info: 'Showing _START_ to _END_ of _TOTAL_ records',
        infoEmpty: 'No records to show',
        zeroRecords: 'No matching records found — adjust the filter or search term.'
      },
      layout: {
        topStart: {
          buttons: [
            { extend: 'copyHtml5', text: 'Copy', title: title, exportOptions: exportOptions },
            { extend: 'csvHtml5', text: 'CSV', filename: fileName, bom: true, exportOptions: exportOptions },
            { extend: 'excelHtml5', text: 'Excel', title: title, filename: fileName, sheetName: 'IAM data', exportOptions: exportOptions }
          ]
        },
        topEnd: 'search',
        bottomStart: 'info',
        bottomEnd: 'paging'
      }
    });
    addColumnVisibilityControl(api, table);
    table.setAttribute('data-datatable-ready', 'true');
  }

  function initializeTables(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('table').forEach(initializeTable);
  }

  function start() {
    initializeTables(document);
    document.addEventListener('htmx:afterSwap', function (event) {
      initializeTables(event.target);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}());
