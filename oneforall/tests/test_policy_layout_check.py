"""Layout check for composed policy DOCX candidates (plans/2026-11-vault-current-proof-policy-layout.md, item 2).

Each case builds a small source document, composes it as the intake screen would, and checks what the layout check
reports. A loss or check finding blocks the candidate until the author records a reason.
"""
import base64
import io

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image

from modules.aria import policy_composition as composition
from modules.aria import policy_intake as intake
from modules.aria import policy_layout_check as layout_check

META = {"title": "Security Policy", "version": "1.0", "effective_date": ""}


def _render(tmp_path, doc, selection):
    source, target = tmp_path / "source.docx", tmp_path / "candidate.docx"
    doc.save(source)
    return composition._render(source, target, selection, META)


def _keys(manifest, severity=None):
    return {f["key"] for f in manifest["layout_check"]["findings"] if severity is None or f["severity"] == severity}


def _blocking(manifest):
    return {f["key"] for f in layout_check.blocking(manifest["layout_check"]["findings"])}


def _bookmark(paragraph, name):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), "7")
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), "7")
    paragraph._p.append(start)
    paragraph._p.append(end)


def _field(paragraph, instruction):
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), instruction)
    paragraph._p.append(field)


def _landscape_annex_document():
    """Cover, a landscape annex closed by its own section break, then a portrait body."""
    doc = Document()
    doc.add_paragraph("Old cover")
    doc.add_paragraph("Landscape risk matrix annex")
    first = doc.sections[0]
    first.orientation = WD_ORIENT.LANDSCAPE
    first.page_width, first.page_height = first.page_height, first.page_width
    second = doc.add_section(WD_SECTION.NEW_PAGE)
    second.orientation = WD_ORIENT.PORTRAIT
    second.page_width, second.page_height = second.page_height, second.page_width
    doc.add_paragraph("Portrait policy body")
    return doc


def test_a_clean_cover_replacement_keeps_everything_and_blocks_nothing(tmp_path):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    doc = Document()
    doc.add_paragraph("Old cover")
    doc.add_paragraph("Purpose: protect information.")
    picture = tmp_path / "diagram.png"
    Image.new("RGB", (30, 30), "#47627b").save(picture)
    doc.add_picture(str(picture))
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "Owner"
    linked = doc.add_paragraph()
    rid = linked.part.relate_to("https://example.invalid/record", RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    linked._p.append(link)
    logo = base64.b64encode(picture.read_bytes()).decode("ascii")
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1, "cover_logo_base64": logo})
    assert _blocking(manifest) == set()
    assert "choice" in _keys(manifest, "info")


def test_excluding_the_block_that_carries_a_section_break_loses_the_landscape_pages(tmp_path):
    doc = _landscape_annex_document()
    outline_blocks = list(doc.iter_inner_content())
    breaker = next(i for i, b in enumerate(outline_blocks) if b._element.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None)
    kept = _render(tmp_path, _landscape_annex_document(), {"mode": "replace_cover", "boundary": 1})
    assert "page_layout" not in _keys(kept)
    lost = _render(tmp_path, _landscape_annex_document(),
                   {"mode": "replace_cover", "boundary": 1, "exclude_blocks": [breaker]})
    finding = next(f for f in lost["layout_check"]["findings"] if f["key"] == "page_layout")
    assert finding["severity"] == "loss" and "landscape" in finding["detail"]


def test_a_cross_reference_to_removed_cover_text_is_a_loss(tmp_path):
    doc = Document()
    cover = doc.add_paragraph("Scope statement on the old cover")
    _bookmark(cover, "Scope")
    body = doc.add_paragraph("See the scope statement on page ")
    _field(body, " PAGEREF Scope \\h ")
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    assert "cross_references" in _blocking(manifest)


def test_a_contents_table_must_be_updated_in_word(tmp_path):
    doc = Document()
    doc.add_paragraph("Old cover")
    toc = doc.add_paragraph()
    _field(toc, ' TOC \\o "1-3" \\h ')
    doc.add_paragraph("1. Purpose")
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    finding = next(f for f in manifest["layout_check"]["findings"] if f["key"] == "contents")
    assert finding["severity"] == "check"


def test_a_footnote_reference_without_its_text_is_a_loss(tmp_path):
    doc = Document()
    doc.add_paragraph("Old cover")
    body = doc.add_paragraph("Retention follows the statute")
    run = body.add_run()
    ref = OxmlElement("w:footnoteReference")
    ref.set(qn("w:id"), "1")
    run._r.append(ref)
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    assert "footnotes" in _blocking(manifest)


def test_a_first_page_header_lands_on_the_new_cover(tmp_path):
    doc = Document()
    doc.add_paragraph("Old cover")
    doc.add_paragraph("Body")
    section = doc.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_header.paragraphs[0].text = "Subsidiary confidential cover"
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    assert "first_page_header" in _blocking(manifest)
    cleared = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1, "clear_headers": True})
    assert "first_page_header" not in _keys(cleared) and "headers" in _keys(cleared, "info")


def test_tracked_changes_left_in_the_text_need_a_decision(tmp_path):
    doc = Document()
    doc.add_paragraph("Old cover")
    body = doc.add_paragraph()
    inserted = OxmlElement("w:ins")
    inserted.set(qn("w:id"), "3")
    inserted.set(qn("w:author"), "Reviewer")
    body._p.append(inserted)
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    assert "revisions" in _blocking(manifest)


def test_findings_carry_no_document_text(tmp_path):
    """The findings are stored in the manifest and shown to approvers; they describe, they do not quote."""
    doc = Document()
    cover = doc.add_paragraph("Secret merger code name on the cover")
    _bookmark(cover, "Merger")
    body = doc.add_paragraph("Refer to ")
    _field(body, " REF Merger \\h ")
    odd = doc.add_paragraph()
    _field(odd, "Board-only-acquisition-target-name DATE")
    manifest = _render(tmp_path, doc, {"mode": "replace_cover", "boundary": 1})
    stored = str(manifest["layout_check"])
    assert "Secret merger" not in stored and "acquisition" not in stored.lower()


@pytest.mark.parametrize("value, ok", [(None, False), ("", False), ("too short", False), (12345, False),
                                       ("x" * 501, False), ("Contents will be updated in Word", True)])
def test_reason_validation(value, ok):
    assert (layout_check.clean_reason(value) is not None) is ok


def test_a_blocking_finding_needs_a_reason_and_records_it(test_db, monkeypatch, tmp_path):
    from tests.test_aria_policy_intake import _actor, _setup
    from modules.aria import policy_storage as storage
    _setup(test_db, monkeypatch, tmp_path)
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", tmp_path / "aria")
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", tmp_path / "aria" / "policy_workflow")
    monkeypatch.setattr(composition, "policy_authoring_enabled_for", lambda org: org == 10)
    doc = Document()
    doc.add_paragraph("Old cover")
    toc = doc.add_paragraph()
    _field(toc, ' TOC \\o "1-3" ')
    doc.add_paragraph("Purpose: A.5.1 protects company information.")
    original = io.BytesIO()
    doc.save(original)
    author = _actor(test_db, 101)
    staged = intake.stage_import(test_db, author, original.getvalue(), "policy.docx")
    intake.register_import(test_db, author, staged["id"], {"title": "Security Policy", "version": "1.0",
                                                           "doc_type": "Policy"}, [])
    selection = {"mode": "replace_cover", "boundary": 1}
    compositions = storage._org_root(10) / "compositions"
    with pytest.raises(intake.IntakeError) as refused:
        composition.create_candidate(test_db, author, staged["id"], selection)
    assert refused.value.status == 409
    assert {f["key"] for f in refused.value.extra["layout_check"]["findings"]} >= {"contents"}
    assert not list(compositions.glob("*.docx")) if compositions.exists() else True
    assert test_db.execute("SELECT COUNT(*) FROM aria_policy_drafts WHERE content_kind='uploaded_docx'").fetchone()[0] == 0

    with pytest.raises(intake.IntakeError):
        composition.create_candidate(test_db, author, staged["id"], {**selection, "layout_acknowledgement": "short"})

    created = composition.create_candidate(test_db, author, staged["id"],
                                           {**selection, "layout_acknowledgement": "  Contents updated in Word before approval "})
    ack = created["manifest"]["layout_check"]["acknowledgement"]
    assert ack["by"] == 101 and ack["reason"] == "Contents updated in Word before approval"
    detail = intake.detail(test_db, author, staged["id"])
    assert detail["composition_draft"]["layout_check"]["acknowledgement"]["reason"].startswith("Contents updated")
