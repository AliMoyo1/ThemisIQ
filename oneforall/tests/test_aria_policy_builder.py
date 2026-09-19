"""
PLAN-35 T03: DOCX builder and branding tests.

Tests semantic structure (headings, lists, tables, emphasis, Unicode,
control characters), not identical DOCX ZIP bytes -- package metadata and
timestamps can legitimately differ between runs, per the plan's own
instruction. Also proves the specific bug apply_template's generated_body
mode exists to fix: a source document whose first heading doesn't match
the legacy heuristic's narrow keyword list was silently dropped entirely.
"""
from docx import Document as DocxDocument

from modules.aria.branding_engine import build_policy_docx, apply_template


def _para_texts(doc):
    return [p.text for p in doc.paragraphs]


def _heading_paras(doc, level_style):
    return [p for p in doc.paragraphs if p.style.name == level_style]


# ─────────────────────────────────────────────────────────────────────────
# Preamble behavior
# ─────────────────────────────────────────────────────────────────────────

def test_include_preamble_true_reproduces_export_word_behavior():
    doc = build_policy_docx(
        "# Access Control Policy\n\nBody text.",
        org_name="Econet", control_label="A.5.15 - Access Control",
        include_preamble=True,
    )
    texts = _para_texts(doc)
    assert texts[0] == "Econet"
    assert doc.paragraphs[0].style.name == "Title"
    assert texts[1] == "A.5.15 - Access Control"
    assert doc.paragraphs[1].style.name == "Heading 1"


def test_include_preamble_false_starts_directly_with_content():
    doc = build_policy_docx(
        "# Access Control Policy\n\nBody text.",
        org_name="Econet", control_label="A.5.15 - Access Control",
        include_preamble=False,
    )
    texts = _para_texts(doc)
    assert "Econet" not in texts
    assert "A.5.15 - Access Control" not in texts
    assert texts[0] == "Access Control Policy"
    assert doc.paragraphs[0].style.name == "Heading 1"


# ─────────────────────────────────────────────────────────────────────────
# Semantic structure: headings, lists, tables, emphasis
# ─────────────────────────────────────────────────────────────────────────

def test_heading_levels():
    doc = build_policy_docx(
        "# H1 Text\n## H2 Text\n### H3 Text", include_preamble=False,
    )
    assert [(p.text, p.style.name) for p in doc.paragraphs] == [
        ("H1 Text", "Heading 1"),
        ("H2 Text", "Heading 2"),
        ("H3 Text", "Heading 3"),
    ]


def test_bullet_and_numbered_lists():
    doc = build_policy_docx(
        "- First bullet\n* Second bullet\n1. First number\n2) Second number",
        include_preamble=False,
    )
    styles_and_text = [(p.style.name, p.text) for p in doc.paragraphs]
    assert styles_and_text == [
        ("List Bullet", "First bullet"),
        ("List Bullet", "Second bullet"),
        ("List Number", "First number"),
        ("List Number", "Second number"),
    ]


def test_table_with_header_row_bolded():
    md = (
        "| Control | Owner |\n"
        "|---|---|\n"
        "| A.5.1 | CISO |\n"
        "| A.5.2 | DPO |"
    )
    doc = build_policy_docx(md, include_preamble=False)
    assert len(doc.tables) == 1
    tbl = doc.tables[0]
    assert len(tbl.rows) == 3  # header + 2 data rows (the --- separator is not a row)
    assert tbl.cell(0, 0).text == "Control"
    assert tbl.cell(0, 1).text == "Owner"
    assert tbl.cell(1, 0).text == "A.5.1"
    assert tbl.cell(2, 1).text == "DPO"
    header_runs = tbl.cell(0, 0).paragraphs[0].runs
    assert all(r.bold for r in header_runs)
    data_runs = tbl.cell(1, 0).paragraphs[0].runs
    assert not any(r.bold for r in data_runs)


def test_emphasis_bold_italic_bold_italic():
    doc = build_policy_docx(
        "Plain **bold** and *italic* and ***both***.", include_preamble=False,
    )
    p = doc.paragraphs[0]
    runs_by_text = {r.text: r for r in p.runs}
    assert runs_by_text["bold"].bold is True and not runs_by_text["bold"].italic
    assert runs_by_text["italic"].italic is True and not runs_by_text["italic"].bold
    assert runs_by_text["both"].bold is True and runs_by_text["both"].italic is True


# ─────────────────────────────────────────────────────────────────────────
# Unicode and control characters
# ─────────────────────────────────────────────────────────────────────────

def test_unicode_content_preserved():
    doc = build_policy_docx(
        "# Politique de contrôle d'accès\n\n"
        "日本語テスト café – emoji \U0001F512",
        include_preamble=False,
    )
    texts = _para_texts(doc)
    assert texts[0] == "Politique de contrôle d'accès"
    # texts[1] is the blank line the "\n\n" produces; content is texts[2].
    assert "日本語テスト" in texts[2]
    assert "café" in texts[2]
    assert "\U0001F512" in texts[2]


def test_control_characters_are_stripped_not_left_to_crash_save(tmp_path):
    content = "# Title\x00\n\nBody\x01 text\x1f with\x0bcontrol chars."
    doc = build_policy_docx(content, include_preamble=False)
    for text in _para_texts(doc):
        for ch in text:
            assert ord(ch) not in range(0, 9) and ord(ch) not in (11, 12) and not (14 <= ord(ch) <= 31), \
                f"control character {ord(ch)!r} leaked into saved text"
    # Must actually be a valid, savable OOXML package.
    out = tmp_path / "control_chars.docx"
    doc.save(str(out))
    assert out.exists() and out.stat().st_size > 0


def test_tab_and_newline_are_not_stripped():
    """_sanitise() must only remove XML-invalid control characters, not
    the legitimate whitespace this parser relies on to split lines."""
    doc = build_policy_docx("Line one\nLine two", include_preamble=False)
    assert _para_texts(doc) == ["Line one", "Line two"]


# ─────────────────────────────────────────────────────────────────────────
# apply_template's generated_body mode: the actual bug this task fixes
# ─────────────────────────────────────────────────────────────────────────

def _make_minimal_template(path):
    doc = DocxDocument()
    doc.add_paragraph("TEMPLATE COVER PAGE PLACEHOLDER")
    doc.save(str(path))


def test_heuristic_mode_drops_content_with_an_unrecognized_first_heading(tmp_path):
    """Reproduces the exact bug: a generated document whose first heading
    doesn't match _is_content_start's keyword list is silently dropped
    entirely under the legacy (generated_body=False) heuristic."""
    template_path = tmp_path / "template.docx"
    _make_minimal_template(template_path)

    source_path = tmp_path / "source.docx"
    source_doc = build_policy_docx(
        "# Data Retention Policy\n\nThis is the real policy body that must survive.",
        include_preamble=False,
    )
    source_doc.save(str(source_path))

    output_path = tmp_path / "branded_heuristic.docx"
    apply_template(
        source_path=str(source_path), template_path=str(template_path),
        output_path=str(output_path), doc_title="Data Retention Policy",
        generated_body=False,
    )
    result = DocxDocument(str(output_path))
    all_text = " ".join(p.text for p in result.paragraphs)
    assert "real policy body that must survive" not in all_text, (
        "if this now passes, the heuristic's keyword list changed and this "
        "regression test needs updating, not deleting"
    )


def test_generated_body_mode_preserves_the_same_content(tmp_path):
    template_path = tmp_path / "template.docx"
    _make_minimal_template(template_path)

    source_path = tmp_path / "source.docx"
    source_doc = build_policy_docx(
        "# Data Retention Policy\n\nThis is the real policy body that must survive.\n\n"
        "## Second Section\n\nMore content here.",
        include_preamble=False,
    )
    source_doc.save(str(source_path))

    output_path = tmp_path / "branded_generated.docx"
    apply_template(
        source_path=str(source_path), template_path=str(template_path),
        output_path=str(output_path), doc_title="Data Retention Policy",
        generated_body=True,
    )
    result = DocxDocument(str(output_path))
    all_text = " ".join(p.text for p in result.paragraphs)
    assert "real policy body that must survive" in all_text
    assert "Second Section" in all_text
    assert "More content here" in all_text
    # The template's own front matter is still present, not replaced.
    assert "TEMPLATE COVER PAGE PLACEHOLDER" in all_text


def test_generated_body_mode_preserves_tables_too(tmp_path):
    template_path = tmp_path / "template.docx"
    _make_minimal_template(template_path)

    source_path = tmp_path / "source.docx"
    source_doc = build_policy_docx(
        "# Roles\n\n| Role | Owner |\n|---|---|\n| Approver | CISO |",
        include_preamble=False,
    )
    source_doc.save(str(source_path))

    output_path = tmp_path / "branded_table.docx"
    apply_template(
        source_path=str(source_path), template_path=str(template_path),
        output_path=str(output_path), doc_title="Roles",
        generated_body=True,
    )
    result = DocxDocument(str(output_path))
    assert len(result.tables) == 1
    assert result.tables[0].cell(1, 1).text == "CISO"


def test_legacy_heuristic_mode_still_copies_a_properly_prefaced_upload(tmp_path):
    """Regression guard: generated_body=False (the existing, unchanged
    default) must still behave exactly as before for a legacy-shaped
    upload whose first real heading DOES match the heuristic."""
    template_path = tmp_path / "template.docx"
    _make_minimal_template(template_path)

    source_path = tmp_path / "source.docx"
    source_doc = DocxDocument()
    source_doc.add_heading("Uploaded Document Cover Title", level=0)
    h = source_doc.add_heading("1. Purpose", level=1)
    source_doc.add_paragraph("This paragraph must survive.")
    source_doc.save(str(source_path))

    output_path = tmp_path / "branded_legacy.docx"
    apply_template(
        source_path=str(source_path), template_path=str(template_path),
        output_path=str(output_path), doc_title="Uploaded Document",
        generated_body=False,
    )
    result = DocxDocument(str(output_path))
    all_text = " ".join(p.text for p in result.paragraphs)
    assert "This paragraph must survive." in all_text
    assert "Uploaded Document Cover Title" not in all_text  # cover still stripped
