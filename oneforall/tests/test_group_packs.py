"""
Group packs (plan 21, slice 6): frozen, signed off by a second person, reproducible, and never a way round the grants.

Service level on SQLite. The database-level immutability of a decided pack is tested on real PostgreSQL in
tests/test_postgres_init.py.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.governance import group_figures as gf
from modules.governance import group_packs as gp


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None).isoformat()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _user(db, org, key, role):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key.replace("_", " ").title(),
              password_hash="t", org_id=org, is_active=1)
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": None, "roles": [role], "is_super_admin": False,
            "full_name": key.replace("_", " ").title(), "username": key}


def _snap(db, org, key, value, module, version=1, as_of=None):
    detail = {}
    as_of = as_of or _now()
    row = {"measure_key": key, "state": "measured", "value": float(value), "window": "", "detail": detail}
    return _id(db, "group_figure_snapshots", source_org_id=org, measure_key=key, module=module, state="measured",
               value=float(value), window_text="", detail_json=json.dumps(detail), method_version="t", as_of=as_of,
               publication_version=version, content_hash=gf._hash(org, row, as_of, version))


@pytest.fixture
def world(test_db):
    db = test_db
    parent = _id(db, "organizations", name="Pack Parent", slug="pk_parent", status="active")
    child = _id(db, "organizations", name="Pack Child", slug="pk_child", status="active")
    terms = json.dumps({"figure_measures": list(gf.PUBLISHABLE)})
    relation = _id(db, "org_relationships", parent_org_id=parent, child_org_id=child, status="active", purpose="Group",
                   child_ack_by=1, privacy_review_by=2, legal_review_by=3, terms_json=terms, review_due_at=_future(90))
    users = {"grc": _user(db, parent, "pk_grc", "grc_officer"), "comp": _user(db, parent, "pk_comp", "compliance_manager"),
             "audit": _user(db, parent, "pk_audit", "audit_lead"), "dpo": _user(db, parent, "pk_dpo", "dpo"),
             "emp": _user(db, parent, "pk_emp", "employee"),
             "child_grc": _user(db, child, "pk_child_grc", "grc_officer"),
             "child_comp": _user(db, child, "pk_child_comp", "compliance_manager")}
    for who in ("grc", "comp", "audit", "dpo"):
        _id(db, "group_view_grants", relationship_id=relation, source_org_id=child, viewer_org_id=parent,
            user_id=users[who]["id"], capability="figure.view", expires_at=_future(30), review_due_at=_future(7),
            granted_by=999)
    snaps = {}
    for org in (parent, child):
        snaps[org, "breach"] = _snap(db, org, "cc.open_breaches", 2 if org == parent else 5, "sentinel")
        snaps[org, "audit"] = _snap(db, org, "cc.grid_open_audit_controls", 1 if org == parent else 4, "grid")
    return db, parent, child, relation, users, snaps


def _make(db, users, who="grc", title="Q4 board pack", period="Q4 2026"):
    return gp.create(db, users[who], title, period)


def _figures(pack, name):
    entity = next(e for e in pack["entities"] if e["name"] == name)
    return {f["key"]: f["value"] for f in entity["figures"]}


def test_a_pack_freezes_the_figures_the_author_could_see_and_does_not_follow_later_publications(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    _snap(db, child, "cc.open_breaches", 99, "sentinel", version=2)
    pack = gp.get(db, users["grc"], pack_id)
    assert pack["status"] == "proposed" and pack["verified"] is True
    assert _figures(pack, "Pack Child") == {"cc.open_breaches": 5.0, "cc.grid_open_audit_controls": 4.0}
    assert _figures(pack, "Pack Parent") == {"cc.open_breaches": 2.0, "cc.grid_open_audit_controls": 1.0}
    assert len(pack["content_hash"]) == 64


def test_the_author_needs_the_capability_a_title_and_something_published(world):
    db, parent, child, relation, users, snaps = world
    for who in ("audit", "dpo", "emp"):
        with pytest.raises(HTTPException) as denied:
            gp.create(db, users[who], "A pack", "Q4")
        assert denied.value.status_code == 403
    for title, period in (("ab", "Q4"), ("", "Q4"), (None, "Q4"), ("Fine title", ""), ("Fine title", "x" * 99)):
        with pytest.raises(HTTPException) as bad:
            gp.create(db, users["grc"], title, period)
        assert bad.value.status_code == 422
    db.execute("DELETE FROM group_figure_snapshots")
    db.commit()
    with pytest.raises(HTTPException) as nothing:
        gp.create(db, users["grc"], "Empty pack", "Q4")
    assert nothing.value.status_code == 409


def test_a_pack_is_signed_off_by_a_different_person_and_the_decision_is_final(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    assert [p["can_review"] for p in gp.listing(db, users["grc"])] == [False], "the author cannot sign off"
    assert [p["can_review"] for p in gp.listing(db, users["comp"])] == [True]
    with pytest.raises(HTTPException) as own:
        gp.review(db, users["comp"] | {"id": users["grc"]["id"]}, pack_id, "issued", "Checked against the sources")
    assert own.value.status_code == 409
    for who, code in (("grc", 403), ("emp", 403)):
        with pytest.raises(HTTPException) as denied:
            gp.review(db, users[who], pack_id, "issued", "Checked against the sources")
        assert denied.value.status_code == code
    for decision, note in (("approved", "Checked against the sources"), ("issued", "short")):
        with pytest.raises(HTTPException) as bad:
            gp.review(db, users["comp"], pack_id, decision, note)
        assert bad.value.status_code == 422
    assert gp.review(db, users["comp"], pack_id, "issued", "Checked against the sources") == {"id": pack_id, "status": "issued"}
    db.commit()
    with pytest.raises(HTTPException) as again:
        gp.review(db, users["audit"], pack_id, "rejected", "Changed my mind about this")
    assert again.value.status_code == 404
    pack = gp.get(db, users["grc"], pack_id)
    assert (pack["status"], pack["reviewed_by"]) == ("issued", "Pk Comp")


def test_a_pack_that_no_longer_matches_what_was_frozen_says_so(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    assert gp.get(db, users["grc"], pack_id)["verified"] is True
    db.execute("UPDATE group_figure_snapshots SET value=50 WHERE id=%s", (snaps[child, "breach"],))
    db.commit()
    assert gp.get(db, users["grc"], pack_id)["verified"] is False, "an edited snapshot no longer hashes to its record"
    db.execute("UPDATE group_figure_snapshots SET value=5 WHERE id=%s", (snaps[child, "breach"],))
    db.commit()
    assert gp.get(db, users["grc"], pack_id)["verified"] is True
    db.execute("UPDATE group_packs SET title='A different title' WHERE id=%s", (pack_id,))
    db.commit()
    assert gp.get(db, users["grc"], pack_id)["verified"] is False, "the manifest hash covers the title"
    db.execute("UPDATE group_packs SET title='Q4 board pack' WHERE id=%s", (pack_id,))
    manifest = json.loads(db.execute("SELECT manifest_json FROM group_packs WHERE id=%s", (pack_id,)).fetchone()[0])
    manifest[1]["snapshots"].pop()
    db.execute("UPDATE group_packs SET manifest_json=%s WHERE id=%s", (json.dumps(manifest), pack_id))
    db.commit()
    assert gp.get(db, users["grc"], pack_id)["verified"] is False, "a figure dropped from the manifest is noticed"


def test_a_reader_sees_only_the_families_their_role_allows(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    assert set(_figures(gp.get(db, users["dpo"], pack_id), "Pack Child")) == {"cc.open_breaches"}
    assert set(_figures(gp.get(db, users["audit"], pack_id), "Pack Child")) == {"cc.grid_open_audit_controls"}
    assert set(_figures(gp.get(db, users["comp"], pack_id), "Pack Child")) == {"cc.open_breaches", "cc.grid_open_audit_controls"}


def test_a_pack_is_not_a_way_round_the_grants_or_the_terms(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    db.execute("UPDATE group_view_grants SET revoked_at=%s WHERE user_id=%s", ('2020-01-01T00:00:00', users["audit"]["id"]))
    db.execute("UPDATE group_view_grants SET expires_at='2020-01-01T00:00:00' WHERE user_id=%s", (users["dpo"]["id"],))
    db.commit()
    for who in ("audit", "dpo"):
        names = [e["name"] for e in gp.get(db, users[who], pack_id)["entities"]]
        assert names == ["Pack Parent"], "without a current grant the subsidiary is left out, with no placeholder"
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
               (json.dumps({"figure_measures": ["cc.open_breaches"]}), relation))
    db.commit()
    assert set(_figures(gp.get(db, users["comp"], pack_id), "Pack Child")) == {"cc.open_breaches"}, \
        "narrowing the terms stops showing what was frozen"
    db.execute("UPDATE org_relationships SET status='ended' WHERE id=%s", (relation,))
    db.commit()
    assert [e["name"] for e in gp.get(db, users["comp"], pack_id)["entities"]] == ["Pack Parent"]


def test_another_organization_cannot_open_the_pack_and_a_missing_one_looks_the_same(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    with pytest.raises(HTTPException) as foreign:
        gp.get(db, users["child_grc"], pack_id)
    with pytest.raises(HTTPException) as missing:
        gp.get(db, users["grc"], pack_id + 999)
    assert foreign.value.status_code == missing.value.status_code == 404
    with pytest.raises(HTTPException) as employee:
        gp.get(db, users["emp"], pack_id)
    assert employee.value.status_code == 403
    assert gp.listing(db, users["comp"])[0]["id"] == pack_id
    assert all(p["id"] != pack_id for p in gp.listing(db, {**users["comp"], "org_id": child}))


def test_a_later_correction_is_shown_beside_the_pack_and_does_not_change_it(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    gp.review(db, users["comp"], pack_id, "issued", "Checked against the sources")
    db.commit()
    restatement = gf.propose_restatement(db, users["child_grc"], "cc.open_breaches", 3, "Duplicates were merged on review")
    db.commit()
    gf.review_restatement(db, users["child_comp"], restatement, "approved", "Confirmed against the register")
    db.commit()
    pack = gp.get(db, users["comp"], pack_id)
    assert pack["verified"] is True, "the pack itself is untouched"
    assert _figures(pack, "Pack Child")["cc.open_breaches"] == 5.0
    assert len(pack["corrections"]) == 1
    fix = pack["corrections"][0]
    assert (fix["name"], fix["pack_value"], fix["corrected_value"]) == ("Pack Child", 5.0, 3.0)
    assert fix["reason"] == "Duplicates were merged on review"
    # The correction is shown only to a reader who may see that subsidiary's figure.
    assert gp.get(db, users["dpo"], pack_id)["corrections"][0]["key"] == "cc.open_breaches"
    assert gp.get(db, users["audit"], pack_id)["corrections"] == [], "outside the audit lead's families"


def test_opening_and_exporting_a_pack_are_recorded_for_each_subsidiary_shown(world):
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    gp.get(db, users["comp"], pack_id)
    gp.log_export(db, users["comp"], pack_id, "pdf")
    db.commit()
    actions = [r[0] for r in db.execute(
        "SELECT action FROM group_access_events WHERE source_org_id=%s AND action LIKE 'pack_%' ORDER BY id", (child,))]
    assert actions == ["pack_view", "pack_export_pdf"]


def test_the_pack_exports_to_pdf_and_excel_from_the_same_data(world):
    from core.report_kit.render_pdf import render_pdf
    from core.report_kit.render_xlsx import render_xlsx
    db, parent, child, relation, users, snaps = world
    pack_id = _make(db, users)
    gp.review(db, users["comp"], pack_id, "issued", "Checked against the sources")
    db.commit()
    pack = gp.get(db, users["comp"], pack_id)
    report = gp.build_report(users["comp"], "Pack Parent", pack)
    assert report.meta.title == "Q4 board pack" and report.meta.reference == f"Pack {pack_id}"
    assert render_pdf(report).startswith(b"%PDF")
    workbook = render_xlsx(report)
    assert workbook.startswith(b"PK")
    import io
    import openpyxl
    sheets = openpyxl.load_workbook(io.BytesIO(workbook)).sheetnames
    assert any("Pack Child" in s for s in sheets) and any("Pack Parent" in s for s in sheets)
    draft = gp.get(db, users["grc"], _make(db, users, title="Draft pack"))
    assert gp.build_report(users["grc"], "Pack Parent", draft).meta.subtitle == "Draft: not signed off"
