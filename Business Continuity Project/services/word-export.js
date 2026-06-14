// Render BCP plans and exercises to branded .docx files.
//
// Uses the `docx` package. Exposes two builders:
//   buildPlanDoc(plan, { tenantName, generatedBy }) -> Buffer
//   buildExerciseDoc(exercise, { tenantName, generatedBy }) -> Buffer
//
// Both accept Markdown-ish text (headings via # / ##, bullets via * / -)
// and map it to proper Word styles so the output opens cleanly in Word,
// Google Docs, and Pages.

const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Header, Footer, PageNumber, Table, TableRow, TableCell, WidthType,
  BorderStyle, ShadingType, TabStopType, TabStopPosition, UnderlineType,
  LevelFormat
} = require('docx');

const { tokenize } = require('./markdown');

// ------------------- Brand constants -------------------
const BRAND = {
  primary: '3A3F2E',     // olive/charcoal
  accent:  '8A8A5B',     // olive accent
  accentSoft: 'C9C79F',
  text: '1C1C1C',
  muted: '6B6B6B',
  rule:  'D7D1BF',
  cream: 'F4F1E8'
};

// ------------------- Low-level helpers -------------------

function textRun(text, opts = {}) {
  return new TextRun({
    text: (text === null || text === undefined) ? '' : String(text),
    font: opts.font || 'Calibri',
    size: opts.size || 22,          // half-points -> 11pt
    bold: !!opts.bold,
    italics: !!opts.italics,
    color: opts.color || BRAND.text,
    underline: opts.underline ? { type: UnderlineType.SINGLE } : undefined,
    break: opts.break || undefined
  });
}

function para(children, opts = {}) {
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

function spacer(size = 120) {
  return new Paragraph({
    children: [new TextRun({ text: '' })],
    spacing: { before: size, after: size }
  });
}

function horizontalRule() {
  return new Paragraph({
    border: {
      bottom: { color: BRAND.rule, size: 6, style: BorderStyle.SINGLE, space: 1 }
    },
    spacing: { before: 80, after: 160 }
  });
}

function pageBreak() {
  return new Paragraph({ children: [new TextRun({ text: '', break: 1 })], pageBreakBefore: true });
}

// ------------------- Markdown body parser → docx nodes -------------------
// Uses services/markdown.tokenize() to walk blocks so pipe-tables, headings,
// paragraphs, bullets, and numbered lists all render as native Word elements.

function parseBody(text) {
  if (!text || !String(text).trim()) {
    return [para(textRun('No content provided.', { italics: true, color: BRAND.muted }))];
  }
  const blocks = tokenize(text);
  const out = [];

  const sizeMap = { 1: 32, 2: 28, 3: 24, 4: 22, 5: 20, 6: 20 };
  const levelMap = {
    1: HeadingLevel.HEADING_1,
    2: HeadingLevel.HEADING_2,
    3: HeadingLevel.HEADING_3,
    4: HeadingLevel.HEADING_4,
    5: HeadingLevel.HEADING_5,
    6: HeadingLevel.HEADING_6
  };

  for (const b of blocks) {
    switch (b.kind) {
      case 'heading':
        out.push(new Paragraph({
          heading: levelMap[b.depth] || HeadingLevel.HEADING_4,
          spacing: { before: b.depth === 1 ? 280 : 200, after: 120 },
          children: [textRun(b.text, {
            bold: true,
            color: b.depth <= 2 ? BRAND.primary : BRAND.accent,
            size: sizeMap[b.depth] || 22
          })]
        }));
        break;

      case 'paragraph':
        out.push(para(parseInline(b.text)));
        break;

      case 'bullet':
        out.push(new Paragraph({
          bullet: { level: 0 },
          spacing: { before: 40, after: 40 },
          children: parseInline(b.text)
        }));
        break;

      case 'numbered':
        out.push(new Paragraph({
          numbering: { reference: 'bcm-numbering', level: 0 },
          spacing: { before: 40, after: 40 },
          children: parseInline(b.text)
        }));
        break;

      case 'hr':
        out.push(horizontalRule());
        break;

      case 'table':
        out.push(buildTable(b));
        out.push(new Paragraph({ children: [textRun('')], spacing: { before: 80, after: 80 } }));
        break;
    }
  }
  return out;
}

// Build a styled Word table from a tokenised pipe-table block.
function buildTable({ header, aligns, rows }) {
  const alignMap = {
    center: AlignmentType.CENTER,
    right:  AlignmentType.RIGHT,
    left:   AlignmentType.LEFT
  };
  const cellMargins = { top: 100, bottom: 100, left: 140, right: 140 };

  const headerRow = new TableRow({
    tableHeader: true,
    children: header.map((cell, idx) => new TableCell({
      margins: cellMargins,
      shading: { fill: 'EEE8D3', type: ShadingType.CLEAR, color: 'auto' },
      children: [new Paragraph({
        alignment: alignMap[aligns[idx]] || AlignmentType.LEFT,
        spacing: { before: 0, after: 0 },
        children: [textRun(cell, { bold: true, color: BRAND.primary, size: 21 })]
      })]
    }))
  });

  const bodyRows = rows.map((r, rowIdx) => {
    const zebra = rowIdx % 2 === 1;
    return new TableRow({
      children: r.map((cell, idx) => new TableCell({
        margins: cellMargins,
        shading: zebra ? { fill: 'FAF8F0', type: ShadingType.CLEAR, color: 'auto' } : undefined,
        children: [new Paragraph({
          alignment: alignMap[aligns[idx]] || AlignmentType.LEFT,
          spacing: { before: 0, after: 0 },
          children: parseInline(cell).map(run => {
            // Shrink body cell text slightly for density
            return run;
          })
        })]
      }))
    });
  });

  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top:             { style: BorderStyle.SINGLE, size: 6, color: BRAND.rule },
      bottom:          { style: BorderStyle.SINGLE, size: 6, color: BRAND.rule },
      left:            { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
      right:           { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
      insideHorizontal:{ style: BorderStyle.SINGLE, size: 2, color: BRAND.rule },
      insideVertical:  { style: BorderStyle.SINGLE, size: 2, color: BRAND.rule }
    },
    rows: [headerRow, ...bodyRows]
  });
}

// Very small inline parser for **bold** and *italic* fragments.
function parseInline(text) {
  const runs = [];
  // Match **bold** then *italic*
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) runs.push(textRun(text.slice(last, m.index)));
    const frag = m[0];
    if (frag.startsWith('**')) {
      runs.push(textRun(frag.slice(2, -2), { bold: true }));
    } else if (frag.startsWith('`')) {
      runs.push(textRun(frag.slice(1, -1), { font: 'Consolas', color: BRAND.primary }));
    } else if (frag.startsWith('*')) {
      runs.push(textRun(frag.slice(1, -1), { italics: true }));
    }
    last = m.index + frag.length;
  }
  if (last < text.length) runs.push(textRun(text.slice(last)));
  return runs.length ? runs : [textRun(text)];
}

// ------------------- Cover block -------------------

function coverBlock({ title, subtitle, tenantName, generatedBy, meta = [] }) {
  const nodes = [];
  // Branded top rule
  nodes.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { before: 0, after: 80 },
    children: [textRun(tenantName || '', { bold: true, color: BRAND.accent, size: 18 })]
  }));
  nodes.push(horizontalRule());

  // Display title
  nodes.push(new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { before: 1200, after: 120 },
    children: [textRun(title, {
      font: 'Cambria', bold: true, size: 56, color: BRAND.primary
    })]
  }));
  if (subtitle) {
    nodes.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { before: 0, after: 120 },
      children: [textRun(subtitle, { font: 'Cambria', size: 30, color: BRAND.accent, italics: true })]
    }));
  }
  nodes.push(horizontalRule());

  // Meta table
  if (meta.length) {
    const rows = meta.map(([k, v]) => new TableRow({
      children: [
        new TableCell({
          width: { size: 30, type: WidthType.PERCENTAGE },
          shading: { fill: BRAND.cream, type: ShadingType.CLEAR, color: 'auto' },
          children: [para(textRun(k, { bold: true, color: BRAND.primary }))]
        }),
        new TableCell({
          width: { size: 70, type: WidthType.PERCENTAGE },
          children: [para(textRun(v || '—'))]
        })
      ]
    }));
    nodes.push(new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      borders: {
        top:    { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
        bottom: { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
        left:   { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
        right:  { style: BorderStyle.SINGLE, size: 4, color: BRAND.rule },
        insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: BRAND.rule },
        insideVertical:   { style: BorderStyle.SINGLE, size: 2, color: BRAND.rule }
      },
      rows
    }));
  }

  // Footnote
  nodes.push(new Paragraph({
    spacing: { before: 600, after: 0 },
    children: [textRun(
      `Generated on ${new Date().toISOString().slice(0, 10)}` +
      (generatedBy ? ` by ${generatedBy}` : '') +
      ' via BCM Sentinel.',
      { size: 18, italics: true, color: BRAND.muted }
    )]
  }));
  nodes.push(pageBreak());
  return nodes;
}

function sectionHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 240, after: 120 },
    border: { bottom: { color: BRAND.accent, size: 8, style: BorderStyle.SINGLE, space: 2 } },
    children: [textRun(text, { bold: true, color: BRAND.primary, size: 30 })]
  });
}

// ------------------- Page chrome (header + footer) -------------------

function makeHeader(tenantName) {
  return new Header({
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      children: [textRun(tenantName || 'BCM Sentinel', { color: BRAND.muted, size: 18 })]
    })]
  });
}

function makeFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [
        textRun('Confidential — BCM Sentinel  ·  Page ', { color: BRAND.muted, size: 16 }),
        new TextRun({ children: [PageNumber.CURRENT], color: BRAND.muted, size: 16 }),
        textRun(' of ', { color: BRAND.muted, size: 16 }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], color: BRAND.muted, size: 16 })
      ]
    })]
  });
}

function baseDocOptions() {
  return {
    creator: 'BCM Sentinel',
    description: 'Generated by BCM Sentinel',
    styles: {
      default: {
        document: {
          run: { font: 'Calibri', size: 22, color: BRAND.text }
        }
      },
      paragraphStyles: [{
        id: 'normal',
        name: 'Normal',
        run: { font: 'Calibri', size: 22, color: BRAND.text },
        paragraph: { spacing: { line: 300 } }
      }]
    },
    numbering: {
      config: [{
        reference: 'bcm-numbering',
        levels: [{
          level: 0,
          format: LevelFormat.DECIMAL,
          text: '%1.',
          alignment: AlignmentType.START,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }]
    }
  };
}

// ------------------- Public builders -------------------

async function buildPlanDoc(plan, { tenantName, generatedBy } = {}) {
  const meta = [
    ['Plan ID',        String(plan.id)],
    ['Version',        plan.version || '1.0'],
    ['Status',         plan.status || 'draft'],
    ['Scope',          plan.scope || '—'],
    ['Owner',          plan.owner || '—'],
    ['Last reviewed',  plan.last_reviewed || '—'],
    ['Next review',    plan.next_review || '—']
  ];

  const children = [
    ...coverBlock({
      title:    plan.title,
      subtitle: 'Business Continuity Plan',
      tenantName,
      generatedBy,
      meta
    }),
    sectionHeading('Executive summary'),
    para(textRun(
      `This document defines the business continuity arrangements for ${plan.scope || plan.title}. ` +
      `It covers roles, response procedures, recovery objectives, and review cadence required to ` +
      `maintain operational resilience against the disruptions most likely to affect the service.`,
      { color: BRAND.text }
    )),
    sectionHeading('Plan details'),
    ...parseBody(plan.content || '')
  ];

  if (plan.next_review) {
    children.push(sectionHeading('Review cadence'));
    children.push(para(textRun(
      `Next scheduled review: ${plan.next_review}. ` +
      (plan.last_reviewed ? `Last reviewed ${plan.last_reviewed}.` : 'No prior review recorded.'),
      { italics: true, color: BRAND.muted }
    )));
  }

  const doc = new Document({
    ...baseDocOptions(),
    title: plan.title,
    sections: [{
      headers: { default: makeHeader(tenantName) },
      footers: { default: makeFooter() },
      properties: { page: { margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 } } },
      children
    }]
  });

  return Packer.toBuffer(doc);
}

async function buildExerciseDoc(exercise, { tenantName, generatedBy } = {}) {
  const typeLabel = {
    tabletop:    'Tabletop exercise',
    walkthrough: 'Walkthrough',
    simulation:  'Simulation',
    full:        'Full-scale exercise'
  }[exercise.type] || 'Exercise';

  const meta = [
    ['Exercise ID',   String(exercise.id)],
    ['Type',          typeLabel],
    ['Status',        exercise.status || 'planned'],
    ['Scheduled',     exercise.scheduled_date || '—'],
    ['Duration',      exercise.duration_minutes ? `${exercise.duration_minutes} minutes` : '—'],
    ['Facilitator',   exercise.facilitator || '—'],
    ['Linked plan',   exercise.plan_title || '—'],
    ['Outcome',       exercise.outcome || '—']
  ];

  const children = [
    ...coverBlock({
      title:    exercise.title,
      subtitle: typeLabel,
      tenantName,
      generatedBy,
      meta
    })
  ];

  // Scenario
  children.push(sectionHeading('Scenario'));
  children.push(...(exercise.scenario
    ? parseBody(exercise.scenario)
    : [para(textRun('No scenario captured.', { italics: true, color: BRAND.muted }))]));

  // Objectives
  children.push(sectionHeading('Objectives'));
  children.push(...(exercise.objectives
    ? parseBody(exercise.objectives)
    : [para(textRun('No objectives captured.', { italics: true, color: BRAND.muted }))]));

  // Participants
  children.push(sectionHeading('Participants'));
  children.push(para(textRun(exercise.participants || 'Not recorded.',
    exercise.participants ? {} : { italics: true, color: BRAND.muted })));

  // Exercise conduct notes (by type)
  const conductByType = {
    tabletop:
      'Facilitator presents the scenario to participants around a table. No systems are touched. ' +
      'Participants talk through their decisions, hand-offs, and gaps. Injects may be paced at 10–15 minute intervals.',
    walkthrough:
      'Team walks through the plan step by step to verify each procedure is accurate, role assignments are current, ' +
      'and dependencies are understood. Used to validate a plan rather than stress-test response.',
    simulation:
      'A controlled test where response teams execute key steps against a simulated environment. ' +
      'Real notifications may be sent to mailing lists; production systems remain untouched unless otherwise scoped.',
    full:
      'Full-scale exercise — production systems, third-party vendors, and on-call teams are engaged. ' +
      'Requires executive sign-off and a rollback plan. Observers measure against documented objectives.'
  };
  if (conductByType[exercise.type]) {
    children.push(sectionHeading('How this exercise was conducted'));
    children.push(para(textRun(conductByType[exercise.type])));
  }

  // AAR section
  const hasAar = exercise.aar_summary || exercise.aar_strengths || exercise.aar_gaps || exercise.aar_actions;
  children.push(sectionHeading('After-Action Report'));
  if (!hasAar) {
    children.push(para(textRun('No after-action report captured yet.', { italics: true, color: BRAND.muted })));
  } else {
    if (exercise.aar_summary) {
      children.push(para(textRun('Summary', { bold: true, color: BRAND.primary, size: 24 }),
        { spacing: { before: 160, after: 80 } }));
      children.push(...parseBody(exercise.aar_summary));
    }
    if (exercise.aar_strengths) {
      children.push(para(textRun('Strengths', { bold: true, color: BRAND.primary, size: 24 }),
        { spacing: { before: 160, after: 80 } }));
      children.push(...parseBody(exercise.aar_strengths));
    }
    if (exercise.aar_gaps) {
      children.push(para(textRun('Gaps & observations', { bold: true, color: BRAND.primary, size: 24 }),
        { spacing: { before: 160, after: 80 } }));
      children.push(...parseBody(exercise.aar_gaps));
    }
    if (exercise.aar_actions) {
      children.push(para(textRun('Follow-up actions', { bold: true, color: BRAND.primary, size: 24 }),
        { spacing: { before: 160, after: 80 } }));
      children.push(...parseBody(exercise.aar_actions));
    }
  }

  // Sign-off
  children.push(sectionHeading('Sign-off'));
  children.push(para([
    textRun('Facilitator: ', { bold: true }),
    textRun((exercise.facilitator || '_________________________')),
  ]));
  children.push(para([
    textRun('Date: ', { bold: true }),
    textRun('_________________________')
  ]));
  children.push(para([
    textRun('Signature: ', { bold: true }),
    textRun('_________________________')
  ]));

  const doc = new Document({
    ...baseDocOptions(),
    title: exercise.title,
    sections: [{
      headers: { default: makeHeader(tenantName) },
      footers: { default: makeFooter() },
      properties: { page: { margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 } } },
      children
    }]
  });

  return Packer.toBuffer(doc);
}

// Sanitises a string so it is safe as a filename.
function safeFilename(name) {
  return String(name || 'document')
    .replace(/[^a-z0-9\-_. ]+/gi, '')
    .replace(/\s+/g, '_')
    .slice(0, 80) || 'document';
}

module.exports = { buildPlanDoc, buildExerciseDoc, safeFilename };
