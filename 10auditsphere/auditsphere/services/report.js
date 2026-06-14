const PDFDocument = require('pdfkit');

function generateAuditReport(audit, controls, evidence, narrative = {}) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50, size: 'A4' });
    const buffers = [];
    doc.on('data', chunk => buffers.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(buffers)));
    doc.on('error', reject);

    const colors = { primary: '#4f8ef7', dark: '#0d0f14', muted: '#666', green: '#27ae60', red: '#e74c3c', amber: '#f39c12', border: '#e0e0e0' };
    const completed = controls.filter(c => c.status === 'Complete').length;
    const pct = controls.length > 0 ? Math.round((completed / controls.length) * 100) : 0;
    const critical = controls.filter(c => c.risk_level === 'Critical' && c.status !== 'Complete').length;

    // ---- COVER PAGE ----
    doc.rect(0, 0, doc.page.width, 200).fill(colors.dark);
    doc.fillColor(colors.primary).fontSize(28).font('Helvetica-Bold').text('AUDITSPHERE', 50, 50);
    doc.fillColor('white').fontSize(20).font('Helvetica-Bold').text(audit.name || 'Audit Report', 50, 90);
    doc.fillColor('#aaa').fontSize(12).font('Helvetica').text(`${audit.framework_name} · ${audit.audit_type || 'External'} Audit`, 50, 120);
    doc.fillColor('#888').fontSize(10).text(`Generated: ${new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })}`, 50, 145);
    doc.fillColor('#888').text(`Audit Date: ${audit.audit_date || 'TBD'} · Auditor: ${audit.auditor || 'TBD'}`, 50, 162);

    // KPI boxes
    const kpis = [
      { label: 'Completion', value: `${pct}%`, color: pct >= 80 ? colors.green : pct >= 50 ? colors.amber : colors.red },
      { label: 'Controls', value: `${completed}/${controls.length}`, color: colors.primary },
      { label: 'Critical Gaps', value: `${critical}`, color: critical > 0 ? colors.red : colors.green },
      { label: 'Evidence Items', value: `${evidence.length}`, color: colors.primary },
    ];
    let kpiX = 50;
    kpis.forEach(k => {
      doc.rect(kpiX, 210, 115, 60).fill('#f8f9ff').stroke(colors.border);
      doc.fillColor(k.color).fontSize(22).font('Helvetica-Bold').text(k.value, kpiX + 8, 220, { width: 99, align: 'center' });
      doc.fillColor(colors.muted).fontSize(9).font('Helvetica').text(k.label, kpiX + 8, 249, { width: 99, align: 'center' });
      kpiX += 125;
    });

    doc.moveDown(6);

    // ---- EXECUTIVE SUMMARY ----
    sectionHeader(doc, 'Executive Summary', colors);
    doc.fillColor(colors.dark).fontSize(10).font('Helvetica').text(
      narrative.executive_summary || `This report presents the findings of the ${audit.name}. The audit assessed compliance across ${controls.length} controls within the ${audit.framework_name} framework. ${pct}% of controls have been satisfied as of the report date.`,
      { lineGap: 4 }
    );
    doc.moveDown();

    // Scope & Methodology
    if (narrative.scope_statement) {
      sectionHeader(doc, 'Scope', colors);
      doc.fillColor(colors.dark).fontSize(10).text(narrative.scope_statement, { lineGap: 4 }).moveDown();
    }
    if (narrative.methodology) {
      sectionHeader(doc, 'Methodology', colors);
      doc.fillColor(colors.dark).fontSize(10).text(narrative.methodology, { lineGap: 4 }).moveDown();
    }

    // ---- CONTROLS TABLE ----
    doc.addPage();
    sectionHeader(doc, 'Controls Assessment', colors);

    const colWidths = [60, 180, 65, 65, 65];
    const headers = ['Control ID', 'Control Name', 'Risk', 'Status', 'Evidence'];
    let y = doc.y;

    // Table header
    doc.rect(50, y, 495, 20).fill(colors.dark);
    let x = 50;
    headers.forEach((h, i) => {
      doc.fillColor('white').fontSize(8).font('Helvetica-Bold').text(h, x + 4, y + 6, { width: colWidths[i], align: 'left' });
      x += colWidths[i];
    });
    y += 20;

    // Table rows
    controls.forEach((ctrl, idx) => {
      if (y > doc.page.height - 80) { doc.addPage(); y = 50; }
      const rowBg = idx % 2 === 0 ? 'white' : '#f9f9f9';
      doc.rect(50, y, 495, 18).fill(rowBg).stroke(colors.border);
      x = 50;
      const riskColor = { Critical: colors.red, High: colors.amber, Medium: colors.primary, Low: colors.green }[ctrl.risk_level] || colors.muted;
      const statusColor = ctrl.status === 'Complete' ? colors.green : ctrl.status === 'In Progress' ? colors.amber : colors.red;
      const cols = [ctrl.control_id, ctrl.name?.substring(0, 35) || '', ctrl.risk_level, ctrl.status, `${ctrl.ev_count || 0}/${ctrl.ev_req || 0}`];
      const colColors = [colors.primary, colors.dark, riskColor, statusColor, colors.muted];
      cols.forEach((v, i) => {
        doc.fillColor(colColors[i]).fontSize(8).font('Helvetica').text(v, x + 4, y + 5, { width: colWidths[i] - 4 });
        x += colWidths[i];
      });
      y += 18;
    });

    doc.moveDown(2);

    // ---- EVIDENCE LIST ----
    if (evidence.length > 0) {
      if (doc.y > doc.page.height - 150) doc.addPage();
      sectionHeader(doc, 'Evidence Summary', colors);
      evidence.forEach(ev => {
        if (doc.y > doc.page.height - 60) doc.addPage();
        doc.rect(50, doc.y, 495, 1).fill(colors.border);
        doc.moveDown(0.3);
        doc.fillColor(colors.primary).fontSize(9).font('Helvetica-Bold').text(ev.original_name || ev.name, 50);
        doc.fillColor(colors.muted).fontSize(8).font('Helvetica')
          .text(`Control: ${ev.control_name || '—'} · Uploaded: ${ev.uploaded_at ? ev.uploaded_at.substring(0,10) : 'N/A'} · Status: ${ev.status}`, 50);
        doc.moveDown(0.5);
      });
    }

    // ---- FINDINGS ----
    if (narrative.findings_overview || narrative.conclusion) {
      doc.addPage();
      if (narrative.findings_overview) {
        sectionHeader(doc, 'Findings Overview', colors);
        doc.fillColor(colors.dark).fontSize(10).text(narrative.findings_overview, { lineGap: 4 }).moveDown();
      }
      if (narrative.conclusion) {
        sectionHeader(doc, 'Conclusion', colors);
        doc.fillColor(colors.dark).fontSize(10).text(narrative.conclusion, { lineGap: 4 }).moveDown();
      }
    }

    // Footer on each page
    const range = doc.bufferedPageRange();
    for (let i = 0; i < range.count; i++) {
      doc.switchToPage(range.start + i);
      doc.rect(0, doc.page.height - 30, doc.page.width, 30).fill(colors.dark);
      doc.fillColor('#666').fontSize(8).text(`AuditSphere · ${audit.name} · Confidential`, 50, doc.page.height - 18);
      doc.fillColor('#666').text(`Page ${i + 1} of ${range.count}`, doc.page.width - 100, doc.page.height - 18);
    }

    doc.end();
  });
}

function sectionHeader(doc, title, colors) {
  doc.rect(50, doc.y, 495, 24).fill(colors.primary);
  doc.fillColor('white').fontSize(11).font('Helvetica-Bold').text(title, 58, doc.y - 18);
  doc.moveDown(0.5);
}

module.exports = { generateAuditReport };
