"""
Links and Markdown in the shared report kit (decision D15 of PLAN_record_document_exports_2026-10-22.md).

A table column can name the row key that holds its link. PDF, Word, Excel and the print view each draw it as a link (a clickable
annotation, a hyperlink relationship, a cell hyperlink, an anchor), and draw anything that is not a safe absolute https address as plain
text: a relative path, `javascript:`, a quote that could end an attribute and credentials in the address can never become a link. Text
written in Markdown (an AI draft, the body of a plan) becomes titled blocks, lines and tables, never markup.
"""
import io
import zipfile
from datetime import datetime

import openpyxl
import pytest
from docx import Document
from lxml import etree
from pypdf import PdfReader

from core.report_kit import identity, markdown
from core.report_kit.model import Actor, Col, Meta, Paragraphs, Report, Table
from core.report_kit.render_docx import render_docx
from core.report_kit.render_html import render_html
from core.report_kit.render_pdf import render_pdf
from core.report_kit.render_xlsx import render_xlsx
from tests.test_report_kit import EXPECTED_ORDER

WHEN = datetime(2026, 10, 22, 8, 0)
GOOD = "https://app.example.test/sentinel/?open=dpia:7&tab=risks"


def _report(rows):
    report = Report(Meta(title="Links", module="sentinel", generated_at=WHEN, generated_by=Actor(name="Jane Doe", username="jdoe")))
    return report.add(Table("Connected", [Col("Record", "title", link="url"), Col("Where", "where")], rows))


def _pdf_links(body):
    return [a.get_object().get("/A", {}).get("/URI") for page in PdfReader(io.BytesIO(body)).pages for a in page.get("/Annots") or []]


@pytest.mark.parametrize("url", [GOOD, "https://app.example.test", "https://app.example.test:8443/x", "http://localhost:8000/x",
                                 "http://127.0.0.1/x", "HTTPS://APP.EXAMPLE.TEST/x"])
def test_an_absolute_https_address_is_a_link(url):
    assert identity.safe_link(url) == url


@pytest.mark.parametrize("url", [None, "", "   ", "/sentinel/?open=dpia:7", "//evil.test/x", "relative/path", "javascript:alert(1)", "data:text/html,x",
                                 "ftp://app.example.test/x", "http://app.example.test/x", "https://user:pw@app.example.test/x", "https:///nohost",
                                 'https://app.example.test/x"onmouseover="y', "https://app.example.test/<script>", "https://app.example.test/a b",
                                 "https://app.example.test/é", "https://app.example.test/a\nb", "https://app.example.test:notaport/x",
                                 "https://app.example.test/" + "a" * 2100])
def test_anything_else_is_never_a_link(url):
    assert identity.safe_link(url) == ""


def test_blanks_around_an_address_are_trimmed_and_never_inside_it():
    assert identity.safe_link("  https://app.example.test/x\n") == "https://app.example.test/x"


def test_each_renderer_draws_a_link_for_a_safe_address_and_plain_text_for_anything_else():
    rows = [{"title": "Customer onboarding", "url": GOOD, "where": "Privacy"}, {"title": "Relative path", "url": "/sentinel/", "where": "Privacy"},
            {"title": "Script", "url": "javascript:alert(1)", "where": "Privacy"}, {"title": "No address", "url": None, "where": "Privacy"}]
    report = _report(rows)

    pdf = render_pdf(report)
    assert _pdf_links(pdf) == [GOOD], "one annotation, and the ampersand of the address survives the markup"
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert all(name in text for name in ("Customer onboarding", "Relative path", "Script", "No address")), "the text is drawn for every row"

    docx = render_docx(report)
    package = zipfile.ZipFile(io.BytesIO(docx))
    relations = package.read("word/_rels/document.xml.rels").decode()
    assert relations.count('TargetMode="External"') == 1 and GOOD.replace("&", "&amp;") in relations
    body = etree.fromstring(package.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    anchors = body.findall(".//w:hyperlink", ns)
    assert len(anchors) == 1 and "".join(anchors[0].itertext()) == "Customer onboarding"
    assert anchors[0].find("w:r/w:rPr/w:u", ns) is not None, "underlined, not blue"
    assert Document(io.BytesIO(docx)).tables, "the document still opens"

    sheet = openpyxl.load_workbook(io.BytesIO(render_xlsx(report)))["Connected"]
    assert [(c.value, c.hyperlink.target if c.hyperlink else None) for c in sheet["A"][1:]] == [
        ("Customer onboarding", GOOD), ("Relative path", None), ("Script", None), ("No address", None)]
    assert sheet["A2"].font.underline == "single" and sheet["A3"].font.underline is None
    assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)

    html = render_html(report)
    assert html.count("<a href=") == 1 and f'<a href="{GOOD.replace("&", "&amp;")}" rel="noopener noreferrer">Customer onboarding</a>' in html
    assert "javascript:" not in html and 'href="/sentinel/"' not in html


def test_a_link_cannot_carry_markup_out_of_a_name_or_an_address():
    rows = [{"title": 'A <b>bold</b> & "quoted" name', "url": GOOD, "where": "x"}]
    report = _report(rows)
    assert _pdf_links(render_pdf(report)) == [GOOD]
    html = render_html(report)
    assert '<a href="https://app.example.test/sentinel/?open=dpia:7&amp;tab=risks" rel="noopener noreferrer">A bold &amp; &quot;quoted&quot; name</a>' in html, \
        "tags are stripped from a name and the rest is escaped, in the address too"


def test_the_docx_hyperlink_keeps_the_property_order_word_requires():
    package = zipfile.ZipFile(io.BytesIO(render_docx(_report([{"title": "T", "url": GOOD, "where": "x"}]))))
    root = etree.fromstring(package.read("word/document.xml"))
    for element in root.iter():
        local = etree.QName(element).localname if isinstance(element.tag, str) else ""
        if local in EXPECTED_ORDER:
            seen = [etree.QName(child).localname for child in element]
            indexes = [EXPECTED_ORDER[local].index(s) for s in seen]
            assert indexes == sorted(indexes), f"<{local}> children out of order: {seen}"


# ── Markdown ────────────────────────────────────────────────────────────────

def test_a_heading_opens_a_titled_block_and_lines_stay_lines():
    out = markdown.blocks("# Plan title\n\n## 1. Purpose\nFirst line\nSecond line\n\n- one\n* two\n+ three\n\n1. step one\n2) step two\n\n## 2. Next\nText")
    assert [(b.title, b.paragraphs) for b in out] == [
        ("1. Purpose", ["First line", "Second line", "• one", "• two", "• three", "1. step one", "2. step two"]), ("2. Next", ["Text"])]


def test_text_before_the_first_heading_sits_under_the_given_title_and_a_top_heading_is_the_documents_own():
    assert [(b.title, b.paragraphs) for b in markdown.blocks("Just words", "Draft text")] == [("Draft text", ["Just words"])]
    assert [(b.title, b.paragraphs) for b in markdown.blocks("# Title\nWords", "Draft text")] == [("Draft text", ["Words"])]
    assert [(b.title, b.paragraphs) for b in markdown.blocks("## Only a heading\n")] == [("Only a heading", [])], "a heading with nothing under it keeps its title"
    assert [(b.title, b.paragraphs) for b in markdown.blocks("Words\n# A later top heading\nMore")] == [("Overview", ["Words"]), ("A later top heading", ["More"])]


def test_a_pipe_table_becomes_a_table_and_the_text_after_it_goes_on():
    out = markdown.blocks("## Roles\n| Role | Holder | Duty |\n|---|:---:|---|\n| Commander | Head of Ops | Decides \\| owns |\n| Scribe | Duty officer | Keeps notes |\n\nAfter the table\n")
    assert [type(b).__name__ for b in out] == ["Paragraphs", "Table", "Paragraphs"]
    table = out[1]
    assert table.sheet_name == "Text table 1" and markdown.blocks("| a |\n|---|\n| 1 |\n\nx\n\n| b |\n|---|\n| 2 |")[-1].sheet_name == "Text table 2"
    assert [c.header for c in table.columns] == ["Role", "Holder", "Duty"] and table.columns[-1].weight > table.columns[0].weight
    assert table.rows == [{"c0": "Commander", "c1": "Head of Ops", "c2": "Decides | owns"}, {"c0": "Scribe", "c1": "Duty officer", "c2": "Keeps notes"}]
    assert out[0].title == "Roles" and out[2].title == "" and out[2].paragraphs == ["After the table"]
    assert not any(isinstance(b, Table) for b in markdown.blocks("| only | a header |\n|---|---|")), "a header with no row is not a table"


def test_markup_is_reduced_to_its_words():
    out = markdown.blocks("## **Bold** heading\nA [link text](https://x.test/y) and **bold** and *italic* and `code` and ![alt](pic.png) here\n> a quote\n---\n```\nfenced\n```")
    assert out[0].title == "Bold heading"
    assert out[0].paragraphs == ["A link text and bold and italic and code and  here", "a quote", "fenced"]
    assert markdown.plain("a * b * c and 2*3*4") == "a * b * c and 2*3*4", "a star between spaces or digits is not emphasis"
    assert markdown.blocks("") == [] and markdown.blocks(None) == [] and markdown.blocks("  \n \n") == [], "no text, no block"


def test_a_markdown_block_is_drawn_by_the_pdf_without_markup():
    report = Report(Meta(title="Draft", module="sentinel", generated_at=WHEN, generated_by=Actor(name="Jane Doe", username="jdoe")))
    report.add(*markdown.blocks("## 1. Risks\n- **Access** to <script>x</script> data\n| a | b |\n|---|---|\n| 1 | 2 |"))
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(render_pdf(report))).pages)
    assert "1. Risks" in text and "Access to" in text and "**" not in text and "<script>" not in text
    assert isinstance(report.blocks[0], Paragraphs) and isinstance(report.blocks[1], Table)
