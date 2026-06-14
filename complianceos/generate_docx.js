const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, HeadingLevel, AlignmentType, BorderStyle, WidthType,
  ShadingType, PageNumber, NumberFormat, LevelFormat, TabStopType,
  TabStopPosition, VerticalAlign, ImageRun
} = require('docx');
const fs = require('fs');

// ── Input ────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
if (args.length < 2) {
  console.error('Usage: node generate_docx.js <input_json> <output_docx>');
  process.exit(1);
}

const inputPath  = args[0];
const outputPath = args[1];
const data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));

const {
  title        = 'Compliance Policy Document',
  framework    = '',
  control_ref  = '',
  org_name     = 'Your Organisation',
  content      = '',
  generated_at = new Date().toISOString().slice(0, 10)
} = data;

// ── Colour palette ───────────────────────────────────────────────────────────
const NAVY   = '1A2744';
const ACCENT = '1E3A5F';
const LIGHT  = 'EAF2FB';
const BORDER_COLOR = 'BDC3C7';

// ── Helpers ──────────────────────────────────────────────────────────────────
function hr() {
  return new Paragraph({
    paragraph: {},
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 1 } },
    spacing: { before: 120, after: 120 }
  });
}

function spacer(before = 80, after = 80) {
  return new Paragraph({ children: [], spacing: { before, after } });
}

function metaRow(label, value) {
  const border = { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR };
  const borders = { top: border, bottom: border, left: border, right: border };
  return new TableRow({
    children: [
      new TableCell({
        borders, width: { size: 2200, type: WidthType.DXA },
        shading: { fill: 'EDF2F7', type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 140, right: 140 },
        children: [new Paragraph({
          children: [new TextRun({ text: label, bold: true, font: 'Arial', size: 18, color: '374151' })]
        })]
      }),
      new TableCell({
        borders, width: { size: 7160, type: WidthType.DXA },
        margins: { top: 80, bottom: 80, left: 140, right: 140 },
        children: [new Paragraph({
          children: [new TextRun({ text: value, font: 'Arial', size: 18, color: '1F2937' })]
        })]
      })
    ]
  });
}

// ── Parse markdown into docx elements ────────────────────────────────────────
function parseMarkdown(md) {
  const lines = md.split('\n');
  const elements = [];
  let inNumberedList = false;
  let inBulletList   = false;
  let listCounter    = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip empty lines but reset list state
    if (!trimmed) {
      inNumberedList = false;
      inBulletList   = false;
      listCounter    = 0;
      elements.push(spacer(40, 40));
      continue;
    }

    // H1
    if (trimmed.startsWith('# ')) {
      const text = trimmed.slice(2).trim();
      elements.push(new Paragraph({
        heading: HeadingLevel.HEADING_1,
        children: [new TextRun({ text, font: 'Arial', bold: true, color: NAVY })]
      }));
      continue;
    }

    // H2
    if (trimmed.startsWith('## ')) {
      const text = trimmed.slice(3).trim();
      elements.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        children: [new TextRun({ text, font: 'Arial', bold: true, color: ACCENT })]
      }));
      elements.push(hr());
      continue;
    }

    // H3
    if (trimmed.startsWith('### ')) {
      const text = trimmed.slice(4).trim();
      elements.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        children: [new TextRun({ text, font: 'Arial', bold: true, color: '374151' })]
      }));
      continue;
    }

    // Horizontal rule
    if (trimmed === '---' || trimmed === '***') {
      elements.push(hr());
      continue;
    }

    // Numbered list  1. ...
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
    if (numMatch) {
      inBulletList = false;
      listCounter++;
      elements.push(new Paragraph({
        numbering: { reference: 'numbers', level: 0 },
        children: parseInline(numMatch[2])
      }));
      continue;
    }

    // Bullet list  - ... or * ...
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      inNumberedList = false;
      const text = trimmed.slice(2).trim();
      elements.push(new Paragraph({
        numbering: { reference: 'bullets', level: 0 },
        children: parseInline(text)
      }));
      continue;
    }

    // Bold metadata lines  **Key:** Value
    const boldLineMatch = trimmed.match(/^\*\*([^*]+)\*\*:?\s*(.*)/);
    if (boldLineMatch && !trimmed.includes(' ') === false) {
      elements.push(new Paragraph({
        children: [
          new TextRun({ text: boldLineMatch[1] + ': ', font: 'Arial', size: 20, bold: true, color: '1F2937' }),
          new TextRun({ text: boldLineMatch[2], font: 'Arial', size: 20, color: '374151' })
        ],
        spacing: { before: 60, after: 60 }
      }));
      continue;
    }

    // Italic note  *text*
    if (trimmed.startsWith('*') && trimmed.endsWith('*') && !trimmed.startsWith('**')) {
      const text = trimmed.slice(1, -1);
      elements.push(new Paragraph({
        children: [new TextRun({ text, font: 'Arial', size: 18, italics: true, color: '6B7280' })],
        spacing: { before: 80, after: 80 }
      }));
      continue;
    }

    // Regular paragraph
    elements.push(new Paragraph({
      children: parseInline(trimmed),
      spacing: { before: 60, after: 60 }
    }));
  }

  return elements;
}

// Parse inline markdown: **bold**, *italic*, `code`
function parseInline(text) {
  const runs = [];
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // Text before match
    if (match.index > lastIndex) {
      runs.push(new TextRun({
        text: text.slice(lastIndex, match.index),
        font: 'Arial', size: 20, color: '1F2937'
      }));
    }
    if (match[2]) {
      // **bold**
      runs.push(new TextRun({ text: match[2], font: 'Arial', size: 20, bold: true, color: '1A2744' }));
    } else if (match[3]) {
      // *italic*
      runs.push(new TextRun({ text: match[3], font: 'Arial', size: 20, italics: true, color: '374151' }));
    } else if (match[4]) {
      // `code`
      runs.push(new TextRun({ text: match[4], font: 'Courier New', size: 18, color: '7C3AED' }));
    }
    lastIndex = match.index + match[0].length;
  }

  // Remaining text
  if (lastIndex < text.length) {
    runs.push(new TextRun({
      text: text.slice(lastIndex),
      font: 'Arial', size: 20, color: '1F2937'
    }));
  }

  if (runs.length === 0) {
    runs.push(new TextRun({ text, font: 'Arial', size: 20, color: '1F2937' }));
  }

  return runs;
}

// ── Document ──────────────────────────────────────────────────────────────────
// Extract document metadata from first lines of content
let docTitle = title;
let cleanContent = content;

// Try to extract H1 title from markdown
const h1Match = content.match(/^#\s+(.+)/m);
if (h1Match) docTitle = h1Match[1].replace(/\*\*/g, '').trim();

// Extract metadata fields  
const docRef     = content.match(/\*\*Document Reference:\*\*\s*([^\n]+)/)?.[1]?.trim() || `${framework}-${control_ref}-001`;
const version    = content.match(/\*\*Version:\*\*\s*([^\n]+)/)?.[1]?.trim() || '1.0';
const classific  = content.match(/\*\*Classification:\*\*\s*([^\n]+)/)?.[1]?.trim() || 'Internal';
const reviewCycle= content.match(/\*\*Review Cycle:\*\*\s*([^\n]+)/)?.[1]?.trim() || 'Annual';

const bodyElements = parseMarkdown(content);

const doc = new Document({
  numbering: {
    config: [
      {
        reference: 'bullets',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
      {
        reference: 'numbers',
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: '%1.',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }
    ]
  },
  styles: {
    default: {
      document: { run: { font: 'Arial', size: 20 } }
    },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 40, bold: true, font: 'Arial', color: NAVY },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 0 }
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Arial', color: ACCENT },
        paragraph: { spacing: { before: 280, after: 100 }, outlineLevel: 1 }
      },
      {
        id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, font: 'Arial', color: '374151' },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 }
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1440, right: 1260, bottom: 1440, left: 1260 }
      }
    },
    headers: {
      default: new Header({
        children: [
          new Paragraph({
            children: [
              new TextRun({ text: org_name + '  |  ', font: 'Arial', size: 16, color: '6B7280' }),
              new TextRun({ text: framework, font: 'Arial', size: 16, bold: true, color: ACCENT }),
              new TextRun({ text: '  |  ' + control_ref, font: 'Arial', size: 16, color: '6B7280' })
            ],
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: ACCENT, space: 1 } },
            spacing: { after: 160 }
          })
        ]
      })
    },
    footers: {
      default: new Footer({
        children: [
          new Paragraph({
            children: [
              new TextRun({ text: 'CONFIDENTIAL — ' + org_name + '    ', font: 'Arial', size: 16, color: '9CA3AF' }),
              new TextRun({ text: 'Version ' + version + '  |  Generated: ' + generated_at + '    ', font: 'Arial', size: 16, color: '9CA3AF' }),
              new TextRun({ children: [PageNumber.CURRENT], font: 'Arial', size: 16, color: '9CA3AF' }),
              new TextRun({ text: ' of ', font: 'Arial', size: 16, color: '9CA3AF' }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: 'Arial', size: 16, color: '9CA3AF' })
            ],
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: BORDER_COLOR, space: 1 } },
            spacing: { before: 120 },
            alignment: AlignmentType.RIGHT
          })
        ]
      })
    },
    children: [
      // ── Cover block ──────────────────────────────────────────────────────
      new Paragraph({
        children: [new TextRun({ text: framework.toUpperCase(), font: 'Arial', size: 18, bold: true, color: 'FFFFFF' })],
        shading: { fill: NAVY, type: ShadingType.CLEAR },
        spacing: { before: 0, after: 0 },
        indent: { left: 200, right: 200 },
        border: {
          top:    { style: BorderStyle.SINGLE, size: 1, color: NAVY },
          left:   { style: BorderStyle.SINGLE, size: 1, color: NAVY },
          right:  { style: BorderStyle.SINGLE, size: 1, color: NAVY },
        }
      }),
      new Paragraph({
        children: [new TextRun({ text: docTitle, font: 'Arial', size: 52, bold: true, color: NAVY })],
        spacing: { before: 300, after: 160 }
      }),
      new Paragraph({
        children: [new TextRun({ text: org_name, font: 'Arial', size: 24, color: '374151' })],
        spacing: { before: 0, after: 40 }
      }),
      new Paragraph({
        children: [new TextRun({ text: `Control Reference: ${control_ref}`, font: 'Arial', size: 20, color: '6B7280' })],
        spacing: { before: 0, after: 320 }
      }),

      // ── Metadata table ────────────────────────────────────────────────────
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [2200, 7160],
        rows: [
          metaRow('Document Reference', docRef),
          metaRow('Framework',          framework),
          metaRow('Version',            version),
          metaRow('Classification',     classific),
          metaRow('Review Cycle',       reviewCycle),
          metaRow('Date Generated',     generated_at),
          metaRow('Organisation',       org_name),
        ]
      }),
      spacer(320, 200),

      // ── Body content ──────────────────────────────────────────────────────
      ...bodyElements,

      spacer(200, 80),
      hr(),
      new Paragraph({
        children: [new TextRun({
          text: '⚠  This document is a draft generated by ARIA AI. It must be reviewed, tailored to your organisation, and formally approved before use.',
          font: 'Arial', size: 16, italics: true, color: '9CA3AF'
        })],
        spacing: { before: 120, after: 80 }
      })
    ]
  }]
});

// ── Write output ─────────────────────────────────────────────────────────────
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outputPath, buf);
  console.log('OK:' + outputPath);
}).catch(err => {
  console.error('ERROR:' + err.message);
  process.exit(1);
});
