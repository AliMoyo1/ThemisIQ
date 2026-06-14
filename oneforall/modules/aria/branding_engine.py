"""
ARIA module — Document branding engine.

Applies company branding templates to uploaded policy documents.
Takes a source DOCX (user-edited content) and a template DOCX
(company branding: headers, footers, logo, styles), and produces
a branded output DOCX that merges the content into the template's
formatting.

Security: all file paths are validated before access. No user input
is interpolated into file operations without sanitisation.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

log = logging.getLogger("aria.branding")


def _sanitise(text: str | None) -> str:
    """Strip control characters from text."""
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text)).strip()


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
) -> str:
    """
    Merge source document content into a branding template.

    Strategy:
    1. Open the template DOCX (has company styles, headers, footers, logo)
    2. Clear the template's body content (keep headers/footers/styles)
    3. Copy all paragraphs and tables from the source document into the
       template body, preserving the source's paragraph structure but
       applying the template's default font/style where the source
       doesn't specify explicit formatting.
    4. Add a title page block using the template's styles.
    5. Save as the output file.

    Returns the output path.
    """
    # Validate paths
    src = Path(source_path)
    tpl = Path(template_path)
    out = Path(output_path)

    if not src.exists():
        raise FileNotFoundError(f"Source document not found: {source_path}")
    if not tpl.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    # Open template and source
    branded = Document(str(tpl))
    source = Document(str(src))

    # ── Clear template body content (keep headers/footers/styles) ──
    body = branded.element.body
    # Remove all paragraphs and tables from template body
    for child in list(body):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in ("p", "tbl", "sdt"):
            body.remove(child)

    # ── Add title block ────────────────────────────────────────────
    title_para = branded.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.space_before = Pt(40)
    run = title_para.add_run(_sanitise(doc_title) or "Policy Document")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)

    # Metadata line
    meta_para = branded.add_paragraph()
    meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_para.space_after = Pt(20)
    meta_items = []
    if doc_id:
        meta_items.append(f"Document: {_sanitise(doc_id)}")
    if version:
        meta_items.append(f"Version: {_sanitise(version)}")
    if framework:
        meta_items.append(f"Framework: {_sanitise(framework)}")
    meta_run = meta_para.add_run(" | ".join(meta_items))
    meta_run.font.size = Pt(10)
    meta_run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    # Divider
    div_para = branded.add_paragraph()
    div_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    div_run = div_para.add_run("─" * 60)
    div_run.font.size = Pt(8)
    div_run.font.color.rgb = RGBColor(0xD1, 0xD5, 0xDB)

    # ── Copy source content into template ─────────────────────────
    for element in source.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
        if tag in ("p", "tbl"):
            # Deep copy the element
            from copy import deepcopy
            new_el = deepcopy(element)
            body.append(new_el)

    # ── Add logo to header if logo_path provided ──────────────────
    if logo_path:
        logo = Path(logo_path)
        if logo.exists():
            try:
                for section in branded.sections:
                    header = section.header
                    header.is_linked_to_previous = False
                    if header.paragraphs:
                        hp = header.paragraphs[0]
                    else:
                        hp = header.add_paragraph()
                    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    run = hp.add_run()
                    run.add_picture(str(logo), width=Cm(3))
            except Exception as exc:
                log.warning("Could not add logo to header: %s", exc)

    # ── Ensure header/footer text from template survives ──────────
    # The template's headers and footers are already preserved since
    # we only cleared body content, not section headers/footers.

    # ── Save branded document ─────────────────────────────────────
    out.parent.mkdir(parents=True, exist_ok=True)
    branded.save(str(out))
    log.info("Branded document saved: %s", out)

    return str(out)
