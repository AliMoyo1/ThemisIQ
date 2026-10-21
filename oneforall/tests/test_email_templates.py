"""
A message is a template and structured fields, never HTML a caller wrote, and it carries a reference, not a narrative
(plans/2026-10-governance-rework/06 section 5).
"""
import pytest

from core import email_templates as t

ORIGIN = "https://app.themisiq.net"


def test_every_template_renders_a_subject_without_a_field_and_the_same_information_in_text_and_html():
    samples = {
        "action.assigned": ({"kind": "ai_use_review", "reference": "AI-204", "due": "2026-10-18"}, "/my-work"),
        "decision.ready": ({"reference": "AI-204", "due": "2026-10-18"}, "/ai-governance/systems/9"),
        "evidence.renew": ({"reference": "CT-12", "due": "2026-10-20"}, "/evidence/?open=item:4"),
        "audit.finding": ({"reference": "AU-27", "due": "2026-10-23"}, "/grid/?open=nc:5"),
        "audit.deadline": ({"reference": "AU-27", "due": "2026-10-23"}, "/grid/?open=nc:5"),
        "audit.escalation": ({"reference": "AU-27", "due": "2026-10-23"}, "/grid/?open=nc:5"),
        "control.reminder": ({"reference": "AU-27"}, "/grid/?open=control:8"),
        "privacy.deadline": ({"reference": "BR-104", "due": "2026-10-14 16:00", "hours": 6}, "/sentinel/?open=breach:7"),
        "privacy.dsr": ({"reference": "DSR-12", "due": "2026-10-20"}, "/sentinel/?open=dsr:3"),
        "bcm.exercise": ({"reference": "EX-9", "due": "2026-10-20"}, "/bcm/?open=exercise:9"),
        "bcm.incident": ({"reference": "INC-14", "minutes": 15}, "/bcm/?open=incident:14"),
        "bcm.escalation": ({"reference": "INC-14", "minutes": 15}, "/bcm/?open=incident:14"),
        "tasks.assigned": ({"count": 4}, "/tasks"),
        "summary.weekly": ({"audits": 3, "overdue": 1}, "/grid/"),
        "summary.mywork": ({"count": 4, "overdue": 1}, "/my-work"),
        "delivery.failure": ({"count": 3}, "/admin/email"),
    }
    assert set(samples) == set(t.TEMPLATES)
    for key, (fields, route) in samples.items():
        got = t.render(key, fields, route, ORIGIN)
        assert got["subject"].startswith("ThemisIQ: ") and "{" not in got["subject"]
        for value in fields.values():
            assert str(value) not in got["subject"], "a subject carries no field"
        assert got["link"] == ORIGIN + route
        assert got["link"] in got["text"] and got["link"] in got["html"]
        assert "href=\"" + got["link"] + "\"" in got["html"], "a visible and a clickable link"
        for word in ("operational message",):
            assert word in got["text"] and word in got["html"]


def test_the_example_messages_of_the_plan_read_as_the_plan_says():
    got = t.render("audit.finding", {"reference": "AU-27", "due": "2026-10-23"}, "/grid/?open=nc:5", ORIGIN)
    assert got["subject"] == "ThemisIQ: a corrective action is assigned to you"
    assert "A corrective action for audit AU-27 is assigned to you. Due: 23 Oct 2026." in got["text"]
    got = t.render("evidence.renew", {"reference": "CT-12", "due": "2026-10-20"}, "/evidence/?open=item:4", ORIGIN)
    assert "Evidence CT-12 needs review by 20 Oct 2026." in got["text"]


def test_a_field_cannot_carry_markup_a_title_or_a_free_narrative():
    for bad in ("<script>alert(1)</script>", "A very long narrative of the breach and who it affected, in full sentences",
                "line one\nline two with Bcc: x", "x" * 90, "='cmd'"):
        with pytest.raises(t.TemplateError):
            t.render("evidence.renew", {"reference": bad, "due": "2026-10-20"}, "/evidence/", ORIGIN)


def test_an_unknown_kind_a_missing_field_and_a_bad_date_are_refused():
    with pytest.raises(t.TemplateError):
        t.render("action.assigned", {"kind": "free text kind", "reference": "T-1"}, "/my-work", ORIGIN)
    with pytest.raises(t.TemplateError):
        t.render("evidence.renew", {"reference": "CT-12"}, "/evidence/", ORIGIN)
    with pytest.raises(t.TemplateError):
        t.render("evidence.renew", {"reference": "CT-12", "due": "next week"}, "/evidence/", ORIGIN)
    with pytest.raises(t.TemplateError):
        t.render("evidence.renew", {"reference": "CT-12", "due": "2026-10-20", "title": "Secret file"}, "/evidence/", ORIGIN)


def test_a_route_must_be_one_the_template_allows():
    ok = {"reference": "CT-12", "due": "2026-10-20"}
    for bad in ("https://evil.example/", "//evil.example/", "/aria/", "evidence/", "/evidence/\r\nSet-Cookie: x", "\\evidence"):
        with pytest.raises(t.TemplateError):
            t.render("evidence.renew", ok, bad, ORIGIN)
    assert t.render("evidence.renew", ok, "/evidence/?open=item:4", ORIGIN)["link"] == ORIGIN + "/evidence/?open=item:4"


def test_without_an_origin_the_message_carries_no_link_and_says_where_to_look():
    got = t.render("evidence.renew", {"reference": "CT-12", "due": "2026-10-20"}, "/evidence/", "")
    assert got["link"] == "" and "href" not in got["html"]
    assert "open My Work" in got["text"] and "http" not in got["text"]


def test_a_deadline_with_a_time_is_stated_in_utc_and_the_hours_are_a_bounded_number():
    got = t.render("privacy.deadline", {"reference": "BR-104", "due": "2026-10-14 16:00:00", "hours": 6},
                   "/sentinel/?open=breach:7", ORIGIN)
    assert "14 Oct 2026, 16:00 UTC" in got["text"] and "About 6 hour(s) remained" in got["text"]
    assert got["subject"] == "ThemisIQ: a privacy case needs review", "the subject carries no field"
    assert "Reference: BR-104." in got["text"]
    with pytest.raises(t.TemplateError):
        t.render("privacy.deadline", {"reference": "BR-104", "due": "2026-10-14", "hours": -1}, "/sentinel/", ORIGIN)
    with pytest.raises(t.TemplateError):
        t.render("privacy.deadline", {"reference": "BR-104", "due": "2026-10-14", "hours": "soon"}, "/sentinel/", ORIGIN)


def test_the_weekly_summary_states_counts_and_nothing_about_a_record():
    got = t.render("summary.weekly", {"audits": 3, "overdue": 1}, "/grid/", ORIGIN)
    assert "3 audit(s) in your scope and 1 overdue control(s)" in got["text"]
    with pytest.raises(t.TemplateError):
        t.render("summary.weekly", {"audits": 3}, "/grid/", ORIGIN)


def test_html_escapes_what_it_prints():
    got = t.render("action.assigned", {"kind": "task", "reference": "T-1"}, "/my-work", ORIGIN)
    assert "<script" not in got["html"]
    assert t.ACTION_KINDS["task"] in got["text"]
