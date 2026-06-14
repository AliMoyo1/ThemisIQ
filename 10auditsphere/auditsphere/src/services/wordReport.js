/**
 * wordReport.js — Generates a formatted .docx audit report using the docx library
 */
const {
  Document, Packer, Paragraph, Table, TableRow, TableCell,
  TextRun, HeadingLevel, AlignmentType, WidthType, BorderStyle,
  ShadingType, PageBreak, Header, Footer, PageNumber,
  NumberFormat, convertInchesToTwip, ImageRun
} = require('docx');
const path = require('path');
const fs   = require('fs');

const REPORTS_DIR = path.join(__dirname, '../../data/reports');
fs.mkdirSync(REPORTS_DIR, { recursive: true });

/* ── Colour palette (hex without #) ── */
const C = {
  primary:   '1a56db',  // blue
  dark:      '111827',  // near-black
  mid:       '374151',  // dark grey
  muted:     '6b7280',  // grey
  light:     'f3f4f6',  // light bg
  white:     'ffffff',
  green:     '065f46',  // text on green bg
  greenBg:   'd1fae5',
  amber:     '92400e',
  amberBg:   'fef3c7',
  red:       '991b1b',
  redBg:     'fee2e2',
  blue:      '1e40af',
  blueBg:    'dbeafe',
  accent:    '4f8ef7',
};

/* ── Helpers ── */
function txt(text, opts = {}) {
  return new TextRun({ text: String(text || ''), ...opts });
}

function para(children, opts = {}) {
  const runs = Array.isArray(children) ? children : [txt(children, opts.runOpts || {})];
  return new Paragraph({ children: runs, ...opts });
}

function heading(text, level = 1) {
  const sizes = { 1: 32, 2: 26, 3: 22 };
  return new Paragraph({
    children: [new TextRun({ text, bold: true, size: sizes[level] || 22, color: C.dark })],
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    spacing: { before: level === 1 ? 400 : 280, after: 160 },
  });
}

function divider() {
  return new Paragraph({
    children: [],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'e5e7eb' } },
    spacing: { before: 120, after: 120 },
  });
}

function spacer(lines = 1) {
  return new Paragraph({ children: [txt('')], spacing: { after: lines * 120 } });
}

function bullet(text, color = C.primary) {
  return new Paragraph({
    children: [new TextRun({ text: `• ${text}`, size: 20, color: C.mid })],
    spacing: { after: 80 },
    indent: { left: convertInchesToTwip(0.25) },
  });
}

function statBox(label, value, color = C.primary) {
  return new TableCell({
    children: [
      new Paragraph({ children: [txt(String(value), { bold: true, size: 36, color })], alignment: AlignmentType.CENTER }),
      new Paragraph({ children: [txt(label, { size: 16, color: C.muted })], alignment: AlignmentType.CENTER }),
    ],
    shading: { type: ShadingType.CLEAR, fill: C.light },
    margins: { top: 160, bottom: 160, left: 160, right: 160 },
    borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
  });
}

function riskColor(risk) {
  return { Critical: C.red, High: C.amber, Medium: C.primary, Low: C.green }[risk] || C.muted;
}
function riskBg(risk) {
  return { Critical: C.redBg, High: C.amberBg, Medium: C.blueBg, Low: C.greenBg }[risk] || C.light;
}
function statusColor(status) {
  return { complete: C.green, in_progress: C.amber, not_started: C.muted }[status] || C.muted;
}
function statusLabel(status, dueDate) {
  const today = new Date().toISOString().slice(0, 10);
  if (status === 'complete') return 'Complete';
  if (dueDate && dueDate < today && status !== 'complete') return 'Overdue';
  if (status === 'in_progress') return 'In Progress';
  return 'Not Started';
}

/* ── Main export ── */
async function generateAuditReportDocx(auditData, controls, narrative) {
  const {
    name: auditName, framework, audit_type, auditor,
    start_date, audit_date, totalControls, complete,
    pending, overdue, completionPct
  } = auditData;

  const generatedDate = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  const overallStatus = narrative?.overall_status || 'In Progress';
  const statusCol = overallStatus === 'On Track' ? C.green : overallStatus === 'At Risk' ? C.amber : C.red;

  const sections = [];

  /* ── COVER PAGE ── */
  sections.push(
    new Paragraph({
      children: [txt('G.R.I.D AI', { bold: true, size: 56, color: C.primary })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 1200, after: 120 },
    }),
    new Paragraph({
      children: [txt('Governance · Risk · IT · Data', { size: 24, color: C.muted, italics: true })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 80 },
    }),
    new Paragraph({
      children: [txt('by Ali Moyo', { size: 18, color: C.muted })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 600 },
    }),
    divider(),
    spacer(2),
    new Paragraph({
      children: [txt('AUDIT REPORT', { bold: true, size: 48, color: C.dark })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 400, after: 200 },
    }),
    new Paragraph({
      children: [txt(auditName, { bold: true, size: 32, color: C.mid })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 400 },
    }),
    new Table({
      rows: [
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Framework:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(framework, { color: C.dark, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Audit Type:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(audit_type || 'External', { color: C.dark, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Auditor:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(auditor || 'Not specified', { color: C.dark, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Audit Date:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(audit_date || 'TBD', { color: C.dark, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Generated:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(generatedDate, { color: C.dark, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
        new TableRow({ children: [
          new TableCell({ children: [para([txt('Status:', { bold: true, color: C.muted, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
          new TableCell({ children: [para([txt(overallStatus, { bold: true, color: statusCol, size: 18 })])], borders: { top: {style:BorderStyle.NONE}, bottom: {style:BorderStyle.NONE}, left: {style:BorderStyle.NONE}, right: {style:BorderStyle.NONE} } }),
        ]}),
      ],
      width: { size: 60, type: WidthType.PERCENTAGE },
      margins: { top: 0, bottom: 0, left: 0, right: 0 },
    }),
    new Paragraph({ children: [new PageBreak()] })
  );

  /* ── STATS SUMMARY ── */
  sections.push(
    heading('Audit At a Glance', 1),
    new Table({
      rows: [new TableRow({ children: [
        statBox('Total Controls',   totalControls || 0, C.primary),
        statBox('Complete',         complete || 0,      C.green),
        statBox('Pending',          pending || 0,       C.amber),
        statBox('Overdue',          overdue || 0,       C.red),
        statBox('Completion',       (completionPct || 0) + '%', C.primary),
      ]})],
      width: { size: 100, type: WidthType.PERCENTAGE },
      columnWidths: [2000, 2000, 2000, 2000, 2000],
    }),
    spacer(2),
    divider()
  );

  /* ── EXECUTIVE SUMMARY ── */
  if (narrative?.executive_summary) {
    sections.push(
      heading('Executive Summary', 1),
      new Paragraph({
        children: [txt(narrative.executive_summary, { size: 20, color: C.mid })],
        spacing: { after: 200, line: 320 },
        border: { left: { style: BorderStyle.SINGLE, size: 18, color: C.primary } },
        indent: { left: convertInchesToTwip(0.25) },
      }),
      spacer()
    );
  }

  /* ── KEY FINDINGS ── */
  if (narrative?.key_findings?.length) {
    sections.push(heading('Key Findings', 2));
    narrative.key_findings.forEach(f => sections.push(bullet(f)));
    sections.push(spacer());
  }

  /* ── CONCLUSION ── */
  if (narrative?.conclusion) {
    sections.push(
      heading('Conclusion', 2),
      new Paragraph({
        children: [txt(narrative.conclusion, { size: 20, color: C.mid, italics: true })],
        spacing: { after: 200, line: 320 },
      }),
      spacer()
    );
  }

  sections.push(divider(), new Paragraph({ children: [new PageBreak()] }));

  /* ── CONTROLS TABLE ── */
  sections.push(heading('Controls Summary', 1));

  const tableHeaderRow = new TableRow({
    tableHeader: true,
    children: [
      ['Control ID', 1200], ['Control Name', 3600], ['Risk', 1200],
      ['Due Date', 1400], ['Evidence', 1200], ['Status', 1400]
    ].map(([label, w]) => new TableCell({
      children: [new Paragraph({ children: [txt(label, { bold: true, size: 18, color: C.white })], alignment: AlignmentType.CENTER })],
      shading: { type: ShadingType.CLEAR, fill: C.dark },
      width: { size: w, type: WidthType.DXA },
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
    }))
  });

  const controlRows = (controls || []).map((c, idx) => {
    const sl = statusLabel(c.status, c.due_date);
    const bg = idx % 2 === 0 ? C.white : C.light;
    const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: 'e5e7eb' };
    const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
    const cell = (content, color = C.mid, bold = false, bg2 = bg) => new TableCell({
      children: [new Paragraph({ children: [txt(content, { size: 18, color, bold })], alignment: AlignmentType.CENTER })],
      shading: { type: ShadingType.CLEAR, fill: bg2 },
      borders,
      margins: { top: 60, bottom: 60, left: 80, right: 80 },
    });
    return new TableRow({ children: [
      cell(c.control_id || '—', C.primary, true),
      new TableCell({
        children: [new Paragraph({ children: [txt(c.name || '', { size: 18, color: C.mid })] })],
        shading: { type: ShadingType.CLEAR, fill: bg },
        borders,
        margins: { top: 60, bottom: 60, left: 100, right: 80 },
      }),
      cell(c.risk_level || '—', riskColor(c.risk_level), true, riskBg(c.risk_level)),
      cell(c.due_date || '—'),
      cell(`${c.evidence_count || 0}/${c.evidence_required || 1}`,
        (c.evidence_count || 0) >= (c.evidence_required || 1) ? C.green : C.amber),
      cell(sl, statusColor(c.status), true),
    ]});
  });

  sections.push(
    new Table({
      rows: [tableHeaderRow, ...controlRows],
      width: { size: 100, type: WidthType.PERCENTAGE },
      columnWidths: [1200, 3600, 1200, 1400, 1200, 1400],
    }),
    spacer(2)
  );

  /* ── DOCUMENT ── */
  const doc = new Document({
    creator: 'G.R.I.D AI by Ali Moyo',
    title:   `${auditName} — Audit Report`,
    subject: `${framework} Compliance Audit Report`,
    description: `Generated by G.R.I.D AI on ${generatedDate}`,
    styles: {
      default: {
        document: { run: { font: 'Calibri', size: 20, color: C.mid } },
      },
    },
    sections: [{
      properties: {
        page: {
          margin: { top: convertInchesToTwip(1), bottom: convertInchesToTwip(1), left: convertInchesToTwip(1.2), right: convertInchesToTwip(1.2) },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            children: [
              txt('G.R.I.D AI  ', { bold: true, size: 18, color: C.primary }),
              txt(`${auditName} — ${framework} Audit Report`, { size: 18, color: C.muted }),
            ],
            border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'e5e7eb' } },
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            children: [
              txt(`Generated by G.R.I.D AI by Ali Moyo  ·  ${generatedDate}  ·  Page `, { size: 16, color: C.muted }),
              new TextRun({ children: [PageNumber.CURRENT], size: 16, color: C.muted }),
              txt(' of ', { size: 16, color: C.muted }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: C.muted }),
            ],
            alignment: AlignmentType.CENTER,
            border: { top: { style: BorderStyle.SINGLE, size: 6, color: 'e5e7eb' } },
          })],
        }),
      },
      children: sections,
    }],
  });

  const fileName = `grid-ai-report-${Date.now()}.docx`;
  const filePath = path.join(REPORTS_DIR, fileName);
  const buffer   = await Packer.toBuffer(doc);
  fs.writeFileSync(filePath, buffer);
  return { filePath, fileName };
}

module.exports = { generateAuditReportDocx };
