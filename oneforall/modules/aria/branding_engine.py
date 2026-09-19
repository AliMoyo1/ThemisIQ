"""
ARIA module -- Document branding engine.

Applies company branding templates to uploaded policy documents.
Takes a source DOCX (user-edited content) and a template DOCX
(company branding: cover page, logo, metadata tables, styles),
and produces a branded output DOCX that preserves the template's
front matter and appends the policy content after it.

Security: all file paths are validated before access. No user input
is interpolated into file operations without sanitisation.
"""
from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

log = logging.getLogger("aria.branding")

WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _sanitise(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text)).strip()


def _element_tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _element_text(el) -> str:
    runs = el.findall(f".//{{{WML}}}t")
    return "".join(r.text or "" for r in runs)


def _element_style(el) -> str:
    pPr = el.find(f"{{{WML}}}pPr")
    if pPr is not None:
        pStyle = pPr.find(f"{{{WML}}}pStyle")
        if pStyle is not None:
            return pStyle.get(f"{{{WML}}}val", "")
    return ""


def _update_paragraph_text(para_el, new_text: str):
    """Replace all run texts in a paragraph, preserving the first run's formatting."""
    runs = para_el.findall(f".//{{{WML}}}r")
    if not runs:
        return
    first_run = runs[0]
    t_el = first_run.find(f"{{{WML}}}t")
    if t_el is not None:
        t_el.text = new_text
    for run in runs[1:]:
        run.getparent().remove(run)


def _get_para_font_size_half_pt(para_el) -> int:
    """Return the font size in half-points from the first run, or 0."""
    run = para_el.find(f".//{{{WML}}}r")
    if run is None:
        return 0
    rPr = run.find(f"{{{WML}}}rPr")
    if rPr is None:
        return 0
    sz = rPr.find(f"{{{WML}}}sz")
    if sz is not None:
        try:
            return int(sz.get(f"{{{WML}}}val", "0"))
        except ValueError:
            return 0
    return 0


def _table_rows(tbl_el):
    return tbl_el.findall(f"{{{WML}}}tr")


def _table_cell_text(row_el, col: int) -> str:
    cells = row_el.findall(f"{{{WML}}}tc")
    if col < len(cells):
        return _element_text(cells[col])
    return ""


def _set_table_cell_text(row_el, col: int, text: str):
    cells = row_el.findall(f"{{{WML}}}tc")
    if col >= len(cells):
        return
    cell = cells[col]
    paras = cell.findall(f"{{{WML}}}p")
    if paras:
        _update_paragraph_text(paras[0], text)


def _add_table_row(tbl_el, values: list[str]):
    """Clone the last data row of a table and fill with new values."""
    rows = _table_rows(tbl_el)
    if len(rows) < 2:
        return
    last_row = rows[-1]
    new_row = deepcopy(last_row)
    cells = new_row.findall(f"{{{WML}}}tc")
    for i, val in enumerate(values):
        if i < len(cells):
            paras = cells[i].findall(f"{{{WML}}}p")
            if paras:
                _update_paragraph_text(paras[0], val)
    tbl_el.append(new_row)


def _is_content_start(el) -> bool:
    """True if the element looks like the start of actual policy content."""
    tag = _element_tag(el)
    if tag != "p":
        return False
    style = _element_style(el)
    text = _element_text(el).strip()
    if style in ("Heading1", "Heading2") and re.match(r"^\d+[\.\)]?\s", text):
        return True
    if text.lower().startswith(("purpose", "scope", "introduction", "objective")):
        return True
    return False


def build_policy_docx(
    content: str,
    org_name: str = "",
    doc_heading: str = "",
    control_label: str = "",
    include_preamble: bool = True,
) -> Document:
    """Parse policy markdown into a python-docx Document.

    Extracted from routes.py's export_word (PLAN-35 T03), which owns the
    only prior copy of this parser. include_preamble=True reproduces
    export_word's exact prior behavior: a centered org-name heading (level
    0) plus a control-label heading (level 1) before the parsed content --
    used for the standalone Word export, which has no branding template of
    its own to supply a cover. include_preamble=False is the authoring
    path (PLAN-35 section 7.1): the branding template supplies the cover
    and document metadata, so the generated body must start directly with
    real content and carry no preamble for apply_template()'s
    generated_body mode to append after the template's front matter.

    doc_heading, when given, is used as the level-0 heading instead of
    org_name (kept as a separate parameter for callers that already have a
    document title rather than an organisation name).
    """
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    if include_preamble:
        heading = doc.add_heading(_sanitise(doc_heading or org_name) or "Policy Document", level=0)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if control_label:
            sub = doc.add_heading(_sanitise(control_label), level=1)
            sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
        doc.add_paragraph("")

    def _add_formatted_runs(paragraph, text):
        """Parse inline markdown (bold, italic) into Word runs."""
        parts = re.split(r'(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*]+\*)', text)
        for part in parts:
            if not part:
                continue
            if part.startswith("***") and part.endswith("***"):
                run = paragraph.add_run(part[3:-3])
                run.bold = True
                run.italic = True
            elif part.startswith("**") and part.endswith("**"):
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith("*") and part.endswith("*"):
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            else:
                paragraph.add_run(part)

    # XML-invalid control characters would otherwise raise inside
    # python-docx (or silently corrupt the saved package); strip them the
    # same way _sanitise() already does for template metadata fields, but
    # per-line so legitimate newlines between lines are preserved.
    clean_content = "\n".join(_sanitise(line) for line in content.splitlines())

    lines = clean_content.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip()

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(style="List Bullet")
            _add_formatted_runs(p, stripped[2:])
        elif re.match(r'^\d+[\.\)]\s', stripped):
            p = doc.add_paragraph(style="List Number")
            _add_formatted_runs(p, re.sub(r'^\d+[\.\)]\s', '', stripped))
        elif stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].rstrip().startswith("|") and lines[i].rstrip().endswith("|"):
                row_text = lines[i].rstrip()
                if not re.match(r'^\|[\s\-:|]+\|$', row_text):
                    cells = [c.strip() for c in row_text.strip("|").split("|")]
                    table_lines.append(cells)
                i += 1
            if table_lines:
                cols = max(len(r) for r in table_lines)
                tbl = doc.add_table(rows=len(table_lines), cols=cols, style="Table Grid")
                for ri, row_cells in enumerate(table_lines):
                    for ci, cell_text in enumerate(row_cells):
                        if ci < cols:
                            cell = tbl.cell(ri, ci)
                            cell.text = ""
                            p = cell.paragraphs[0]
                            _add_formatted_runs(p, cell_text)
                            if ri == 0:
                                for run in p.runs:
                                    run.bold = True
            continue
        elif stripped == "":
            doc.add_paragraph("")
        else:
            p = doc.add_paragraph()
            _add_formatted_runs(p, stripped)

        i += 1

    return doc


def apply_template(
    *,
    source_path: str,
    template_path: str,
    output_path: str,
    logo_path: str | None = None,
    doc_title: str = "",
    doc_id: str = "",
    version: str = "1.0",
    framework: str = "",
    author_name: str = "",
    generated_body: bool = False,
) -> str:
    """
    Merge source document content into a branding template.

    Strategy:
    1. Open the template DOCX (has cover page, logo, metadata tables, styles)
    2. Keep the template body intact (cover page, tables, front matter)
    3. Update metadata fields (title, version, dates, revision history)
    4. Append source content after the template front matter
    5. Save as the output file.

    generated_body (PLAN-35 T03): the legacy heuristic mode
    (generated_body=False, unchanged default) skips the source document's
    own preamble/cover paragraphs via _is_content_start(), a narrow
    keyword match ("purpose"/"scope"/"introduction"/"objective", or a
    numbered Heading1/2) meant for uploaded documents that carry their own
    title page ahead of the real policy text. An arbitrary first heading
    that matches none of those keywords means content_started never
    becomes true and the ENTIRE source is silently dropped -- confirmed
    directly by inspecting _is_content_start. A source built by
    build_policy_docx(include_preamble=False) has no such cover to strip in
    the first place, so generated_body=True bypasses the heuristic and
    copies every paragraph/table from the source body unconditionally.

    Returns the output path.
    """
    src = Path(source_path)
    tpl = Path(template_path)
    out = Path(output_path)

    if not src.exists():
        raise FileNotFoundError(f"Source document not found: {source_path}")
    if not tpl.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    branded = Document(str(tpl))
    source = Document(str(src))
    body = branded.element.body
    today = datetime.now().strftime("%Y/%m/%d")
    year = datetime.now().strftime("%Y")
    title = _sanitise(doc_title) or "Policy Document"

    # ── Update template metadata ─────────────────────────────────
    title_updated = False
    for child in body:
        if _element_tag(child) != "p":
            continue
        sz = _get_para_font_size_half_pt(child)
        text = _element_text(child).strip()

        if not title_updated and sz >= 36 and text and not text.startswith("VERSION"):
            if not re.match(r"^(Information Security|The content)", text):
                _update_paragraph_text(child, title.upper())
                title_updated = True
                continue

        if re.match(r"VERSION\s+\d", text, re.IGNORECASE):
            _update_paragraph_text(child, f"VERSION {version} OF {year}")

    # ── Update metadata table (has "Reference:" in first row) ────
    for child in body:
        if _element_tag(child) != "tbl":
            continue
        rows = _table_rows(child)
        if not rows:
            continue
        first_row_text = " ".join(
            _table_cell_text(rows[0], c) for c in range(4)
        ).lower()

        if "reference" in first_row_text:
            _set_table_cell_text(rows[0], 1, title)
            _set_table_cell_text(rows[0], 3, doc_id)
            if len(rows) > 1:
                _set_table_cell_text(rows[1], 3, version)
            if len(rows) > 2:
                _set_table_cell_text(rows[2], 1, today)
                _set_table_cell_text(rows[2], 3, today)
            continue

        if "version number" in first_row_text or "version" in first_row_text and "author" in first_row_text:
            _add_table_row(child, [
                version,
                author_name or "ThemisIQ",
                "Generated via ThemisIQ ARIA",
                today,
            ])

    # ── Find insertion point (before sectPr) ─────────────────────
    sect_pr = body.find(f"{{{WML}}}sectPr")
    if sect_pr is None:
        children = list(body)
        sect_pr = children[-1] if children else None

    # ── Copy source content, skipping the title/preamble block ──
    content_started = generated_body

    for element in source.element.body:
        tag = _element_tag(element)
        if tag == "sectPr":
            continue
        if tag not in ("p", "tbl"):
            continue

        if not content_started:
            if tag == "tbl":
                content_started = True
            elif _is_content_start(element):
                content_started = True
            else:
                continue

        if content_started:
            new_el = deepcopy(element)
            if sect_pr is not None:
                sect_pr.addprevious(new_el)
            else:
                body.append(new_el)

    # ── Header logo fallback (for templates with logo in header) ─
    if logo_path:
        logo = Path(logo_path)
        if logo.exists():
            try:
                for section in branded.sections:
                    header = section.header
                    header.is_linked_to_previous = False
                    hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
                    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    run = hp.add_run()
                    run.add_picture(str(logo), width=Cm(3))
            except Exception as exc:
                log.warning("Could not add logo to header: %s", exc)

    # ── Save branded document ────────────────────────────────────
    out.parent.mkdir(parents=True, exist_ok=True)
    branded.save(str(out))
    log.info("Branded document saved: %s", out)

    return str(out)
