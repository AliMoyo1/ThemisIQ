// Lightweight Markdown → HTML renderer used to display plan content,
// exercise scenarios, AARs, etc. inside the app.
//
// Supports:
//   - # / ## / ### / #### headings
//   - Bullet lists (- or * at start of line)
//   - Numbered lists (1. 2. ...)
//   - GitHub-flavoured pipe tables (| a | b | on consecutive lines with a
//     | --- | --- | separator)
//   - **bold**, *italic*, `code` inline
//   - Blank-line paragraph breaks
//
// Everything is HTML-escaped. We never emit user-provided HTML attributes.

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Split a pipe-table row ("| a | b |") into trimmed cells.
function splitTableRow(line) {
  let trimmed = line.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
  if (trimmed.endsWith('|'))   trimmed = trimmed.slice(0, -1);
  return trimmed.split('|').map(c => c.trim());
}

// Is this a separator row like "|---|---|" or "| :--- | ---: |"
function isSeparatorRow(line) {
  const cells = splitTableRow(line);
  if (!cells.length) return false;
  return cells.every(c => /^:?-{2,}:?$/.test(c));
}

function isTableRow(line) {
  const t = line.trim();
  return t.startsWith('|') && t.endsWith('|') && t.length > 2;
}

// Inline formatting — **bold**, *italic*, `code`
function renderInline(text) {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
}

// Render a detected markdown table (array of raw lines, including separator)
// into an HTML <table>. Alignment in the separator row is honoured.
function renderTable(lines) {
  if (lines.length < 2) return '';
  const header = splitTableRow(lines[0]);
  const sep    = splitTableRow(lines[1]);
  const aligns = sep.map(cell => {
    const left  = cell.startsWith(':');
    const right = cell.endsWith(':');
    if (left && right) return 'center';
    if (right)         return 'right';
    if (left)          return 'left';
    return null;
  });

  const bodyRows = lines.slice(2).map(splitTableRow);

  const thead = '<thead><tr>' +
    header.map((cell, i) => {
      const style = aligns[i] ? ` style="text-align:${aligns[i]}"` : '';
      return `<th${style}>${renderInline(cell)}</th>`;
    }).join('') +
    '</tr></thead>';

  const tbody = '<tbody>' +
    bodyRows.map(row =>
      '<tr>' + row.map((cell, i) => {
        const style = aligns[i] ? ` style="text-align:${aligns[i]}"` : '';
        return `<td${style}>${renderInline(cell)}</td>`;
      }).join('') + '</tr>'
    ).join('') +
    '</tbody>';

  return `<table class="md-table">${thead}${tbody}</table>`;
}

function renderMarkdown(input) {
  if (!input || !String(input).trim()) return '<p class="muted">No content yet.</p>';
  const lines = String(input).replace(/\r\n/g, '\n').split('\n');

  const out = [];
  let i = 0;
  let paragraphBuf = [];
  let listType = null;      // 'ul' | 'ol' | null
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraphBuf.length) return;
    const joined = paragraphBuf.join(' ').trim();
    if (joined) out.push('<p>' + renderInline(joined) + '</p>');
    paragraphBuf = [];
  };
  const flushList = () => {
    if (!listType) return;
    out.push(`<${listType}>` + listItems.map(it => `<li>${renderInline(it)}</li>`).join('') + `</${listType}>`);
    listType = null;
    listItems = [];
  };

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.replace(/\s+$/, '');

    // Blank line → flush paragraphs and lists
    if (line.trim() === '') {
      flushParagraph();
      flushList();
      i++;
      continue;
    }

    // Pipe-table detection: current line is `|...|` and next is a separator row
    if (isTableRow(line) && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      flushParagraph();
      flushList();
      const tableLines = [line, lines[i + 1]];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) {
        tableLines.push(lines[i]);
        i++;
      }
      out.push(renderTable(tableLines));
      continue;
    }

    // Heading
    const hMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (hMatch) {
      flushParagraph();
      flushList();
      const depth = Math.min(hMatch[1].length, 6);
      out.push(`<h${depth} class="md-h${depth}">${renderInline(hMatch[2].trim())}</h${depth}>`);
      i++;
      continue;
    }

    // Bullet
    const bulletMatch = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      if (listType !== 'ul') { flushList(); listType = 'ul'; }
      listItems.push(bulletMatch[1]);
      i++;
      continue;
    }

    // Numbered
    const numMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (numMatch) {
      flushParagraph();
      if (listType !== 'ol') { flushList(); listType = 'ol'; }
      listItems.push(numMatch[1]);
      i++;
      continue;
    }

    // Horizontal rule
    if (/^\s*-{3,}\s*$/.test(line) || /^\s*\*{3,}\s*$/.test(line)) {
      flushParagraph();
      flushList();
      out.push('<hr class="md-hr" />');
      i++;
      continue;
    }

    // Plain paragraph text
    flushList();
    paragraphBuf.push(line.trim());
    i++;
  }
  flushParagraph();
  flushList();

  return out.join('\n');
}

// Group Markdown content into logical blocks so the Word exporter can decide
// what to do with each. Returns an array of blocks:
//   { kind: 'heading', depth, text }
//   { kind: 'paragraph', text }
//   { kind: 'bullet', text }
//   { kind: 'numbered', text }
//   { kind: 'table', header: [...], aligns: [...], rows: [[...], ...] }
//   { kind: 'hr' }
function tokenize(input) {
  if (!input) return [];
  const lines = String(input).replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  let paragraphBuf = [];

  const flushParagraph = () => {
    if (!paragraphBuf.length) return;
    const joined = paragraphBuf.join(' ').replace(/\s+/g, ' ').trim();
    if (joined) blocks.push({ kind: 'paragraph', text: joined });
    paragraphBuf = [];
  };

  while (i < lines.length) {
    const line = lines[i].replace(/\s+$/, '');

    if (line.trim() === '') { flushParagraph(); i++; continue; }

    // Pipe table
    if (isTableRow(line) && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      flushParagraph();
      const header = splitTableRow(line);
      const sep    = splitTableRow(lines[i + 1]);
      const aligns = sep.map(cell => {
        const left  = cell.startsWith(':');
        const right = cell.endsWith(':');
        if (left && right) return 'center';
        if (right)         return 'right';
        if (left)          return 'left';
        return null;
      });
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      // Normalise each row to header length
      const width = header.length;
      const padded = rows.map(r => {
        if (r.length === width) return r;
        if (r.length < width) return r.concat(Array(width - r.length).fill(''));
        return r.slice(0, width);
      });
      blocks.push({ kind: 'table', header, aligns, rows: padded });
      continue;
    }

    // Heading
    const hMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (hMatch) {
      flushParagraph();
      blocks.push({ kind: 'heading', depth: Math.min(hMatch[1].length, 6), text: hMatch[2].trim() });
      i++;
      continue;
    }

    // Bullet
    const bulletMatch = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      blocks.push({ kind: 'bullet', text: bulletMatch[1] });
      i++;
      continue;
    }

    // Numbered
    const numMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (numMatch) {
      flushParagraph();
      blocks.push({ kind: 'numbered', text: numMatch[1] });
      i++;
      continue;
    }

    // HR
    if (/^\s*-{3,}\s*$/.test(line) || /^\s*\*{3,}\s*$/.test(line)) {
      flushParagraph();
      blocks.push({ kind: 'hr' });
      i++;
      continue;
    }

    paragraphBuf.push(line.trim());
    i++;
  }
  flushParagraph();
  return blocks;
}

module.exports = { renderMarkdown, tokenize, escapeHtml };
