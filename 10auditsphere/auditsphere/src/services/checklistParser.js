/**
 * checklistParser.js
 * 
 * Extracts ALL controls from Excel/CSV checklists without any character limits.
 * Strategy:
 *   1. Parse the file directly with xlsx/openpyxl-equivalent (SheetJS in Node)
 *   2. Extract every row that has a name/description — no AI, no size limit
 *   3. Use Claude in batches of 40 to assign risk levels + evidence requirements
 *   4. Return the complete merged result
 * 
 * This fixes the "only 10 of 173" bug caused by slicing rawText to 8000 chars.
 */

const XLSX  = require('xlsx');
const fs    = require('fs');
const path  = require('path');
const aiSvc = require('./ai');

/* ─── Step 1: Raw extraction from file ─── */
function extractRowsFromExcel(filePath) {
  const wb = XLSX.readFile(filePath, { cellText: true, cellDates: false });
  const results = [];

  for (const sheetName of wb.SheetNames) {
    const ws  = wb.Sheets[sheetName];
    const raw = XLSX.utils.sheet_to_json(ws, {
      header: 1,
      defval: '',
      blankrows: false,
    });

    if (raw.length < 2) continue;

    // Detect header row and column positions
    const headerRow = raw[0].map(h => String(h || '').toLowerCase().trim());
    
    // Try to detect column indices from the header
    const colIdx = detectColumns(headerRow, raw);

    // If no structured columns found, fall back to positional guessing
    let nameCol  = colIdx.name  ?? 1;
    let descCol  = colIdx.desc  ?? 2;
    let idCol    = colIdx.id    ?? 0;
    let appCol   = colIdx.applicable ?? 4;
    let noteCol  = colIdx.note  ?? 7;

    for (let i = 1; i < raw.length; i++) {
      const row  = raw[i];
      const id   = row[idCol];
      const name = clean(row[nameCol]);
      const desc = clean(row[descCol]);

      // Skip rows with no meaningful content
      if (!name && !desc) continue;
      // Skip obvious header repeats
      if (name.toLowerCase().includes('evidence name') && i < 5) continue;

      results.push({
        seq:        results.length + 1,
        raw_id:     id !== undefined && id !== '' ? String(id) : String(results.length + 1),
        name:       name.slice(0, 200),
        description:desc.slice(0, 400),
        applicable: clean(row[appCol]).toLowerCase(),
        note:       clean(row[noteCol]).slice(0, 150),
        sheet:      sheetName,
      });
    }
  }

  return results;
}

function detectColumns(headerRow, raw) {
  const idx = {};
  const matchers = {
    name:       ['evidence name', 'control name', 'name', 'requirement', 'title', 'evidence'],
    desc:       ['description', 'desc', 'detail', 'requirement description', 'control description'],
    id:         ['#', 'no', 'number', 'id', 'seq', 'item', 'ref', 'sr no', 'sl no'],
    applicable: ['applicable', 'applicability', 'in scope'],
    note:       ['comment', 'auditor', 'remark', 'note', 'observation'],
  };

  for (const [key, patterns] of Object.entries(matchers)) {
    for (let i = 0; i < headerRow.length; i++) {
      if (patterns.some(p => headerRow[i].includes(p))) {
        if (idx[key] === undefined) idx[key] = i;
      }
    }
  }

  // If first column is numeric in first data row, it's the ID
  if (raw.length > 1) {
    const firstDataVal = raw[1][0];
    if (typeof firstDataVal === 'number' || /^\d+$/.test(String(firstDataVal || ''))) {
      idx.id = 0;
    }
  }

  return idx;
}

function clean(val) {
  if (val === null || val === undefined) return '';
  return String(val).replace(/\s+/g, ' ').trim();
}

/* ─── Step 2: Extract from CSV/TXT ─── */
function extractRowsFromCSV(filePath) {
  const text = fs.readFileSync(filePath, 'utf8');
  const wb   = XLSX.read(text, { type: 'string' });
  return extractRowsFromExcel_wb(wb);
}

/* ─── Step 3: AI batch risk scoring ─── */
async function scoreRisksInBatches(rows, frameworkName) {
  const BATCH = 40;
  const scored = [];

  for (let i = 0; i < rows.length; i += BATCH) {
    const batch   = rows.slice(i, i + BATCH);
    const payload = batch.map(r => ({
      seq: r.seq,
      n:   r.name.slice(0, 100),
      d:   r.description.slice(0, 120),
    }));

    let riskMap = {};
    try {
      const response = await aiSvc.batchRiskScore(payload, frameworkName);
      riskMap = response; // { seq: { risk_level, evidence_required, category } }
    } catch (err) {
      console.warn(`Batch ${Math.floor(i/BATCH)+1} risk scoring failed: ${err.message} — using defaults`);
      // Fall back gracefully: assign Medium risk to all in batch
      batch.forEach(r => { riskMap[r.seq] = { risk_level: 'Medium', evidence_required: 1, category: '' }; });
    }

    for (const row of batch) {
      const risk = riskMap[row.seq] || { risk_level: 'Medium', evidence_required: 1, category: '' };
      scored.push({
        control_id:        row.raw_id,
        name:              row.name,
        description:       row.description || row.note,
        risk_level:        risk.risk_level  || 'Medium',
        evidence_required: risk.evidence_required || 1,
        evidence_items:    risk.evidence_items   || [row.name],
        applicable:        row.applicable,
      });
    }
  }

  return scored;
}

/* ─── Main entry point ─── */
async function parseChecklistFile(filePath, frameworkName, skipAI = false, explicitExt = '') {
  // Use explicitly passed extension (from originalname) — multer strips extension from temp path
  const ext = (explicitExt || path.extname(filePath) || '').toLowerCase();
  let rows  = [];

  if (['.xlsx', '.xls', '.xlsm', ''].includes(ext)) {
    // Empty ext = multer temp file — try Excel first (most common), fall back to CSV
    try {
      rows = extractRowsFromExcel(filePath);
    } catch (excelErr) {
      if (ext === '') {
        // Unknown type — try CSV as fallback
        try { rows = extractRowsFromCSV(filePath); }
        catch { throw new Error('Could not parse file. Please upload as .xlsx or .csv'); }
      } else {
        throw excelErr;
      }
    }
  } else if (['.csv', '.tsv', '.txt'].includes(ext)) {
    rows = extractRowsFromCSV(filePath);
  } else if (ext === '.pdf') {
    throw new Error('PDF checklists are not supported — please export to Excel (.xlsx) or CSV.');
  } else {
    throw new Error(`Unsupported file type "${ext}". Please upload .xlsx, .xls, or .csv`);
  }

  if (rows.length === 0) {
    throw new Error('No data rows found in the file. Check that the file has a header row and data below it.');
  }

  // Filter out "Not Applicable" rows if they have no content
  const applicable = rows.filter(r =>
    !r.applicable.includes('not applicable') || r.name.length > 5
  );

  if (skipAI) {
    // Return raw extraction without AI risk scoring
    return applicable.map(r => ({
      control_id:        r.raw_id,
      name:              r.name,
      description:       r.description,
      risk_level:        'Medium',
      evidence_required: 1,
      evidence_items:    [r.name],
    }));
  }

  // Use AI to score risks in batches
  return await scoreRisksInBatches(applicable, frameworkName);
}

module.exports = { parseChecklistFile, extractRowsFromExcel };
