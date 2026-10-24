"""The Privacy DPIA form: what a person types is stored and read back.

The DPIA drawer sent description, mitigations, assessor and due_date, and create_dpia / update_dpia kept only the keys in
_DPIA_FIELDS, which held none of them, so all four were dropped on every save without an error (item O12 of the report
exports ledger). "Assessor / Owner" is stored in the owner column; the due date is a new column, due_date, which the list
page's overdue banner and Due column read.

The expectations are written out by hand: a known text per field, read back from a fresh database. A DPIA that was saved
before the column existed must come through the upgrade untouched, and the upgrade must be safe to run again.

The last part pins how a report on a DPIA reaches the documents around it: through the Evidence Vault, by the connected
view of the record, which applies the reader's own scope.
"""
import itertools
import re
from pathlib import Path

import pytest

import database
import modules.sentinel.data_service as ds
from modules.governance import entity360
from tests.test_platform_ownership import _insert, world  # noqa: F401
from tests.test_sentinel_write_scope import http  # noqa: F401  (a signed in client on the Sentinel router)

TYPED = {
    "description": "Scoring of customers for credit limits",
    "owner": "Privacy office, T. Moyo",
    "due_date": "2026-11-30",
    "mitigations": "Scores are pseudonymised and access is reviewed every quarter",
}
CHANGED = {
    "description": "Scoring of customers for credit and card limits",
    "owner": "Data protection officer",
    "due_date": "2027-02-01",
    "mitigations": "A person reviews every refusal",
}


def _read(dpia):
    return {field: dpia[field] for field in TYPED}


# ── What is typed is stored ─────────────────────────────────────────────────

def test_a_new_dpia_keeps_what_was_typed(test_db):
    dpia = ds.get_dpia(ds.create_dpia({"title": "Credit scoring", **TYPED}))
    assert _read(dpia) == TYPED


def test_an_edited_dpia_keeps_what_was_typed_and_the_list_shows_it(test_db):
    dpia_id = ds.create_dpia({"title": "Credit scoring"})
    assert _read(ds.get_dpia(dpia_id)) == dict.fromkeys(TYPED)  # nothing is made up for a new one
    ds.update_dpia(dpia_id, dict(TYPED))
    assert _read(ds.get_dpia(dpia_id)) == TYPED
    listed = next(row for row in ds.list_dpias() if row["id"] == dpia_id)  # the page reads its Due column from here
    assert _read(listed) == TYPED


def test_each_field_changes_on_its_own_and_leaves_the_others(test_db):
    dpia_id = ds.create_dpia({"title": "Credit scoring", **TYPED})
    expected = dict(TYPED)
    for field, newer in CHANGED.items():
        ds.update_dpia(dpia_id, {field: newer})
        expected[field] = newer
        assert _read(ds.get_dpia(dpia_id)) == expected, field


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_an_emptied_due_date_is_stored_as_no_date(test_db, blank):
    dpia_id = ds.create_dpia({"title": "Credit scoring", "due_date": "2026-11-30"})
    assert ds.get_dpia(dpia_id)["due_date"] == "2026-11-30"
    ds.update_dpia(dpia_id, {"due_date": blank})
    assert ds.get_dpia(dpia_id)["due_date"] is None
    assert ds.get_dpia(ds.create_dpia({"title": "Second", "due_date": blank}))["due_date"] is None


def test_a_due_date_is_kept_as_typed_without_the_padding_a_form_may_add(test_db):
    assert ds.get_dpia(ds.create_dpia({"title": "T", "due_date": " 2026-11-30 "}))["due_date"] == "2026-11-30"


@pytest.mark.parametrize("bad", [
    "31/12/2026", "2026-13-01", "2026-02-30", "2026-1-5", "tomorrow", "2026-11-30T10:00:00",
    '2026-11-30" autofocus onfocus="alert(1)'])
def test_a_due_date_that_is_not_a_date_is_refused_and_nothing_is_stored(test_db, bad):
    """The form reads the stored date back into an input and compares it with today, so it has to be a date."""
    with pytest.raises(ValueError, match="due date must be a date written YYYY-MM-DD"):
        ds.create_dpia({"title": "Refused", "due_date": bad})
    assert ds.list_dpias() == []

    dpia_id = ds.create_dpia({"title": "Credit scoring", "due_date": "2026-11-30"})
    with pytest.raises(ValueError):
        ds.update_dpia(dpia_id, {"due_date": bad, "mitigations": "Changed along with it"})
    kept = ds.get_dpia(dpia_id)
    assert (kept["due_date"], kept["mitigations"]) == ("2026-11-30", None)


def test_the_api_stores_and_returns_what_the_drawer_sends(http):
    made = http("post", "/sentinel/api/dpias", json={"title": "Credit scoring", **TYPED})
    assert made.status_code == 201
    assert _read(made.json()) == TYPED
    dpia_id = made.json()["id"]

    changed = http("put", f"/sentinel/api/dpias/{dpia_id}", json=CHANGED)
    assert changed.status_code == 200
    assert _read(changed.json()) == CHANGED

    listed = next(row for row in http("get", "/sentinel/api/dpias").json() if row["id"] == dpia_id)
    assert _read(listed) == CHANGED


def test_the_api_answers_400_for_a_due_date_that_is_not_a_date_and_stores_nothing(http):
    refused = http("post", "/sentinel/api/dpias", json={"title": "Refused", "due_date": "tomorrow"})
    assert refused.status_code == 400 and "YYYY-MM-DD" in refused.json()["detail"]
    dpia_id = http("post", "/sentinel/api/dpias", json={"title": "Credit scoring", **TYPED}).json()["id"]

    refused = http("put", f"/sentinel/api/dpias/{dpia_id}", json={"due_date": "31/12/2026", "mitigations": "Changed"})
    assert refused.status_code == 400
    kept = http("get", f"/sentinel/api/dpias/{dpia_id}").json()
    assert (kept["due_date"], kept["mitigations"]) == (TYPED["due_date"], TYPED["mitigations"])
    assert [row["title"] for row in http("get", "/sentinel/api/dpias").json()] == ["Credit scoring"]


def test_text_with_quotes_ampersands_and_line_breaks_comes_back_as_typed(http):
    typed = {"title": 'Customer "VIP" scoring & limits', "description": 'Scoring of "A & B"\nsecond line',
             "owner": "O'Brien & \"Sons\"", "mitigations": "Rule: score > 5 triggers review (see 'Policy 7')"}
    made = http("post", "/sentinel/api/dpias", json=typed)
    assert made.status_code == 201
    assert {field: made.json()[field] for field in typed} == typed


# ── The column arrives without touching what was there ──────────────────────

def test_a_dpia_from_before_the_column_has_no_due_date_and_the_upgrade_can_run_again(test_db):
    test_db.execute("ALTER TABLE sentinel_dpias DROP COLUMN due_date")  # the database as it was before this change
    test_db.execute(
        "INSERT INTO sentinel_dpias (ref_number, title, status, owner, mitigations) "
        "VALUES ('DPIA-OLD', 'Old DPIA', 'in_progress', 'Legal', 'Existing measures')")
    test_db.commit()
    assert "due_date" not in {row[1] for row in test_db.execute("PRAGMA table_info(sentinel_dpias)").fetchall()}

    for _ in range(2):  # the second run finds nothing to do
        database._run_sqlite_alters(test_db)
        rows = test_db.execute("SELECT * FROM sentinel_dpias").fetchall()
        assert len(rows) == 1
        old = dict(rows[0])
        assert old["due_date"] is None
        assert (old["title"], old["status"], old["owner"], old["mitigations"]) == (
            "Old DPIA", "in_progress", "Legal", "Existing measures")


# ── The forms and the data service agree on what is stored ──────────────────

_TEMPLATE = Path(__file__).resolve().parent.parent / "modules" / "sentinel" / "templates" / "index.html"
# Keys a DPIA form sends that are deliberately not stored (PLAN_dpia_form_fields_2026-10-22.md, decision D3).
NOT_STORED = set()  # risk_level is now stored: derived from the chosen overall rating, never taken from the client


def _drawer_keys(source):
    start = source.index("window.snSaveDpiaDrawer=")
    body = source[source.index("var data={", start):]
    return set(re.findall(r"(?:^|[{,\s])([a-z_]+):", body[:body.index("};")]))


def _modal_keys(source):
    start = re.search(r"dpia:\{\s*title:'DPIA Assessment'", source).start()
    return set(re.findall(r"\{name:'([a-z_]+)'", source[start:source.index("breach:{", start)]))


def test_every_key_the_dpia_forms_send_is_stored_or_named_as_not_stored():
    """A key the data service does not list is dropped without an error. That is how four fields were lost."""
    source = _TEMPLATE.read_text(encoding="utf-8")
    drawer, modal = _drawer_keys(source), _modal_keys(source)
    for sent in (drawer, modal):
        assert set(TYPED) <= sent and "title" in sent, "the forms' payloads were not found in the template"
    dropped = (drawer | modal) - set(ds._DPIA_FIELDS)
    assert dropped == NOT_STORED, (
        f"dropped without being named: {sorted(dropped - NOT_STORED)}; named as not stored but stored now: "
        f"{sorted(NOT_STORED - dropped)}")


# ── A report reaches a DPIA's documents through the Evidence Vault ──────────

_REF = itertools.count(1)


def _dpia(world, tag):
    return _insert(world.db, "sentinel_dpias", ref_number=f"DPIA-F-{next(_REF)}", title=f"DPIA {tag}",
                   business_unit_id=world.unit[tag])


def _document(world, title, org_id=1, **columns):
    """A file in the Evidence Vault: filed under an organization, and under a unit when one is given."""
    return _insert(world.db, "evidence_items", title=title, org_id=org_id, **columns)


def _attach(world, evidence_id, dpia_id, **columns):
    """Link a file to the DPIA the way the Vault does."""
    return _insert(world.db, "evidence_links", evidence_id=evidence_id, module="sentinel", entity_type="dpia",
                   entity_id=dpia_id, **columns)


def _documents(world, persona, dpia_id):
    """What a report lists as the documents of a DPIA: the proof section of the record's connected view (None when the
    reader may not open the DPIA)."""
    view = entity360.get_connected(world.db, world.users[persona], "sentinel", "dpia", dpia_id)
    return None if view is None else view["proof"]


def test_a_report_lists_the_vault_documents_linked_to_the_dpia_each_with_its_link(world):
    dpia = _dpia(world, "A")
    procedure = _document(world, "Credit scoring procedure", version=3, expiry_date="2099-01-01")
    memo = _document(world, "Supervisory authority memo")
    _attach(world, procedure, dpia)
    _attach(world, memo, dpia, review_status="accepted")

    proof = _documents(world, "dpo_a", dpia)

    assert proof["state"] == "ok" and proof["counts"] == {"files": 2, "accepted": 1}
    shown = {item["title"]: item for item in proof["items"]}
    assert set(shown) == {"Credit scoring procedure", "Supervisory authority memo"}
    assert shown["Credit scoring procedure"]["url"] == f"/evidence/?open=item:{procedure}"
    assert (shown["Credit scoring procedure"]["version"], shown["Credit scoring procedure"]["expiry_date"],
            shown["Credit scoring procedure"]["state"]) == (3, "2099-01-01", "Waiting for a reviewer")
    assert shown["Supervisory authority memo"]["url"] == f"/evidence/?open=item:{memo}"
    assert shown["Supervisory authority memo"]["state"] == "Accepted"


def test_a_removed_link_an_archived_file_and_a_file_the_reader_may_not_open_are_not_listed(world):
    dpia = _dpia(world, "A")
    other_org = _insert(world.db, "organizations", name="Other organization", slug="other-organization")
    wanted = {
        "Organization wide file": _document(world, "Organization wide file"),
        "File in the reader's unit": _document(world, "File in the reader's unit", business_unit_id=world.unit["A"]),
    }
    hidden = {
        "Removed link": (_document(world, "Removed link"), {"deleted_at": "2026-10-01 10:00:00"}),
        "Archived file": (_document(world, "Archived file", status="archived"), {}),
        "File in another unit": (_document(world, "File in another unit", business_unit_id=world.unit["B"]), {}),
        "File of another organization": (_document(world, "File of another organization", org_id=other_org), {}),
    }
    for evidence_id in wanted.values():
        _attach(world, evidence_id, dpia)
    for evidence_id, columns in hidden.values():
        _attach(world, evidence_id, dpia, **columns)

    assert {i["title"] for i in _documents(world, "dpo_a", dpia)["items"]} == set(wanted)
    # the positive twin: an administrator reads every file that is still linked and not archived
    assert {i["title"] for i in _documents(world, "super", dpia)["items"]} == (
        set(wanted) | {"File in another unit", "File of another organization"})


def test_a_replaced_or_expired_file_says_so_and_a_dpia_the_reader_may_not_open_lists_nothing(world):
    dpia = _dpia(world, "A")
    _attach(world, _document(world, "Old procedure", status="superseded"), dpia)
    _attach(world, _document(world, "Lapsed certificate", expiry_date="2020-01-01"), dpia)

    states = {i["title"]: i["state"] for i in _documents(world, "dpo_a", dpia)["items"]}
    assert states == {"Old procedure": "Replaced by a newer version", "Lapsed certificate": "Expired"}
    assert _documents(world, "dpo_b", dpia) is None  # a DPIA in unit A is not unit B's: not even its documents


def test_a_dpia_with_no_linked_file_says_so_and_does_not_invent_one(world):
    proof = _documents(world, "dpo_a", _dpia(world, "A"))
    assert proof["state"] == "empty" and proof["items"] == []
    assert _documents(world, "dpo_a", 987654) is None
