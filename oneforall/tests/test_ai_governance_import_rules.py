"""
The pure rules of the external form import (plans/2026-10-governance-rework/01 section 4).

Written by hand against files built here, not against a customer's export: the real export shapes are still to be
inspected, and this is what keeps every assumption explicit. An untrusted file is only read as text, nothing is guessed, an
answer that is not understood is reported and left open, and the same response always fingerprints the same.
"""
import io
import zipfile

import pytest

from modules.ai_governance import import_rules as ir
from modules.ai_governance import rules


def csv_bytes(*lines, encoding="utf-8"):
    return "\r\n".join(lines).encode(encoding)


GUIDE_HEADERS = [g["question"] for g in ir.FIELD_GUIDE if g["target"] != "response_id"]


# ── Reading a file ──────────────────────────────────────────────────────────

def test_a_csv_with_a_byte_order_mark_and_quoted_commas_is_read():
    data = csv_bytes("﻿Name,Purpose", 'Ticket helper,"Summarize tickets, quickly"')
    table = ir.read_table(data, "responses.csv")
    assert table["kind"] == "csv" and table["headers"] == ["Name", "Purpose"]
    assert table["rows"] == [{"row_number": 2, "cells": ["Ticket helper", "Summarize tickets, quickly"]}]


def test_a_semicolon_or_tab_delimited_export_is_read_as_well():
    assert ir.read_table(csv_bytes("a;b", "1;2"), "x.csv")["rows"][0]["cells"] == ["1", "2"]
    assert ir.read_table(csv_bytes("a\tb", "1\t2"), "x.csv")["rows"][0]["cells"] == ["1", "2"]


def test_utf16_exports_from_a_spreadsheet_are_read_and_other_encodings_are_refused_with_a_way_out():
    assert ir.read_table("a,b\r\n1,2".encode("utf-16"), "x.csv")["headers"] == ["a", "b"]
    with pytest.raises(ir.ImportRuleError, match="UTF-8"):
        ir.read_table("a,b\r\ncaf\xe9,2".encode("cp1252"), "x.csv")


def test_blank_rows_are_skipped_and_the_row_numbers_still_name_the_line_of_the_export():
    table = ir.read_table(csv_bytes("a,b", "1,2", ",", "3,4"), "x.csv")
    assert [r["row_number"] for r in table["rows"]] == [2, 4]


def test_headers_are_trimmed_numbered_when_repeated_and_never_empty():
    table = ir.read_table(csv_bytes(" Name ,Name,,Purpose", "a,b,c,d"), "x.csv")
    assert table["headers"] == ["Name", "Name (2)", "(column 3)", "Purpose"]


def test_control_characters_are_removed_from_cells():
    table = ir.read_table(csv_bytes("a", "x\x00y\x07z"), "x.csv")
    assert table["rows"][0]["cells"] == ["xyz"]


def test_a_workbook_is_read_from_its_first_sheet_with_dates_and_numbers_as_text():
    from datetime import datetime
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(["Name", "Start", "Count", "Flag"])
    sheet.append(["Ticket helper", datetime(2026, 12, 1), 3.0, True])
    buffer = io.BytesIO()
    book.save(buffer)
    table = ir.read_table(buffer.getvalue(), "export.xlsx")
    assert table["kind"] == "xlsx" and table["headers"] == ["Name", "Start", "Count", "Flag"]
    assert table["rows"][0]["cells"] == ["Ticket helper", "2026-12-01", "3", "Yes"]


def test_a_file_that_is_not_a_workbook_but_says_it_is_is_refused():
    with pytest.raises(ir.ImportRuleError, match="not a valid Excel workbook"):
        ir.read_table(b"hello", "export.xlsx")
    with pytest.raises(ir.ImportRuleError, match="not a valid Excel workbook"):
        ir.read_table(b"PK\x03\x04 not really a zip", "export.xlsx")


def test_a_workbook_that_unpacks_to_a_huge_size_is_refused_before_it_is_opened():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (ir.MAX_UNZIPPED_BYTES + 1))
    assert len(buffer.getvalue()) < ir.MAX_FILE_BYTES
    with pytest.raises(ir.ImportRuleError, match="too large"):
        ir.read_table(buffer.getvalue(), "bomb.xlsx")


def test_size_row_and_column_limits_are_enforced():
    with pytest.raises(ir.ImportRuleError, match="empty"):
        ir.read_table(b"", "x.csv")
    with pytest.raises(ir.ImportRuleError, match="larger than"):
        ir.read_table(b"a\n" + b"x" * (ir.MAX_FILE_BYTES + 1), "x.csv")
    many_rows = "a\n" + "\n".join(["1"] * (ir.MAX_ROWS + 1)) + "\n"
    with pytest.raises(ir.ImportRuleError, match=f"more than {ir.MAX_ROWS}"):
        ir.read_table(many_rows.encode(), "x.csv")
    wide = ",".join(f"c{i}" for i in range(ir.MAX_COLUMNS + 1))
    with pytest.raises(ir.ImportRuleError, match="more than"):
        ir.read_table(wide.encode() + b"\n1", "x.csv")
    with pytest.raises(ir.ImportRuleError, match="no column headers"):
        ir.read_table(b",,\n,,\n", "x.csv")
    with pytest.raises(ir.ImportRuleError, match=r"\.csv or \.xlsx"):
        ir.read_table(b"a,b", "x.pdf")


def test_a_cell_over_the_limit_is_marked_not_cut():
    table = ir.read_table(csv_bytes("a,b", "x," + "y" * (ir.MAX_CELL + 1)), "x.csv")
    assert table["rows"][0]["cells"] == ["x", None]


# ── The published guide ─────────────────────────────────────────────────────

def test_the_template_has_the_guides_questions_and_one_example_row_that_maps_and_imports():
    table = ir.read_table(ir.template_csv().encode("utf-8"), "template.csv")
    assert table["headers"] == GUIDE_HEADERS
    mapping = ir.suggest_mapping(table["headers"])
    assert ir.validate_mapping(mapping, table["headers"]) == []
    row = ir.process_row(table["headers"], table["rows"][0], mapping)
    assert row["importable"] is True and row["issues"] == []
    assert row["answers"]["deployment"] == "vendor_service" and row["answers"]["data_categories"] == ["internal", "personal"]
    assert row["answers"]["affects_decisions"] is False and row["owner_hint"] == "owner@example.com"
    assert row["requester"]["email"] == "requester@example.com"
    assert row["missing"] == [], "the example answers every question the form asks for"


def test_every_required_question_is_in_the_published_guide_in_the_order_it_is_asked():
    assert ir.REQUIRED_TARGETS[:3] == ("name", "purpose", "requester_name")
    assert set(ir.REQUIRED_TARGETS) <= set(ir.TARGETS)
    assert ir.GUIDE_VERSION == "forms-v1"


# ── Mapping ─────────────────────────────────────────────────────────────────

def test_a_microsoft_forms_name_column_is_the_requester_and_never_the_name_of_the_use():
    headers = ["Id", "Start time", "Email", "Name", "What is the name of the AI tool or use?"]
    mapping = ir.suggest_mapping(headers)
    assert mapping == {"Id": "response_id", "Start time": "", "Email": "requester_email", "Name": "requester_name",
                       "What is the name of the AI tool or use?": "name"}


def test_a_target_is_offered_once_and_the_rest_is_left_for_a_person():
    mapping = ir.suggest_mapping(["Purpose", "purpose", "Something else"])
    assert mapping == {"Purpose": "purpose", "purpose": "", "Something else": ""}


def test_a_mapping_without_the_use_name_or_with_a_repeat_or_unknown_target_is_refused():
    headers = ["A", "B"]
    assert any("name of the AI use" in p for p in ir.validate_mapping({"A": "purpose", "B": ""}, headers))
    assert any("Two columns" in p for p in ir.validate_mapping({"A": "name", "B": "name"}, headers))
    assert any("not a question" in p for p in ir.validate_mapping({"A": "name", "B": "owner_user_id"}, headers))
    assert any("columns the file does not have" in p for p in ir.validate_mapping({"A": "name", "Z": "purpose"}, headers))
    assert ir.validate_mapping({"A": "name", "B": ""}, headers) == []
    assert ir.validate_mapping([], headers)


# ── One answer at a time ────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Yes", (True, True)), (" no ", (False, True)), ("Y", (True, True)), ("TRUE", (True, True)), ("not sure", (None, True)),
    ("", (None, True)), ("Don't know", (None, True)), ("perhaps", (None, False)),
])
def test_yes_no_answers(text, expected):
    assert ir.norm_yes_no(text) == expected


def test_a_choice_matches_its_key_or_its_label_in_any_case():
    assert ir.norm_choice("vendor_service", rules.DEPLOYMENT) == ("vendor_service", True)
    assert ir.norm_choice("A vendor's AI service that we call", rules.DEPLOYMENT) == ("vendor_service", True)
    assert ir.norm_choice("a VENDORS ai service that we call", rules.DEPLOYMENT) == ("vendor_service", True)
    assert ir.norm_choice("Magic", rules.DEPLOYMENT) == (None, False)
    assert ir.norm_choice("  ", rules.DEPLOYMENT) == (None, True)


def test_checkbox_answers_split_on_a_semicolon_first_then_on_comma_space():
    assert ir.split_multi("Personal data; Financial data") == ["Personal data", "Financial data"]
    assert ir.split_multi("Personal data, Financial data") == ["Personal data", "Financial data"]
    keys, unknown = ir.norm_multi("Personal data, Customer secrets, personal data", rules.DATA_CATEGORIES)
    assert keys == ["personal"] and unknown == ["Customer secrets"]


@pytest.mark.parametrize("text, order, expected", [
    ("2026-12-01", "iso", ("2026-12-01", True)),
    ("2026-12-01 10:30:00", "iso", ("2026-12-01", True)),
    ("03/04/2026", "dmy", ("2026-04-03", True)),
    ("03/04/2026", "mdy", ("2026-03-04", True)),
    ("03/04/2026", "iso", (None, False)),
    ("1 December 2026", "iso", ("2026-12-01", True)),
    ("31/02/2026", "dmy", (None, False)),
    ("next spring", "iso", (None, False)),
    ("", "iso", (None, True)),
])
def test_dates_are_read_only_in_the_declared_order(text, order, expected):
    assert ir.norm_date(text, order) == expected


# ── One response ────────────────────────────────────────────────────────────

HEADERS = ["Use", "Why", "How", "Data", "Affects", "Owner", "Who", "Extra column"]
MAPPING = {"Use": "name", "Why": "purpose", "How": "deployment", "Data": "data_categories", "Affects": "affects_decisions",
           "Owner": "owner", "Who": "requester_name", "Extra column": ""}


def row(*cells, number=2):
    return {"row_number": number, "cells": list(cells)}


def test_a_complete_response_is_importable_and_names_what_a_submission_still_lacks():
    got = ir.process_row(HEADERS, row("Helper", "Summarize", "Built in-house", "Internal business information", "No", "jane@x.org",
                                      "Pat", "kept as is"), MAPPING)
    assert got["importable"] is True and got["answers"]["deployment"] == "internal_build"
    assert got["answers"]["data_categories"] == ["internal"] and got["answers"]["affects_decisions"] is False
    assert got["owner_hint"] == "jane@x.org" and got["requester"] == {"name": "Pat"}
    assert got["unmapped"] == {"Extra column": "kept as is"}, "an unmapped column stays visible and is never copied in"
    assert got["missing"] == ["intended_users"], "the form never asked who will use it"


def test_an_unknown_choice_is_reported_and_left_open_never_guessed():
    got = ir.process_row(HEADERS, row("Helper", "Summarize", "Somewhere in the cloud", "Personal data, Secrets", "Perhaps", "", "Pat", ""), MAPPING)
    assert got["importable"] is True, "warnings import the response with that answer left open"
    assert got["answers"]["deployment"] is None and got["answers"]["data_categories"] == ["personal"]
    assert got["answers"]["affects_decisions"] is None
    messages = [i["message"] for i in got["issues"]]
    assert any("Somewhere in the cloud" in m for m in messages) and any("Secrets" in m for m in messages)
    assert any("Perhaps" in m for m in messages) and all(i["level"] == "warning" for i in got["issues"])
    assert "deployment" in got["missing"] and "data_categories" not in got["missing"]


def test_a_response_without_a_name_or_with_a_cut_cell_is_an_error():
    nameless = ir.process_row(HEADERS, row("", "Summarize", "", "", "", "", "", ""), MAPPING)
    assert nameless["importable"] is False and nameless["issues"][0] == {
        "level": "error", "field": "name", "message": "The response has no name for the AI use."}
    long = ir.process_row(HEADERS, row("Helper", None, "", "", "", "", "", ""), MAPPING)
    assert long["importable"] is False and any("longer than" in i["message"] for i in long["issues"])
    too_long_purpose = ir.process_row(HEADERS, row("Helper", "x" * 2500, "", "", "", "", "", ""), MAPPING)
    assert too_long_purpose["importable"] is False
    assert any(i["field"] == "purpose" and i["level"] == "error" for i in too_long_purpose["issues"])


def test_a_requesters_email_that_is_not_an_address_is_a_warning():
    headers, mapping = ["Use", "Mail"], {"Use": "name", "Mail": "requester_email"}
    got = ir.process_row(headers, row("Helper", "not-an-address"), mapping)
    assert got["importable"] is True and any(i["field"] == "requester_email" for i in got["issues"])


def test_extra_questions_are_kept_with_the_requester_and_not_in_the_profile_answers():
    headers = ["Use", "Model", "Docs"]
    mapping = {"Use": "name", "Model": "known_model", "Docs": "supporting_documents"}
    got = ir.process_row(headers, row("Helper", "GPT-x 2026", "https://example.org/doc.pdf"), mapping)
    assert got["requester"]["extra"] == {"known_model": "GPT-x 2026", "supporting_documents": "https://example.org/doc.pdf"}
    assert "known_model" not in got["answers"]


# ── Identity: fingerprint, key, differences ─────────────────────────────────

def test_the_same_response_fingerprints_the_same_and_any_changed_answer_does_not():
    first = ir.process_row(HEADERS, row("Helper", "Summarize", "Built in-house", "", "", "", "Pat", ""), MAPPING)
    again = ir.process_row(HEADERS, row("Helper", "Summarize", "Built in-house", "", "", "", "Pat", "", ), MAPPING)
    corrected = ir.process_row(HEADERS, row("Helper", "Summarize more", "Built in-house", "", "", "", "Pat", ""), MAPPING)
    assert first["fingerprint"] == again["fingerprint"] != corrected["fingerprint"]
    assert len(first["fingerprint"]) == 64


def test_the_row_number_and_an_unmapped_column_do_not_change_the_fingerprint():
    a = ir.process_row(HEADERS, row("Helper", "Summarize", "", "", "", "", "Pat", "one", number=2), MAPPING)
    b = ir.process_row(HEADERS, row("Helper", "Summarize", "", "", "", "", "Pat", "two", number=9), MAPPING)
    assert a["fingerprint"] == b["fingerprint"]


def test_the_correlation_key_prefers_a_response_id_then_the_requester_and_the_use_name():
    by_id = ir.correlation_key(1, "AI intake", "R-17", "a@x.org", "Helper")
    assert by_id == ir.correlation_key(1, " ai INTAKE ", "R-17", "other@x.org", "Other name")
    assert by_id != ir.correlation_key(2, "AI intake", "R-17", "a@x.org", "Helper"), "another organization, another key"
    by_person = ir.correlation_key(1, "AI intake", None, "A@X.org", "  Helper  Two ")
    assert by_person == ir.correlation_key(1, "AI intake", "", "a@x.org", "helper two")
    assert ir.correlation_key(1, "AI intake", None, None, "Helper") is None, "nothing to correlate on: always new"


def test_a_difference_names_each_changed_answer_and_treats_empty_lists_and_blanks_as_the_same():
    old = {"name": "Helper", "purpose": "A", "data_categories": [], "autonomy": None}
    new = {"name": "Helper", "purpose": "B", "data_categories": ["personal"], "autonomy": ""}
    assert ir.diff_answers(old, new) == [
        {"field": "purpose", "label": "purpose", "before": "A", "after": "B"},
        {"field": "data_categories", "label": "kinds of data", "before": None, "after": ["personal"]}]
    assert ir.diff_answers(old, dict(old)) == []
    assert ir.diff_requester({"name": "Pat"}, {"name": "Pat", "email": "p@x.org"}) == [
        {"field": "requester_email", "label": "requester email", "before": None, "after": "p@x.org"}]
