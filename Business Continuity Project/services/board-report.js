// Board report generator — produces a branded quarterly Word report
// summarising the state of the resilience program for executives.
//
//   const { buildBoardReport, gatherBoardMetrics } = require('./board-report');
//   const metrics = gatherBoardMetrics(tenantId, { quarter: 'Q1 2026' });
//   const buf = await buildBoardReport(metrics, { tenantName, generatedBy });

const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Header, Footer, PageNumber, Table, TableRow, TableCell, WidthType,
  BorderStyle, ShadingType, LevelFormat
} = require('docx');

const db = require('../models/db');
const { chat } = require('./ai');

// ------------------- Brand + helpers (reused idiom from word-export.js) -------------------
const BRAND = {
  primary: '3A3F2E', accent: '8A8A5B', accentSoft: 'C9C79F',
  text: '1C1C1C', muted: '6B6B6B', rule: 'D7D1BF', cream: 'F4F1E8'
};

function tr(text, opts = {}) {
  return new TextRun({
    text: (text === null || text === undefined) ? '' : String(text),
    font: opts.font || 'Calibri',
    size: opts.size || 22,
    bold: !!opts.bold,
    italics: !!opts.italics,
    color: opts.color || BRAND.text,
    break: opts.break
  });
}
function p(children, opts = {}) {
  return new Paragraph({
    children: Array.isArray(children) ? children : [children],
    alignment: opts.alignment,
    spacing: opts.spacing || { before: 80, after: 80 },
    heading: opts.heading,
    indent: opts.indent,
    border: opts.border,
    shading: opts.shading,
    bullet: opts.bullet,
    numbering: opts.numbering,
    pageBreakBefore: !!opts.pageBreakBefore
  });
}
function sectionHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 240, after: 120 },
    border: { bottom: { color: BRAND.accent, size: 8, style: BorderStyle.SINGLE, space: 2 } },
    children: [tr(text, { bold: true, color: BRAND.primary, size: 30 })]
  });
}
function subHeading(text) {
  return p(tr(text, { bold: true, color: BRAND.primary, size: 24 }), { spacing: { before: 200, after: 80 } });
}
function makeHeader(tenantName) {
  return new Header({ children: [p([tr(tenantName || 'BCM Sentinel', { color: BRAND.muted, size: 18 })], { alignment: AlignmentType.RIGHT })] });
}
function makeFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [
        tr('Board Report · BCM Sentinel  ·  Page ', { color: BRAND.muted, size: 16 }),
        new TextRun({ children: [PageNumber.CURRENT], color: BRAND.muted, size: 16 }),
        tr(' of ', { color: BRAND.muted, size: 16 }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], color: BRAND.muted, size: 16 })
      ]
    })]
  });
}
function pageBreak() { return new Paragraph({ children: [new TextRun({ text: '', break: 1 })], pageBreakBefore: true }); }
function hr() { return new Paragraph({ border: { bottom: { color: BRAND.rule, size: 6, style: BorderStyle.SINGLE, space: 1 } }, spacing: { before: 80, after: 160 } }); }

// Generic styled table (reused pattern from word-export)
function boardTable({ header, widths, rows }) {
  const cellMargins = { top: 100, bottom: 100, left: 140, right: 140 };
  const headerRow = new TableRow({
    tableHeader: true,
    children: header.map((cell, i) => new TableCell({
      width: widths ? { size: widths[i], type: WidthType.PERCENTAGE } : undefined,
      margins: cellMargins,
      shading: { fill: 'EEE8D3', type: ShadingType.CLEAR, color: 'auto' },
      children: [p(tr(cell, { bold: true, color: BRAND.primary, size: 21 }), { spacing: { before: 0, after: 0 } })]
    }))
  });
  const bodyRows = rows.map((r, rowIdx) => new TableRow({
    children: r.map((cell, i) => new TableCell({
      width: widths ? { size: widths[i], type: WidthType.PERCENTAGE } : undefined,
      margins: cellMargins,
      shading: rowIdx % 2 === 1 ? { fill: 'FAF8F0', type: ShadingType.CLEAR, color: 'auto' } : undefined,
      children: [p(tr(String(cell ?? '—')), { spacing: { before: 0, after: 0 } })]
    }))
  }));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 6, color: BRAND.rule },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: BRAND.rule },
      left: { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
      right: { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: BRAND.rule },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: BRAND.rule }
    },
    rows: [headerRow, ...bodyRows]
  });
}

// ------------------- Metrics gathering -------------------

/**
 * gatherBoardMetrics(tenantId, {periodStart, periodEnd, label})
 * Returns a structured object the Word builder consumes.
 */
function gatherBoardMetrics(tenantId, { periodStart, periodEnd, label } = {}) {
  // Default: current quarter
  const now = new Date();
  if (!periodEnd) periodEnd = now.toISOString().slice(0, 10);
  if (!periodStart) {
    const d = new Date(now);
    d.setMonth(d.getMonth() - 3);
    periodStart = d.toISOString().slice(0, 10);
  }
  if (!label) {
    const q = Math.floor(now.getMonth() / 3) + 1;
    label = `Q${q} ${now.getFullYear()}`;
  }

  const tenant = db.prepare('SELECT name FROM tenants WHERE id = ?').get(tenantId) || { name: '' };

  // Counts
  const planCount = db.prepare(`SELECT COUNT(*) AS n FROM bcp_plans WHERE tenant_id = ?`).get(tenantId).n;
  const openRisks = db.prepare(`SELECT COUNT(*) AS n FROM risks WHERE tenant_id = ? AND status = 'open'`).get(tenantId).n;
  const totalRisks = db.prepare(`SELECT COUNT(*) AS n FROM risks WHERE tenant_id = ?`).get(tenantId).n;
  const vendorCount = db.prepare(`SELECT COUNT(*) AS n FROM vendors WHERE tenant_id = ?`).get(tenantId).n;
  const biaCount = db.prepare(`SELECT COUNT(*) AS n FROM bia_records WHERE tenant_id = ?`).get(tenantId).n;

  // Top 10 risks by score
  const topRisks = db.prepare(`
    SELECT title, category, owner, likelihood, impact, score, status
    FROM risks WHERE tenant_id = ? ORDER BY COALESCE(score, likelihood*impact) DESC, impact DESC LIMIT 10
  `).all(tenantId);

  // Incidents in period
  const incidents = db.prepare(`
    SELECT id, title, severity, status, commander, started_at, resolved_at
    FROM incidents WHERE tenant_id = ? AND started_at >= ? AND started_at <= ? || ' 23:59:59'
    ORDER BY started_at DESC
  `).all(tenantId, periodStart, periodEnd);

  const incidentsBySev = {};
  ['SEV1', 'SEV2', 'SEV3', 'SEV4'].forEach(s => incidentsBySev[s] = 0);
  incidents.forEach(i => { incidentsBySev[i.severity || 'SEV4'] = (incidentsBySev[i.severity || 'SEV4'] || 0) + 1; });

  // Exercises in period
  const exercises = db.prepare(`
    SELECT id, title, type, outcome, status, scheduled_date, facilitator, aar_summary
    FROM exercises WHERE tenant_id = ? AND (scheduled_date IS NULL OR scheduled_date >= ?)
    AND (scheduled_date IS NULL OR scheduled_date <= ?)
    ORDER BY scheduled_date DESC
  `).all(tenantId, periodStart, periodEnd);

  // Compliance maturity
  const controls = db.prepare(`SELECT framework, status FROM compliance_controls WHERE tenant_id = ?`).all(tenantId);
  const byFramework = {};
  controls.forEach(c => {
    const k = c.framework || 'Other';
    byFramework[k] = byFramework[k] || { total: 0, implemented: 0, verified: 0, in_progress: 0, not_started: 0 };
    byFramework[k].total++;
    byFramework[k][c.status || 'not_started'] = (byFramework[k][c.status || 'not_started'] || 0) + 1;
    if (c.status === 'implemented' || c.status === 'verified') byFramework[k].implemented++;
  });
  const complianceRows = Object.keys(byFramework).map(fw => {
    const r = byFramework[fw];
    const pct = r.total ? Math.round(100 * r.implemented / r.total) : 0;
    return { framework: fw, total: r.total, implemented: r.implemented, verified: r.verified || 0, maturity_pct: pct };
  });

  // Vendor concentration (top 5 critical vendors)
  const topVendors = db.prepare(`
    SELECT name, category, criticality, tier, risk_score, contract_renewal
    FROM vendors WHERE tenant_id = ?
    ORDER BY CASE criticality WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
             COALESCE(risk_score, 0) DESC LIMIT 5
  `).all(tenantId);

  // BIA <-> BCP coverage snapshot. The board cares about one question: are our
  // critical business processes covered by a continuity plan? Anything in
  // "red" with Critical/High criticality is a decision point for the board.
  const coverageRows = db.prepare(`
    SELECT b.id, b.process_name, b.department, b.criticality, b.rto_hours, b.owner,
           COUNT(bpl.id) AS link_count,
           MIN(CASE WHEN bpl.coverage_type = 'primary' THEN 0 ELSE 1 END) AS has_primary_flag
    FROM bia_records b
    LEFT JOIN bia_plan_links bpl ON bpl.bia_id = b.id AND bpl.tenant_id = b.tenant_id
    WHERE b.tenant_id = ?
    GROUP BY b.id
  `).all(tenantId);
  let covGreen = 0, covAmber = 0, covRed = 0;
  const criticalExposed = [];
  coverageRows.forEach(r => {
    const linkCount = r.link_count || 0;
    let state = 'red';
    if (linkCount > 0) state = r.has_primary_flag === 0 ? 'green' : 'amber';
    if (state === 'green') covGreen++;
    else if (state === 'amber') covAmber++;
    else covRed++;
    if ((r.criticality === 'Critical' || r.criticality === 'High') && state !== 'green') {
      criticalExposed.push({ ...r, state });
    }
  });
  criticalExposed.sort((a, b) =>
    ((a.criticality === 'Critical' ? 0 : 1) - (b.criticality === 'Critical' ? 0 : 1)) ||
    ((a.rto_hours || 9999) - (b.rto_hours || 9999))
  );
  const orphanPlansCount = db.prepare(`
    SELECT COUNT(*) AS n FROM bcp_plans p
    WHERE p.tenant_id = ?
      AND NOT EXISTS (SELECT 1 FROM bia_plan_links l WHERE l.plan_id = p.id AND l.tenant_id = p.tenant_id)
  `).get(tenantId).n;
  const coverage = {
    total: coverageRows.length,
    green: covGreen, amber: covAmber, red: covRed,
    pct: coverageRows.length ? Math.round(100 * covGreen / coverageRows.length) : 0,
    criticalExposed,
    orphanPlansCount
  };

  // Overall program pulse (simple composite score)
  const riskHealth = totalRisks ? Math.max(0, 100 - Math.round(100 * openRisks / Math.max(totalRisks, 1))) : 100;
  const exerciseHealth = exercises.length ? Math.round(100 * exercises.filter(e => e.outcome === 'pass').length / exercises.length) : 0;
  const complianceHealth = complianceRows.length
    ? Math.round(complianceRows.reduce((a, r) => a + r.maturity_pct, 0) / complianceRows.length)
    : 0;
  // Coverage health now contributes to the pulse — a program with 0% coverage
  // should never score "strong" no matter how healthy its other dimensions look.
  const coverageHealth = coverage.total ? coverage.pct : 100;
  const pulse = Math.round((riskHealth + exerciseHealth + complianceHealth + coverageHealth) / 4);

  return {
    tenantId, tenantName: tenant.name,
    periodStart, periodEnd, label,
    counts: { planCount, openRisks, totalRisks, vendorCount, biaCount, incidentCount: incidents.length, exerciseCount: exercises.length },
    pulse, riskHealth, exerciseHealth, complianceHealth, coverageHealth,
    topRisks, incidents, incidentsBySev, exercises, complianceRows, topVendors,
    coverage
  };
}

// ------------------- Optional AI narrative -------------------

async function generateNarrative(metrics) {
  const prompt = `You are the Chief Risk Officer writing the executive narrative for a board-level resilience report. Below are the program metrics for ${metrics.label}.

Metrics summary (JSON):
${JSON.stringify({
  pulse: metrics.pulse,
  counts: metrics.counts,
  health: { risk: metrics.riskHealth, exercise: metrics.exerciseHealth, compliance: metrics.complianceHealth, coverage: metrics.coverageHealth },
  incidentsBySev: metrics.incidentsBySev,
  topRiskTitles: metrics.topRisks.slice(0, 5).map(r => r.title),
  complianceRows: metrics.complianceRows,
  exerciseOutcomes: metrics.exercises.map(e => ({ title: e.title, outcome: e.outcome })),
  coverage: metrics.coverage ? {
    pct: metrics.coverage.pct,
    covered: metrics.coverage.green,
    partial: metrics.coverage.amber,
    uncovered: metrics.coverage.red,
    orphan_plans: metrics.coverage.orphanPlansCount,
    critical_processes_without_plan: metrics.coverage.criticalExposed.slice(0, 8)
      .map(r => ({ name: r.process_name, criticality: r.criticality, rto_hours: r.rto_hours, state: r.state }))
  } : null
}, null, 2)}

Produce a crisp board narrative in Markdown with these sections:

## Executive summary
2-3 sentences. Plain English. State the pulse score in context (what it means, not just the number).

## What changed this quarter
3-5 bullets of concrete movement: incidents handled, exercises run, controls implemented, new risks identified.

## Top risks and decisions the board should weigh in on
3-5 bullets. Be specific about which risk, why it matters financially/operationally, and what decision is pending.

## Recommendations for next quarter
3-5 crisp bullets starting with verbs (Invest, Decommission, Approve, Test…).

Rules:
- No fluff, no throat-clearing, no "I hope this helps"
- No made-up facts — work only from the data above
- British English`;

  try {
    const { reply, provider } = await chat({
      tenantId: metrics.tenantId,
      messages: [{ role: 'user', content: prompt }]
    });
    return { text: reply || '', provider };
  } catch (err) {
    return { text: '', provider: 'error' };
  }
}

// ------------------- Narrative → docx paragraphs -------------------

function narrativeToDocx(text) {
  if (!text) return [p(tr('(No AI narrative generated.)', { italics: true, color: BRAND.muted }))];
  const out = [];
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { out.push(p(tr(''), { spacing: { before: 60, after: 60 } })); continue; }
    if (line.startsWith('## ')) { out.push(subHeading(line.slice(3))); continue; }
    if (line.startsWith('# ')) { out.push(sectionHeading(line.slice(2))); continue; }
    if (/^[-*]\s+/.test(line)) {
      out.push(new Paragraph({ bullet: { level: 0 }, spacing: { before: 40, after: 40 }, children: [tr(line.replace(/^[-*]\s+/, ''))] }));
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      out.push(new Paragraph({ numbering: { reference: 'bcm-numbering', level: 0 }, spacing: { before: 40, after: 40 },
        children: [tr(line.replace(/^\d+\.\s+/, ''))] }));
      continue;
    }
    out.push(p(tr(line)));
  }
  return out;
}

// ------------------- Public builder -------------------

async function buildBoardReport(metrics, { tenantName, generatedBy, includeNarrative = true } = {}) {
  const narrative = includeNarrative ? await generateNarrative(metrics) : { text: '', provider: '' };

  // ----- Cover -----
  const cover = [
    p([tr(tenantName || metrics.tenantName || '', { bold: true, color: BRAND.accent, size: 18 })], { alignment: AlignmentType.RIGHT, spacing: { before: 0, after: 80 } }),
    hr(),
    p([tr('Resilience Board Report', { font: 'Cambria', bold: true, size: 56, color: BRAND.primary })],
      { alignment: AlignmentType.LEFT, spacing: { before: 1200, after: 120 } }),
    p([tr(metrics.label, { font: 'Cambria', size: 30, color: BRAND.accent, italics: true })],
      { alignment: AlignmentType.LEFT, spacing: { before: 0, after: 120 } }),
    hr(),
    boardTable({
      header: ['Field', 'Value'],
      widths: [30, 70],
      rows: [
        ['Reporting period',   `${metrics.periodStart} → ${metrics.periodEnd}`],
        ['Program pulse',      `${metrics.pulse}/100`],
        ['Active plans',       metrics.counts.planCount],
        ['Open risks',         `${metrics.counts.openRisks} / ${metrics.counts.totalRisks}`],
        ['Incidents in period',metrics.counts.incidentCount],
        ['Exercises in period',metrics.counts.exerciseCount],
        ['Tracked vendors',    metrics.counts.vendorCount]
      ]
    }),
    p([tr(
      `Generated on ${new Date().toISOString().slice(0, 10)}` +
      (generatedBy ? ` by ${generatedBy}` : '') +
      ' via BCM Sentinel.',
      { size: 18, italics: true, color: BRAND.muted }
    )], { spacing: { before: 600, after: 0 } }),
    pageBreak()
  ];

  // ----- Pulse & health breakdown -----
  const pulseBand = metrics.pulse >= 80 ? 'Strong' : metrics.pulse >= 65 ? 'Healthy' : metrics.pulse >= 50 ? 'Caution' : 'At risk';
  const pulseSection = [
    sectionHeading('Program pulse'),
    p([
      tr('Overall score: ', { bold: true }),
      tr(`${metrics.pulse}/100 — ${pulseBand}`, { bold: true, color: BRAND.primary, size: 26 })
    ]),
    p(tr('Composite of risk closure rate, exercise pass-rate, and compliance maturity across tracked frameworks.', { italics: true, color: BRAND.muted })),
    boardTable({
      header: ['Dimension', 'Score / 100', 'Interpretation'],
      widths: [34, 20, 46],
      rows: [
        ['Risk closure',         metrics.riskHealth,       metrics.counts.openRisks + ' of ' + metrics.counts.totalRisks + ' risks open'],
        ['Exercise pass-rate',   metrics.exerciseHealth,   metrics.counts.exerciseCount + ' exercises run in period'],
        ['Compliance maturity',  metrics.complianceHealth, metrics.complianceRows.length + ' framework(s) tracked'],
        ['Process coverage',     metrics.coverageHealth,   (metrics.coverage && metrics.coverage.total)
          ? (metrics.coverage.green + ' of ' + metrics.coverage.total + ' processes have a primary plan')
          : 'No BIA records to cover']
      ]
    })
  ];

  // ----- AI narrative -----
  const narrativeSection = [
    sectionHeading('Executive narrative'),
    ...narrativeToDocx(narrative.text),
    p(tr(`Narrative generated by ${narrative.provider || 'n/a'}.`, { italics: true, color: BRAND.muted, size: 16 }))
  ];

  // ----- Top risks -----
  const riskSection = [
    sectionHeading('Top 10 risks'),
    metrics.topRisks.length
      ? boardTable({
          header: ['Title', 'Category', 'Owner', 'L', 'I', 'Score', 'Status'],
          widths: [32, 16, 16, 6, 6, 10, 14],
          rows: metrics.topRisks.map(r => [
            r.title, r.category || '—', r.owner || '—',
            r.likelihood ?? '—', r.impact ?? '—',
            (r.score ?? (r.likelihood && r.impact ? r.likelihood * r.impact : '—')),
            r.status || 'open'
          ])
        })
      : p(tr('No risks currently tracked.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Incidents -----
  const incidentSection = [
    sectionHeading('Incidents this period'),
    boardTable({
      header: ['Severity', 'Count'],
      widths: [60, 40],
      rows: Object.keys(metrics.incidentsBySev).map(k => [k, metrics.incidentsBySev[k]])
    }),
    p(tr('', { size: 12 })),
    subHeading('Incident details'),
    metrics.incidents.length
      ? boardTable({
          header: ['Started', 'Severity', 'Title', 'Commander', 'Status', 'Resolved'],
          widths: [17, 10, 32, 18, 12, 11],
          rows: metrics.incidents.map(i => [i.started_at, i.severity || '—', i.title, i.commander || '—', i.status, i.resolved_at || '—'])
        })
      : p(tr('No incidents declared this period.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Exercises -----
  const exerciseSection = [
    sectionHeading('Exercise outcomes'),
    metrics.exercises.length
      ? boardTable({
          header: ['Date', 'Type', 'Title', 'Facilitator', 'Outcome', 'Status'],
          widths: [14, 14, 30, 20, 12, 10],
          rows: metrics.exercises.map(e => [
            e.scheduled_date || '—', e.type || '—', e.title, e.facilitator || '—',
            e.outcome || '—', e.status || '—'
          ])
        })
      : p(tr('No exercises completed this period.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Compliance maturity -----
  const complianceSection = [
    sectionHeading('Compliance maturity'),
    metrics.complianceRows.length
      ? boardTable({
          header: ['Framework', 'Controls', 'Implemented', 'Verified', 'Maturity'],
          widths: [28, 14, 20, 16, 22],
          rows: metrics.complianceRows.map(c => [c.framework, c.total, c.implemented, c.verified, c.maturity_pct + '%'])
        })
      : p(tr('No compliance frameworks tracked yet.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Coverage of critical processes -----
  const cov = metrics.coverage || { total: 0, green: 0, amber: 0, red: 0, pct: 0, criticalExposed: [], orphanPlansCount: 0 };
  const coverageSection = [
    sectionHeading('Coverage of critical processes'),
    p(tr('Do our BIA processes have a continuity plan behind them?', { italics: true, color: BRAND.muted })),
    boardTable({
      header: ['Metric', 'Count'],
      widths: [60, 40],
      rows: [
        ['Processes tracked (BIA records)', cov.total],
        ['Covered — has a primary plan', cov.green],
        ['Partial — only secondary/partial/referenced links', cov.amber],
        ['No plan — uncovered', cov.red],
        ['Orphan plans (no linked process)', cov.orphanPlansCount],
        ['Coverage percentage', cov.pct + '%']
      ]
    }),
    p(tr('', { size: 12 })),
    subHeading('Critical / High processes without a primary plan'),
    cov.criticalExposed.length
      ? boardTable({
          header: ['Process', 'Department', 'Criticality', 'RTO (hrs)', 'Owner', 'State'],
          widths: [30, 18, 14, 12, 16, 10],
          rows: cov.criticalExposed.slice(0, 15).map(r => [
            r.process_name,
            r.department || '—',
            r.criticality || '—',
            r.rto_hours != null ? r.rto_hours : '—',
            r.owner || '—',
            r.state === 'amber' ? 'Partial' : 'No plan'
          ])
        })
      : p(tr('Every Critical and High process has a primary plan. Well done.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Vendor concentration -----
  const vendorSection = [
    sectionHeading('Vendor concentration — top 5 critical'),
    metrics.topVendors.length
      ? boardTable({
          header: ['Vendor', 'Category', 'Criticality', 'Tier', 'Risk score', 'Renewal'],
          widths: [28, 18, 16, 10, 14, 14],
          rows: metrics.topVendors.map(v => [v.name, v.category || '—', v.criticality || '—', v.tier || '—', v.risk_score ?? '—', v.contract_renewal || '—'])
        })
      : p(tr('No vendors tracked yet.', { italics: true, color: BRAND.muted }))
  ];

  // ----- Sign-off -----
  const signOff = [
    sectionHeading('Sign-off'),
    p([tr('Prepared by: ', { bold: true }), tr(generatedBy || '_________________________')]),
    p([tr('Date: ',         { bold: true }), tr(new Date().toISOString().slice(0, 10))]),
    p([tr('Approver: ',     { bold: true }), tr('_________________________')]),
    p([tr('Signature: ',    { bold: true }), tr('_________________________')])
  ];

  const doc = new Document({
    creator: 'BCM Sentinel',
    title: `Resilience Board Report — ${metrics.label}`,
    description: `Board report for ${metrics.label}`,
    styles: {
      default: { document: { run: { font: 'Calibri', size: 22, color: BRAND.text } } },
      paragraphStyles: [{ id: 'normal', name: 'Normal',
        run: { font: 'Calibri', size: 22, color: BRAND.text },
        paragraph: { spacing: { line: 300 } } }]
    },
    numbering: {
      config: [{
        reference: 'bcm-numbering',
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.',
          alignment: AlignmentType.START,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
      }]
    },
    sections: [{
      headers: { default: makeHeader(tenantName || metrics.tenantName) },
      footers: { default: makeFooter() },
      properties: { page: { margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 } } },
      children: [
        ...cover,
        ...pulseSection,
        ...narrativeSection,
        ...riskSection,
        ...incidentSection,
        ...exerciseSection,
        ...complianceSection,
        ...coverageSection,
        ...vendorSection,
        ...signOff
      ]
    }]
  });

  return Packer.toBuffer(doc);
}

module.exports = { buildBoardReport, gatherBoardMetrics };
