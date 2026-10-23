/*
 * CSV built in the browser (a table that is on screen, a list the page already holds).
 *
 * A text cell that a spreadsheet would read as a formula (it starts with =, +, - or @, or with a tab or a line break) is
 * written as text with a leading apostrophe; a plain number is left alone. Every cell is quoted, lines end with CRLF, and the
 * file name is built from letters, digits, dot, dash and underscore only.
 */
(function (global) {
  'use strict';
  var FORMULA = /^[=+\-@\t\r\n]/;
  var NUMBER = /^[-+]?\d+([.,]\d+)?%?$/;

  function cell(value) {
    var text = (value === null || value === undefined) ? '' : String(value);
    if (FORMULA.test(text) && !NUMBER.test(text.trim())) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function row(values) {
    return values.map(cell).join(',');
  }

  function fileName(stem, extension) {
    var clean = String(stem || 'export').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[._-]+|[._-]+$/g, '') || 'export';
    return 'themisiq-' + clean + '-' + new Date().toISOString().slice(0, 10) + '.' + extension;
  }

  /* download('erm-register', ['Title', 'Status'], [['A', 'open'], ...]) */
  function download(stem, header, rows) {
    var lines = [row(header)].concat(rows.map(row));
    var blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = fileName(stem, 'csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  global.TiqCsv = { cell: cell, row: row, download: download, fileName: fileName };
})(window);
