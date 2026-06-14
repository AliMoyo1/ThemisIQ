const PDFDocument = require('pdfkit');

function generateAuditReport(data, narrative) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50, size: 'A4' });
    const chunks = [];
    doc.on('data', c => chunks.push(c));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    const colors = { dark: '#0d0f14', blue: '#4f8ef7', green: '#3ecf84', amber: '#f5a623', red: '#f25c5c', gray: '#6b7280', light: '#f9fafb' };

    // Cover page
    doc.rect(0, 0, doc.page.width, 200).fill(colors.dark);
    doc.fillColor(colors.blue).fontSize(28).font('Helvetica-Bold').text('AUDITSPHERE', 50, 60);
    doc.fillColor('#7a8099').fontSize(12).font('Helvetica').text('Compliance Audit Management System', 50, 95);
    doc.fillColor('white').fontSize(20).font('Helvetica-Bold').text(data.name || 'Audit Report', 50, 130);
    doc.fillColor('#7a8099').fontSize(11).font('Helvetica').text(`${data.framework} · Generated ${new Date().toLocaleDateString('en-GB', { day:'2-digit',month:'long',year:'numeric' })}`, 50, 158);

    doc.moveDown(6);

    // Health score box
    const healthColor = data.health_score >= 80 ? colors.green : data.health_score >= 60 ? colors.amber : colors.red;
    doc.rect(50, 220, 120, 80).fill(healthColor).fillOpacity(0.1).stroke();
    doc.fillColor(healthColor).fillOpacity(1).fontSize(36).font('Helvetica-Bold').text(`${data.health_score || 0}%`, 55, 235);
    doc.fillColor(colors.gray).fontSize(10).font('Helvetica').text('READINESS SCORE', 55, 280);

    // Stat boxes
    const stats = [
      { label: 'Total Controls', value: data.totalControls || 0, color: colors.blue },
      { label: 'Complete', value: data.complete || 0, color: colors.green },
      { label: 'Pending', value: (data.totalControls || 0) - (data.complete || 0), color: colors.amber },
      { label: 'Overdue', value: data.overdue || 0, color: colors.red }
    ];
    stats.forEach((s, i) => {
      const x = 190 + i * 100;
      doc.rect(x, 220, 88, 80).fill('#f9fafb').stroke('#e5e7eb');
      doc.fillColor(s.color).fontSize(28).font('Helvetica-Bold').text(String(s.value), x + 8, 235);
      doc.fillColor(colors.gray).fontSize(9).font('Helvetica').text(s.label, x + 8, 278);
    });

    doc.moveDown(8);

    // Executive Summary
    if (narrative?.executive_summary) {
      doc.addPage();
      doc.fillColor(colors.dark).fontSize(18).font('Helvetica-Bold').text('Executive Summary', 50, 50);
      doc.moveTo(50, 75).lineTo(545, 75).stroke(colors.blue);
      doc.fillColor('#374151').fontSize(11).font('Helvetica').text(narrative.executive_summary, 50, 85, { width: 495, lineGap: 4 });
    }

    // Scope
    if (narrative?.scope_description) {
      doc.moveDown(1.5);
      doc.fillColor(colors.dark).fontSize(14).font('Helvetica-Bold').text('Audit Scope & Methodology');
      doc.moveDown(0.3);
      doc.fillColor('#374151').fontSize(11).font('Helvetica').text(narrative.scope_description, { width: 495, lineGap: 4 });
    }

    // Findings
    if (narrative?.findings_summary) {
      doc.moveDown(1.5);
      doc.fillColor(colors.dark).fontSize(14).font('Helvetica-Bold').text('Key Findings');
      doc.moveDown(0.3);
      doc.fillColor('#374151').fontSize(11).font('Helvetica').text(narrative.findings_summary, { width: 495, lineGap: 4 });
    }

    // Controls detail
    if (data.controls && data.controls.length > 0) {
      doc.addPage();
      doc.fillColor(colors.dark).fontSize(18).font('Helvetica-Bold').text('Controls Detail', 50, 50);
      doc.moveTo(50, 75).lineTo(545, 75).stroke(colors.blue);

      const riskColor = { Critical: colors.red, High: colors.amber, Medium: colors.blue, Low: colors.green };
      const statusColor = { Complete: colors.green, 'In Progress': colors.amber, 'Not Started': colors.red };

      let y = 90;
      // Table header
      doc.rect(50, y, 495, 24).fill('#0d0f14');
      doc.fillColor('white').fontSize(9).font('Helvetica-Bold');
      doc.text('ID', 58, y + 8).text('Control Name', 100, y + 8).text('Risk', 340, y + 8).text('Status', 400, y + 8).text('Evidence', 470, y + 8);
      y += 24;

      data.controls.forEach((ctrl, idx) => {
        if (y > 750) { doc.addPage(); y = 50; }
        const bg = idx % 2 === 0 ? 'white' : '#f9fafb';
        doc.rect(50, y, 495, 22).fill(bg);
        doc.fillColor('#374151').fontSize(9).font('Helvetica');
        doc.text(ctrl.control_id || '', 58, y + 7, { width: 38 });
        doc.text(ctrl.name || '', 100, y + 7, { width: 232, ellipsis: true });
        const rc = riskColor[ctrl.risk_level] || colors.gray;
        doc.fillColor(rc).text(ctrl.risk_level || '', 340, y + 7, { width: 55 });
        const sc = statusColor[ctrl.status] || colors.gray;
        doc.fillColor(sc).text(ctrl.status || '', 400, y + 7, { width: 65 });
        const evPct = ctrl.evidence_total > 0 ? `${ctrl.evidence_uploaded}/${ctrl.evidence_total}` : '—';
        doc.fillColor('#374151').text(evPct, 470, y + 7, { width: 70 });
        y += 22;
      });
    }

    // Recommendations
    if (narrative?.recommendations) {
      doc.addPage();
      doc.fillColor(colors.dark).fontSize(18).font('Helvetica-Bold').text('Recommendations', 50, 50);
      doc.moveTo(50, 75).lineTo(545, 75).stroke(colors.blue);
      doc.fillColor('#374151').fontSize(11).font('Helvetica').text(narrative.recommendations, 50, 90, { width: 495, lineGap: 4 });
    }

    // Conclusion
    if (narrative?.conclusion) {
      doc.moveDown(1.5);
      doc.fillColor(colors.dark).fontSize(14).font('Helvetica-Bold').text('Conclusion');
      doc.moveDown(0.3);
      doc.fillColor('#374151').fontSize(11).font('Helvetica').text(narrative.conclusion, { width: 495, lineGap: 4 });
    }

    // Footer on all pages
    const range = doc.bufferedPageRange();
    for (let i = 0; i < range.count; i++) {
      doc.switchToPage(range.start + i);
      doc.rect(0, doc.page.height - 40, doc.page.width, 40).fill('#f9fafb');
      doc.fillColor(colors.gray).fontSize(9).font('Helvetica')
        .text(`AuditSphere · ${data.framework} Audit Report · Confidential`, 50, doc.page.height - 26)
        .text(`Page ${i + 1} of ${range.count}`, 0, doc.page.height - 26, { align: 'right', width: doc.page.width - 50 });
    }

    doc.end();
  });
}

module.exports = { generateAuditReport };
