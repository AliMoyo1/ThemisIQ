'use strict';
const PDFDocument = require('pdfkit');
const path = require('path');
const fs   = require('fs');

function generateAuditReportPDF(auditData, controls, narrative) {
  return new Promise((resolve, reject) => {
    const dir = path.join(__dirname, '../../data/reports');
    fs.mkdirSync(dir, { recursive: true });
    const fileName = `report-${auditData.id}-${Date.now()}.pdf`;
    const filePath = path.join(dir, fileName);

    const doc    = new PDFDocument({ margin: 50, size: 'A4' });
    const stream = fs.createWriteStream(filePath);
    doc.pipe(stream);

    const DARK='#0d0f14', ACCENT='#4f8ef7', GREEN='#3ecf84', AMBER='#f5a623', RED='#f25c5c', MUTED='#7a8099';

    // Header
    doc.rect(0,0,doc.page.width,80).fill(DARK);
    doc.fillColor('white').fontSize(22).font('Helvetica-Bold').text('AuditSphere',50,22);
    doc.fillColor(ACCENT).fontSize(11).font('Helvetica').text('Compliance Audit Report',50,50);
    doc.fillColor('#aaa').fontSize(9).text('Generated: '+new Date().toLocaleDateString(),400,45,{align:'right',width:145});

    // Title
    doc.fillColor(DARK).fontSize(17).font('Helvetica-Bold').text(auditData.name||'Audit Report',50,100);
    doc.fillColor(MUTED).fontSize(10).font('Helvetica').text(`Framework: ${auditData.framework||''} · Type: ${auditData.audit_type||''} · Auditor: ${auditData.auditor||'N/A'}`,50,122);

    // Status pill
    const stColor = narrative?.overall_status==='On Track' ? GREEN : narrative?.overall_status==='At Risk' ? AMBER : RED;
    doc.rect(50,140,100,20).fill(stColor+'22');
    doc.fillColor(stColor).fontSize(9).font('Helvetica-Bold').text(narrative?.overall_status||'In Progress',55,146);

    // Stats row
    const stats=[
      {label:'Total Controls',value:String(auditData.totalControls||0),color:ACCENT},
      {label:'Complete',value:String(auditData.complete||0),color:GREEN},
      {label:'Pending',value:String(auditData.pending||0),color:AMBER},
      {label:'Overdue',value:String(auditData.overdue||0),color:RED},
      {label:'Completion',value:(auditData.completionPct||0)+'%',color:ACCENT},
    ];
    const bw=90,bh=52,bx=50,by=172,bg=8;
    stats.forEach((s,i)=>{
      const x=bx+i*(bw+bg);
      doc.rect(x,by,bw,bh).fill('#f5f5f5');
      doc.fillColor(s.color).fontSize(18).font('Helvetica-Bold').text(s.value,x+4,by+8,{width:bw-8,align:'center'});
      doc.fillColor(MUTED).fontSize(7).font('Helvetica').text(s.label,x+4,by+34,{width:bw-8,align:'center'});
    });

    let y=240;

    // Executive summary
    if (narrative?.executive_summary) {
      doc.fillColor(DARK).fontSize(13).font('Helvetica-Bold').text('Executive Summary',50,y); y+=18;
      doc.rect(50,y,3,55).fill(ACCENT);
      doc.fillColor('#333').fontSize(10).font('Helvetica').text(narrative.executive_summary,58,y,{width:485,lineGap:3}); y+=70;
    }

    // Key findings
    if (narrative?.key_findings?.length) {
      if (y>680){doc.addPage();y=50;}
      doc.fillColor(DARK).fontSize(13).font('Helvetica-Bold').text('Key Findings',50,y); y+=16;
      narrative.key_findings.forEach(f=>{
        doc.rect(50,y+4,4,4).fill(ACCENT);
        doc.fillColor('#333').fontSize(10).font('Helvetica').text(f,60,y,{width:480}); y+=16;
      }); y+=8;
    }

    // Controls table
    if (y>650){doc.addPage();y=50;}
    doc.fillColor(DARK).fontSize(13).font('Helvetica-Bold').text('Controls Summary',50,y); y+=18;
    doc.rect(50,y,495,20).fill(DARK);
    doc.fillColor('white').fontSize(8).font('Helvetica-Bold');
    ['Control ID','Name','Risk','Status','Evidence'].forEach((h,i)=>{
      doc.text(h,50+[0,70,290,360,430][i],y+6,{width:[65,215,65,65,60][i]});
    }); y+=20;

    (controls||[]).slice(0,35).forEach((c,idx)=>{
      if(y>720){doc.addPage();y=50;}
      doc.rect(50,y,495,18).fill(idx%2===0?'#f8f9fa':'white');
      const rClr={Critical:RED,High:AMBER,Medium:ACCENT,Low:GREEN}[c.risk_level]||MUTED;
      const sClr=c.status==='complete'?GREEN:c.status==='in_progress'?AMBER:RED;
      doc.fillColor(ACCENT).fontSize(7).font('Helvetica-Bold').text(c.control_id||'',55,y+5,{width:60});
      doc.fillColor('#333').font('Helvetica').text((c.name||'').slice(0,38),115,y+5,{width:170});
      doc.fillColor(rClr).text(c.risk_level||'',290,y+5,{width:60});
      doc.fillColor(sClr).text((c.status||'').replace('_',' '),355,y+5,{width:70});
      doc.fillColor('#333').text(`${c.evidence_count||0}/${c.evidence_required||1}`,430,y+5,{width:60});
      y+=18;
    });

    // Conclusion
    y+=14; if(y>680){doc.addPage();y=50;}
    if(narrative?.conclusion){
      doc.fillColor(DARK).fontSize(13).font('Helvetica-Bold').text('Conclusion',50,y); y+=16;
      doc.fillColor('#333').fontSize(10).font('Helvetica').text(narrative.conclusion,50,y,{width:495}); y+=40;
    }

    // Footer
    const fy=doc.page.height-38;
    doc.rect(0,fy,doc.page.width,38).fill(DARK);
    doc.fillColor(MUTED).fontSize(8).font('Helvetica').text('AuditSphere Compliance Management · Confidential',50,fy+14);
    doc.fillColor(MUTED).text(new Date().toISOString(),400,fy+14,{align:'right',width:145});

    doc.end();
    stream.on('finish', ()=>resolve({filePath,fileName}));
    stream.on('error', reject);
  });
}

module.exports = { generateAuditReportPDF };
