"""Reuse an earlier audit (plan 25, CISO 02): suggestions only, one hop, reviewed mappings, idempotent and undoable."""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from modules.grid import reuse


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _person(db, org, name, role, unit):
    uid = _id(db, "users", username=name, email=name + "@example.invalid", full_name=name, password_hash="x",
              org_id=org, business_unit_id=unit, is_active=1)
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role], "is_super_admin": False}


def _expect(code, work):
    with pytest.raises(HTTPException) as refused:
        work()
    assert refused.value.status_code == code, refused.value.detail
    return refused.value.detail


@pytest.fixture
def world(test_db):
    db = test_db
    org = _id(db, "organizations", name="Reuse Co", slug="reuse_co", status="active")
    unit, other = _id(db, "business_units", name="Ops", is_active=1), _id(db, "business_units", name="Far", is_active=1)
    people = {"lead": _person(db, org, "ru_lead", "audit_lead", unit),
              "reviewer": _person(db, org, "ru_reviewer", "compliance_manager", unit),
              "owner": _person(db, org, "ru_owner", "control_owner", unit),
              "far_lead": _person(db, org, "ru_far", "audit_lead", other),
              "employee": _person(db, org, "ru_emp", "employee", unit)}
    earlier = _id(db, "grid_audits", name="ISO 2025", business_unit_id=unit, audit_date="2025-10-01")
    new = _id(db, "grid_audits", name="ISO 2026", business_unit_id=unit)
    hidden = _id(db, "grid_audits", name="Far audit", business_unit_id=other)
    e = {ref: _id(db, "grid_controls", audit_id=earlier, framework_id=7, control_id=ref, name=f"Earlier {ref}",
                  status=status) for ref, status in (("A.1", "Complete"), ("A.2", "In Progress"), ("X.9", "Complete"))}
    n = {ref: _id(db, "grid_controls", audit_id=new, framework_id=7, control_id=ref, name=f"New {ref}")
         for ref in ("A.1", "A.2", "B.5", "C.3")}
    mapping = _id(db, "grid_control_mappings", source_control_id=n["B.5"], target_control_id=e["X.9"],
                  mapping_type="equivalent")
    assignment = _id(db, "grid_assignments", org_id=org, audit_id=earlier, title="2025 questions", assignee_id=people["owner"]["id"],
                     reviewer_id=people["lead"]["id"], due_date="2025-09-01", state="closed", created_by=people["lead"]["id"],
                     created_at="2025-08-01", updated_at="2025-09-02")
    _id(db, "grid_assignment_items", assignment_id=assignment, control_id=e["A.1"], response="Quarterly access review",
        review_state="accepted", reviewed_at="2025-09-02")
    files = {}
    for name, unit_id, expiry, status, review in (("Access review 2025", unit, None, "current", "accepted"),
                                                  ("Old log", unit, "2020-01-01", "current", "accepted"),
                                                  ("Far file", other, None, "current", "accepted"),
                                                  ("Mapping proof", unit, None, "current", "accepted")):
        files[name] = _id(db, "evidence_items", title=name, status=status, version=1, file_hash="h-" + name,
                          org_id=org, business_unit_id=unit_id, expiry_date=expiry, uploaded_by=people["owner"]["id"])
        target = e["X.9"] if name == "Mapping proof" else e["A.1"]
        _id(db, "evidence_links", evidence_id=files[name], module="grid", entity_type="control", entity_id=target,
            linked_by=people["owner"]["id"], review_status=review)
    return db, people, earlier, new, hidden, e, n, files, mapping


def _rows(db, people, new, earlier):
    return {r["target"]["ref"]: r for r in reuse.preview(db, people["lead"], new, earlier)["rows"]}


def test_the_preview_says_what_matches_how_strongly_and_what_is_held_back(world):
    db, people, earlier, new, hidden, e, n, files, mapping = world
    data = reuse.preview(db, people["lead"], new, earlier)
    assert data["counts"] == {"full": 2, "partial": 1, "none": 1, "would_change": 2}
    rows = {r["target"]["ref"]: r for r in data["rows"]}
    a1 = rows["A.1"]
    assert (a1["relation"], a1["basis"]) == ("full", "The same requirement in both audits")
    assert a1["answer"] == {"text": "Quarterly access review", "accepted_at": "2025-09-02"} and a1["note"] is True
    assert [p["title"] for p in a1["proof"]] == ["Access review 2025"], "expired proof and another unit's file stay out"
    assert any("Old log" in h for h in a1["held_back"])
    assert "Far file" not in str(data), "a file the viewer cannot open is never named"
    assert rows["A.2"]["relation"] == "full" and not rows["A.2"]["would_change"]
    assert any("In Progress, not Complete" in h for h in rows["A.2"]["held_back"])
    b5 = rows["B.5"]
    assert b5["relation"] == "partial" and "nobody has reviewed" in b5["basis"] and b5["mapping_id"] == mapping
    assert b5["carry"] == [files["Mapping proof"]] and b5["note"] is False
    assert rows["C.3"]["relation"] == "none" and rows["C.3"]["source"] is None


def test_only_an_audit_lead_who_may_open_both_audits_reuses(world):
    db, people, earlier, new, hidden, e, n, files, mapping = world
    _expect(403, lambda: reuse.preview(db, people["employee"], new, earlier))
    _expect(404, lambda: reuse.preview(db, people["lead"], new, hidden))
    _expect(404, lambda: reuse.preview(db, people["far_lead"], new, earlier))
    _expect(422, lambda: reuse.preview(db, people["lead"], new, new))


def test_applying_adds_suggestions_only_once_and_a_changed_source_needs_a_fresh_preview(world):
    db, people, earlier, new, hidden, e, n, files, mapping = world
    rows = _rows(db, people, new, earlier)
    picks = [{"target_control_id": rows[ref]["target"]["id"], "fingerprint": rows[ref]["fingerprint"]}
             for ref in ("A.1", "B.5", "C.3")]
    db.execute("UPDATE evidence_links SET review_status='returned' WHERE evidence_id=%s", (files["Mapping proof"],))
    db.commit()
    _expect(409, lambda: reuse.apply(db, people["lead"], new, earlier, picks))
    rows = _rows(db, people, new, earlier)
    picks = [{"target_control_id": rows[ref]["target"]["id"], "fingerprint": rows[ref]["fingerprint"]}
             for ref in ("A.1", "B.5", "C.3")]
    result = reuse.apply(db, people["lead"], new, earlier, picks)
    db.commit()
    assert (result["applied"], result["links"], result["notes"]) == (1, 1, 1), "B.5 lost its proof, C.3 has none"
    link = db.execute("SELECT entity_id, linked_by, review_status FROM evidence_links WHERE evidence_id=%s AND "
                      "entity_id=%s", (files["Access review 2025"], n["A.1"])).fetchone()
    assert (link["linked_by"], link["review_status"]) == (people["lead"]["id"], None), "waiting for review"
    comment = db.execute("SELECT content FROM grid_control_comments WHERE control_id=%s", (n["A.1"],)).fetchone()[0]
    assert comment.startswith("Suggested, not yet assessed. From ISO 2025") and "Quarterly access review" in comment
    assert db.execute("SELECT status FROM grid_controls WHERE id=%s", (n["A.1"],)).fetchone()[0] in (None, "Not Started")
    again = _rows(db, people, new, earlier)["A.1"]
    assert again["would_change"] is False and again["carry"] == [] and again["note"] is False
    second = reuse.apply(db, people["lead"], new, earlier,
                         [{"target_control_id": n["A.1"], "fingerprint": again["fingerprint"]}])
    assert second == {"decision_id": None, "applied": 0, "links": 0, "notes": 0}, "a rerun adds nothing"


def test_a_mapping_reviewed_as_equivalent_becomes_a_full_match(world):
    db, people, earlier, new, hidden, e, n, files, mapping = world
    _expect(403, lambda: reuse.review_mapping(db, people["employee"], mapping, "equivalent"))
    _expect(422, lambda: reuse.review_mapping(db, people["lead"], mapping, "same"))
    reuse.review_mapping(db, people["lead"], mapping, "equivalent")
    db.commit()
    b5 = _rows(db, people, new, earlier)["B.5"]
    assert (b5["relation"], b5["basis"]) == ("full", "A mapping a person reviewed as equivalent")
    reuse.review_mapping(db, people["lead"], mapping, "partial")
    db.commit()
    assert _rows(db, people, new, earlier)["B.5"]["relation"] == "partial"


def test_undo_takes_back_what_it_added_until_something_was_reviewed(world):
    db, people, earlier, new, hidden, e, n, files, mapping = world
    rows = _rows(db, people, new, earlier)
    picks = [{"target_control_id": rows[r]["target"]["id"], "fingerprint": rows[r]["fingerprint"]} for r in ("A.1", "B.5")]
    first = reuse.apply(db, people["lead"], new, earlier, picks)
    db.commit()
    _expect(422, lambda: reuse.undo(db, people["lead"], first["decision_id"], ""))
    assert reuse.undo(db, people["lead"], first["decision_id"], "Wrong earlier audit") == {"links_removed": 2,
                                                                                          "notes_removed": 1}
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM evidence_links WHERE entity_id IN (%s,%s) AND deleted_at IS NULL "
                      "AND module='grid'", (n["A.1"], n["B.5"])).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM grid_control_comments WHERE control_id=%s", (n["A.1"],)).fetchone()[0] == 0
    _expect(409, lambda: reuse.undo(db, people["lead"], first["decision_id"], "Again"))
    rows = _rows(db, people, new, earlier)
    assert rows["A.1"]["would_change"] and rows["A.1"]["note"], "after an undo it can be applied again"
    second = reuse.apply(db, people["lead"], new, earlier, [{"target_control_id": n["A.1"],
                                                             "fingerprint": rows["A.1"]["fingerprint"]}])
    db.commit()
    db.execute("UPDATE evidence_links SET review_status='accepted' WHERE entity_id=%s AND deleted_at IS NULL",
               (n["A.1"],))
    db.commit()
    message = _expect(409, lambda: reuse.undo(db, people["lead"], second["decision_id"], "Changed my mind"))
    assert "reviewed since" in message
    history = reuse.history(db, people["lead"], new)
    assert [h["undone_at"] is not None for h in history] == [False, True]
