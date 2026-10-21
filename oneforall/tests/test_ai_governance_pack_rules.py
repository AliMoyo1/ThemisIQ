"""
AI governance G6a: the pure rules of a review pack.

Written by hand. The hash identifies content and not the moment it was generated; people's names and free text leave only
when chosen; a section the author could not read says so in the pack's own words; a recipient is refused for exactly the
reasons the plan lists; and a manifest that no longer hashes to its recorded value is never shown.
"""
import json

import pytest

from modules.ai_governance import review_packs as packs

OPTIONS = {"include_people": False, "include_notes": False}
PEOPLE = {"include_people": True, "include_notes": False}
NOTES = {"include_people": False, "include_notes": True}
BOTH = {"include_people": True, "include_notes": True}
WHEN = "2026-10-11 09:00:00"


def raw_sections():
    return [
        {"key": "use", "title": "The AI use", "items": [
            {"title": "Ticket summarizer", "status": "Lower", "when": "2026-09-01", "detail": ["Purpose: Summarize tickets"],
             "people": [("Owner", "Ada Lovelace")], "notes": [("Why this tier was adopted", "Reviewed with legal")]}]},
        {"key": "gaps", "title": "Known gaps", "items": [
            {"title": "Provider review is required and not started", "status": "gap", "detail": ["Acme is a vendor"]}]},
        {"key": "evaluations", "title": "Evaluations", "state": "unavailable", "items": []},
        {"key": "evidence", "title": "Attached evidence", "state": "no_access", "items": [], "note": "You do not have access"},
    ]


def make(options=OPTIONS, sections=None, generated=WHEN):
    return packs.assemble(sections if sections is not None else raw_sections(), options, "Ticket summarizer", "Unit A", generated)


# ── The hash ────────────────────────────────────────────────────────────────

def test_the_hash_ignores_when_it_was_generated_and_the_order_of_keys():
    a, b = make(generated="2026-10-11 09:00:00"), make(generated="2026-10-12 17:30:00")
    assert a["hash"] == b["hash"] and a["generated_at"] != b["generated_at"]
    shuffled = dict(reversed(list(a.items())))
    assert packs.content_hash(shuffled) == a["hash"]


def test_the_hash_changes_when_anything_that_is_shown_changes():
    base = make()["hash"]
    changed = raw_sections()
    changed[1]["items"][0]["detail"] = ["Acme is a different vendor"]
    assert make(sections=changed)["hash"] != base
    assert make(PEOPLE)["hash"] != base, "choosing to include names changes what the pack says"


def test_a_manifest_verifies_only_while_it_matches_its_recorded_hash():
    manifest = make()
    stored = json.dumps(manifest)
    assert packs.verifies(stored, manifest["hash"]) == manifest
    tampered = dict(manifest, summary={"gaps": 0, "not_shown": []})
    assert packs.verifies(json.dumps(tampered), manifest["hash"]) is None
    assert packs.verifies(stored, "0" * 64) is None
    assert packs.verifies("not json", manifest["hash"]) is None
    assert packs.verifies(json.dumps([1, 2]), manifest["hash"]) is None
    assert packs.verifies(None, manifest["hash"]) is None


# ── What leaves ─────────────────────────────────────────────────────────────

def lines(manifest, key):
    section = next(s for s in manifest["sections"] if s["key"] == key)
    return [line for item in section["items"] for line in item["lines"]]


def test_no_names_and_no_notes_unless_they_were_chosen():
    assert lines(make(OPTIONS), "use") == ["Purpose: Summarize tickets"]
    assert lines(make(PEOPLE), "use") == ["Purpose: Summarize tickets", "Owner: Ada Lovelace"]
    assert lines(make(NOTES), "use") == ["Purpose: Summarize tickets", "Why this tier was adopted: Reviewed with legal"]
    assert lines(make(BOTH), "use") == ["Purpose: Summarize tickets", "Owner: Ada Lovelace", "Why this tier was adopted: Reviewed with legal"]
    text = json.dumps(make(OPTIONS))
    assert "Ada Lovelace" not in text and "Reviewed with legal" not in text


def test_an_empty_name_or_note_leaves_no_line_behind():
    sections = raw_sections()
    sections[0]["items"][0]["people"] = [("Owner", None), ("Decided by", "")]
    sections[0]["items"][0]["notes"] = [("Rationale", None)]
    assert lines(make(BOTH, sections), "use") == ["Purpose: Summarize tickets"]


def test_a_section_the_author_could_not_read_says_so_in_the_packs_own_words():
    manifest = make()
    by_key = {s["key"]: s for s in manifest["sections"]}
    assert by_key["evaluations"]["state"] == "unavailable" and "could not be read" in by_key["evaluations"]["note"]
    assert by_key["evidence"]["state"] == "no_access" and "does not have access" in by_key["evidence"]["note"]
    assert "You do not have access" not in json.dumps(manifest), "the author's second person wording is replaced"
    assert manifest["summary"]["not_shown"] == ["Evaluations", "Attached evidence"]
    assert manifest["summary"]["gaps"] == 1


def test_a_long_section_is_cut_and_says_how_many_there_were():
    many = [{"key": "gaps", "title": "Known gaps", "items": [{"title": f"Gap {n}"} for n in range(60)]}]
    manifest = make(sections=many)
    section = manifest["sections"][0]
    assert len(section["items"]) == packs.ITEMS_MAX and section["note"] == f"Showing the first {packs.ITEMS_MAX} of 60."
    assert manifest["summary"]["gaps"] == packs.ITEMS_MAX


def test_control_characters_and_long_text_are_trimmed():
    sections = [{"key": "use", "title": "The AI use", "items": [{"title": "T" * 400, "detail": ["a\x00b\x1f" + "x" * 600]}]}]
    item = make(sections=sections)["sections"][0]["items"][0]
    assert len(item["title"]) == packs.TITLE_MAX
    assert len(item["lines"][0]) == packs.LINE_MAX and "\x00" not in item["lines"][0] and "\x1f" not in item["lines"][0]


def test_the_pack_states_that_it_is_not_a_certification():
    assert "not a certification" in make()["disclaimer"] and "does not say the use is compliant" in make()["disclaimer"]


# ── Changes since ───────────────────────────────────────────────────────────

def test_what_changed_since_names_changed_added_and_removed_sections():
    old = make()
    sections = raw_sections()
    sections[1]["items"].append({"title": "New gap", "status": "gap"})
    sections.append({"key": "regulatory", "title": "Regulatory changes", "items": []})
    del sections[2]
    new = make(sections=sections)
    assert packs.changed_sections(old, new) == ["Known gaps", "Regulatory changes", "Evaluations"]
    assert packs.changed_sections(old, make()) == []


# ── Options ─────────────────────────────────────────────────────────────────

def test_the_careful_answer_is_the_default():
    opts, errors = packs.clean_options({"name": "Q4 review"})
    assert errors == {}
    assert opts == {"name": "Q4 review", "purpose": None, "include_people": False, "include_notes": False,
                    "allow_download": False, "expires_days": 30, "recipient_id": None}


@pytest.mark.parametrize("raw, field", [
    ({"name": "ab"}, "name"), ({"name": "x" * 121}, "name"), ({"name": None}, "name"), ({"name": ["a"]}, "name"),
    ({"name": "Good name", "purpose": "p" * 501}, "purpose"), ({"name": "Good name", "purpose": 5}, "purpose"),
    ({"name": "Good name", "include_people": "yes"}, "include_people"),
    ({"name": "Good name", "include_notes": 1}, "include_notes"),
    ({"name": "Good name", "allow_download": "true"}, "allow_download"),
    ({"name": "Good name", "expires_days": 0}, "expires_days"), ({"name": "Good name", "expires_days": 91}, "expires_days"),
    ({"name": "Good name", "expires_days": True}, "expires_days"), ({"name": "Good name", "expires_days": "7"}, "expires_days"),
])
def test_each_bad_option_is_named(raw, field):
    _, errors = packs.clean_options(raw)
    assert field in errors


def test_a_recipient_is_required_only_to_issue():
    assert packs.clean_options({"name": "Good name"})[1] == {}
    assert "recipient_id" in packs.clean_options({"name": "Good name"}, need_recipient=True)[1]
    assert "recipient_id" in packs.clean_options({"name": "Good name", "recipient_id": True}, need_recipient=True)[1]
    assert "recipient_id" in packs.clean_options({"name": "Good name", "recipient_id": "7"}, need_recipient=True)[1]
    opts, errors = packs.clean_options({"name": "Good name", "recipient_id": 7, "expires_days": 90}, need_recipient=True)
    assert errors == {} and opts["recipient_id"] == 7 and opts["expires_days"] == 90


def test_the_name_and_purpose_are_trimmed():
    opts, _ = packs.clean_options({"name": "  Q4 review \x00 ", "purpose": "  For the audit  "})
    assert opts["name"] == "Q4 review" and opts["purpose"] == "For the audit"


# ── Who may open ────────────────────────────────────────────────────────────

def pack(**changes):
    return {"status": "issued", "expires_at": "2026-11-01 00:00:00", "recipient_user_id": 7, **changes}


def test_the_named_recipient_may_open_an_issued_pack_before_it_expires():
    assert packs.open_refusal(pack(), 7, "2026-10-11 09:00:00") is None


@pytest.mark.parametrize("changes, viewer, now, reason", [
    ({"status": "revoked"}, 7, "2026-10-11 09:00:00", "revoked"),
    ({}, 7, "2026-11-01 00:00:00", "expired"),
    ({}, 7, "2026-12-01 00:00:00", "expired"),
    ({}, 8, "2026-10-11 09:00:00", "wrong_recipient"),
    ({"recipient_user_id": None}, 7, "2026-10-11 09:00:00", "wrong_recipient"),
])
def test_a_recipient_is_refused_for_the_reason_the_plan_lists(changes, viewer, now, reason):
    assert packs.open_refusal(pack(**changes), viewer, now) == reason


def test_revoked_is_reported_before_expired_and_expired_before_the_wrong_person():
    assert packs.open_refusal(pack(status="revoked"), 8, "2027-01-01 00:00:00") == "revoked"
    assert packs.open_refusal(pack(), 8, "2027-01-01 00:00:00") == "expired"
