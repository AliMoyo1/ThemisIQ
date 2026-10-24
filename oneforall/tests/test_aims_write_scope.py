"""
Operations Risk AI management (AIMS): the routes that change an assessment hold to its business unit.

The assessment list was scoped to the caller's units, and so is every read of one assessment. The routes that change things were
not: a risk owner in unit A could edit or delete unit B's assessment, a risk in it or a control link on that risk, by id. A risk and
a link carry no unit of their own, so each follows its assessment: every write route finds the assessment first (through the risk or
the link where it was given one of those) and answers 404, never 403, when the caller may not open it, exactly as it answers for an
id that does not exist. An organization wide assessment (no unit) is open to every unit's managers, as it is in the list.
The unit a body names when it creates or edits an assessment is held to the rule Sentinel applies to its records: a unit the writer
cannot open is a 400, and only an administrator takes an assessment out of its unit.
Expectations are written out by hand and each "cannot" has a positive twin.
"""
import types

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
import modules.orm.routes as orm_routes
from core import rbac
from tests.test_platform_ownership import _insert, world  # noqa: F401

TABLES = ("aims_assessments", "aims_risks", "aims_risk_controls")
PLACES = {"org", "A", "A1", "B"}

# persona -> the places whose assessments they may open: their own unit, the units under it, and what is organization wide
OPENS = {
    "super": PLACES,
    "owner_a": {"org", "A", "A1"},
    "owner_a1": {"org", "A1"},
    "owner_b": {"org", "B"},
    "owner_none": {"org"},
}
CONFINED = [persona for persona, opens in OPENS.items() if opens != PLACES]


@pytest.fixture
def web(world, monkeypatch):
    who = {"name": "super"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(orm_routes.router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(method, path, name="super", **kwargs):
        who["name"] = name
        return client.request(method.upper(), path, **kwargs)

    db, unit = world.db, world.unit
    for name, tag, extra in (("owner_a1", "A1", {}), ("owner_none", None, {}), ("owner_a_unlicensed", "A", {"licensed_modules": ["aria"]})):
        unit_id = unit.get(tag) if tag else None
        uid = 300 + len(world.users)
        world.users[name] = {"id": uid, "username": name, "org_id": 1, "business_unit_id": unit_id, "is_super_admin": 0,
                             "roles": [rbac.RISK_OWNER], **extra}
        _insert(db, "users", id=uid, username=name, email=f"{name}@example.test", full_name=name, password_hash="x", org_id=1,
                business_unit_id=unit_id)

    call.rows = {}   # place -> the ids of an assessment of that place, a risk in it and a control link on that risk
    for tag in sorted(PLACES):
        assessment = _insert(db, "aims_assessments", ref=f"AIMS-{tag}", title=f"Assessment {tag}", business_unit_id=unit[tag])
        risk = _insert(db, "aims_risks", assessment_id=assessment, ref="R1", risk_description=f"Risk {tag}")
        link = _insert(db, "aims_risk_controls", risk_id=risk, control_detail=f"Control {tag}", ice_score=50)
        call.rows[tag] = types.SimpleNamespace(assessment=assessment, risk=risk, link=link)
    call.world = world
    return call


def _writes(rows):
    """Every route that changes an assessment, a risk or a control link, aimed at the rows of one place."""
    return [
        ("put", f"/orm/api/aims/{rows.assessment}", {"title": "Edited", "status": "completed"}),
        ("post", f"/orm/api/aims/{rows.assessment}/risks", {"risk_description": "Filed risk"}),
        ("put", f"/orm/api/aims/risks/{rows.risk}", {"risk_description": "Edited risk", "likelihood": 1}),
        ("post", f"/orm/api/aims/risks/{rows.risk}/controls", {"control_detail": "Filed control", "ice_score": 90}),
        ("put", f"/orm/api/aims/controls/{rows.link}", {"control_detail": "Edited control", "ice_score": 0}),
        ("delete", f"/orm/api/aims/controls/{rows.link}", None),
        ("delete", f"/orm/api/aims/risks/{rows.risk}", None),
        ("delete", f"/orm/api/aims/{rows.assessment}", None),
    ]


def _reads(rows):
    return [f"/orm/api/aims/{rows.assessment}", f"/orm/api/aims/{rows.assessment}/risks", f"/orm/api/aims/risks/{rows.risk}",
            f"/orm/api/aims/{rows.assessment}/aggregation", f"/orm/api/aims/{rows.assessment}/aggregation/csv"]


def _snapshot(db):
    return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()] for table in TABLES}


def _value(db, table, row_id, column):
    row = db.execute(f"SELECT {column} FROM {table} WHERE id = %s", (row_id,)).fetchone()
    return row[0] if row else None


def _exists(db, table, row_id):
    return db.execute(f"SELECT 1 FROM {table} WHERE id = %s", (row_id,)).fetchone() is not None


# ── Another unit's assessment cannot be changed, and nothing changes when it is tried ──

@pytest.mark.parametrize("persona", CONFINED)
def test_no_write_route_reaches_the_assessment_of_a_unit_the_caller_cannot_open(web, persona):
    """Edit and delete an assessment, file a risk, edit and delete a risk, file a link, edit and delete a link: all 404, no row touched."""
    db = web.world.db
    foreign = PLACES - OPENS[persona]
    assert foreign, "a persona with nothing foreign would pass for nothing"
    for tag in sorted(foreign):
        before = _snapshot(db)
        for method, path, body in _writes(web.rows[tag]):
            answer = web(method, path, name=persona, json=body)
            assert answer.status_code == 404, (persona, tag, method, path, answer.status_code)
        assert _snapshot(db) == before, (persona, tag)


@pytest.mark.parametrize("persona", list(OPENS))
def test_each_write_route_works_in_the_callers_own_places(web, persona):
    """The positive twin: what the caller may open they can change, and what they file lands under that assessment."""
    db = web.world.db
    for tag in sorted(OPENS[persona]):
        rows = web.rows[tag]
        edit = web("put", f"/orm/api/aims/{rows.assessment}", name=persona, json={"title": "Edited", "status": "completed"})
        assert edit.status_code == 200, (persona, tag)
        assert _value(db, "aims_assessments", rows.assessment, "title") == "Edited"
        risk = web("post", f"/orm/api/aims/{rows.assessment}/risks", name=persona, json={"risk_description": "Filed risk"})
        assert risk.status_code == 201, (persona, tag)
        assert _value(db, "aims_risks", risk.json()["id"], "assessment_id") == rows.assessment
        edit = web("put", f"/orm/api/aims/risks/{rows.risk}", name=persona, json={"risk_description": "Edited risk"})
        assert edit.status_code == 200, (persona, tag)
        assert _value(db, "aims_risks", rows.risk, "risk_description") == "Edited risk"
        link = web("post", f"/orm/api/aims/risks/{rows.risk}/controls", name=persona, json={"control_detail": "Filed control", "ice_score": 90})
        assert link.status_code == 201, (persona, tag)
        assert _value(db, "aims_risk_controls", link.json()["id"], "risk_id") == rows.risk
        edit = web("put", f"/orm/api/aims/controls/{rows.link}", name=persona, json={"control_detail": "Edited control"})
        assert edit.status_code == 200, (persona, tag)
        assert _value(db, "aims_risk_controls", rows.link, "control_detail") == "Edited control"
        for path, table, row_id in ((f"/orm/api/aims/controls/{rows.link}", "aims_risk_controls", rows.link),
                                    (f"/orm/api/aims/risks/{rows.risk}", "aims_risks", rows.risk),
                                    (f"/orm/api/aims/{rows.assessment}", "aims_assessments", rows.assessment)):
            assert web("delete", path, name=persona).status_code == 200, (persona, tag, path)
            assert not _exists(db, table, row_id), (persona, tag, path)


# ── The reads follow the same rule ──────────────────────────────────────────

@pytest.mark.parametrize("persona", list(OPENS))
def test_the_reads_of_an_assessment_open_only_for_those_who_may_open_its_unit(web, persona):
    for tag, rows in web.rows.items():
        for path in _reads(rows):
            answer = web("get", path, name=persona)
            assert answer.status_code == (200 if tag in OPENS[persona] else 404), (persona, tag, path, answer.status_code)


# ── Nobody can tell another unit's row from one that is not there ───────────

def test_an_id_in_another_unit_answers_exactly_like_an_id_that_does_not_exist(web):
    """Same status, same body, on every read and every write: the answer never confirms that the other unit's row exists."""
    nowhere = types.SimpleNamespace(assessment=987654, risk=987654, link=987654)

    def routes(rows):
        return [("get", path, None) for path in _reads(rows)] + _writes(rows)

    for (method, path, body), (_, missing_path, _) in zip(routes(web.rows["B"]), routes(nowhere)):
        foreign = web(method, path, name="owner_a", json=body)
        missing = web(method, missing_path, name="owner_a", json=body)
        assert foreign.status_code == missing.status_code == 404, (method, path)
        assert foreign.json() == missing.json(), (method, path)


# ── What stays as it was ────────────────────────────────────────────────────

@pytest.mark.parametrize("persona", ["dpo_a", "employee_a"])
def test_a_role_without_the_manage_capability_is_still_refused_in_its_own_unit(web, persona):
    db = web.world.db
    before = _snapshot(db)
    for method, path, body in _writes(web.rows["A"]):
        assert web(method, path, name=persona, json=body).status_code == 403, (persona, method, path)
    assert _snapshot(db) == before


def test_an_organization_without_the_operations_risk_licence_reaches_no_assessment_through_the_write_routes(web):
    """The write routes ask only for the manage capability, which does not look at the licence; the unit rule does."""
    db = web.world.db
    before = _snapshot(db)
    for method, path, body in _writes(web.rows["A"]):
        assert web(method, path, name="owner_a_unlicensed", json=body).status_code == 404, (method, path)
    assert _snapshot(db) == before


def test_a_risk_and_a_control_link_stay_under_the_assessment_they_were_filed_under(web):
    """The unit rule reads the parent once, so a body must not be able to move a row under another unit's assessment."""
    db, mine, theirs = web.world.db, web.rows["A"], web.rows["B"]
    edit = web("put", f"/orm/api/aims/risks/{mine.risk}", name="owner_a", json={"assessment_id": theirs.assessment, "risk_description": "Edited"})
    assert edit.status_code == 200
    assert _value(db, "aims_risks", mine.risk, "assessment_id") == mine.assessment
    edit = web("put", f"/orm/api/aims/controls/{mine.link}", name="owner_a", json={"risk_id": theirs.risk, "control_detail": "Edited"})
    assert edit.status_code == 200
    assert _value(db, "aims_risk_controls", mine.link, "risk_id") == mine.risk


# ── The unit a body names ───────────────────────────────────────────────────

def _count(db):
    return db.execute("SELECT COUNT(*) FROM aims_assessments").fetchone()[0]


def test_a_body_cannot_file_an_assessment_under_a_unit_the_writer_cannot_open(web):
    """Before this, any manager could plant an assessment in another unit's list just by naming it."""
    db, unit = web.world.db, web.world.unit
    total = _count(db)
    for bad in (unit["B"], str(unit["B"]), "abc", 0, -1, True, 1.5, [unit["A"]]):
        answer = web("post", "/orm/api/aims", name="owner_a", json={"title": "Planted", "business_unit_id": bad})
        assert answer.status_code == 400, repr(bad)
    assert _count(db) == total, "a refused create left no row behind"
    # A child unit is inside the scope, and a form sends the number as text.
    child = web("post", "/orm/api/aims", name="owner_a", json={"title": "Mine", "business_unit_id": str(unit["A1"])})
    assert child.status_code == 201
    assert _value(db, "aims_assessments", child.json()["id"], "business_unit_id") == unit["A1"], "stored as a number"
    own = web("post", "/orm/api/aims", name="owner_a", json={"title": "Mine", "business_unit_id": unit["A"]})
    assert own.status_code == 201 and _value(db, "aims_assessments", own.json()["id"], "business_unit_id") == unit["A"]


def test_a_body_that_names_no_unit_files_the_assessment_under_the_authors_unit(web):
    """The page sends no unit, so a new assessment takes its author's unit. Asking for organization wide is for administrators."""
    db, unit = web.world.db, web.world.unit
    made = web("post", "/orm/api/aims", name="owner_a", json={"title": "From the page"})
    assert made.status_code == 201
    assert _exists(db, "aims_assessments", made.json()["id"])
    assert _value(db, "aims_assessments", made.json()["id"], "business_unit_id") == unit["A"]
    total = _count(db)
    for empty in (None, ""):
        refused = web("post", "/orm/api/aims", name="owner_a", json={"title": "Wide", "business_unit_id": empty})
        assert refused.status_code == 400, repr(empty)
    assert _count(db) == total


def test_an_assessment_moves_only_inside_the_writers_units(web):
    db, unit, mine = web.world.db, web.world.unit, web.rows["A"]
    before = _snapshot(db)
    refused = web("put", f"/orm/api/aims/{mine.assessment}", name="owner_a", json={"title": "Moved", "business_unit_id": unit["B"]})
    assert refused.status_code == 400
    assert _snapshot(db) == before, "a refused edit changed nothing, not even the title"
    moved = web("put", f"/orm/api/aims/{mine.assessment}", name="owner_a", json={"business_unit_id": str(unit["A1"])})
    assert moved.status_code == 200
    assert _value(db, "aims_assessments", mine.assessment, "business_unit_id") == unit["A1"], "stored as a number"
    assert web("put", f"/orm/api/aims/{mine.assessment}", name="owner_a", json={"business_unit_id": unit["B"]}).status_code == 400
    assert _value(db, "aims_assessments", mine.assessment, "business_unit_id") == unit["A1"]
    assert web("put", f"/orm/api/aims/{mine.assessment}", name="super", json={"business_unit_id": unit["B"]}).status_code == 200
    assert _value(db, "aims_assessments", mine.assessment, "business_unit_id") == unit["B"], "an administrator is not confined"


def test_only_an_administrator_makes_an_assessment_organization_wide(web):
    db, unit, mine, shared = web.world.db, web.world.unit, web.rows["A"], web.rows["org"]
    for empty in (None, ""):
        refused = web("put", f"/orm/api/aims/{mine.assessment}", name="owner_a", json={"title": "Widened", "business_unit_id": empty})
        assert refused.status_code == 400, repr(empty)
    assert _value(db, "aims_assessments", mine.assessment, "business_unit_id") == unit["A"]
    assert _value(db, "aims_assessments", mine.assessment, "title") == "Assessment A"
    # Nothing to widen on one that is organization wide already, and an administrator may do it.
    assert web("put", f"/orm/api/aims/{shared.assessment}", name="owner_none", json={"business_unit_id": None}).status_code == 200
    assert web("put", f"/orm/api/aims/{mine.assessment}", name="super", json={"business_unit_id": None}).status_code == 200
    assert _value(db, "aims_assessments", mine.assessment, "business_unit_id") is None


def test_a_person_with_no_unit_files_nothing_and_never_under_the_no_unit_marker(web):
    """bu_scope_ids answers [-1] for someone with no unit; that marker must not become a unit a row can be filed under."""
    db, unit = web.world.db, web.world.unit
    total = _count(db)
    for bad in (unit["A"], unit["B"], -1):
        answer = web("post", "/orm/api/aims", name="owner_none", json={"title": "Planted", "business_unit_id": bad})
        assert answer.status_code == 400, bad
    assert _count(db) == total
    # Someone with no unit has no unit to default to, and only an administrator makes an assessment organization wide.
    assert web("post", "/orm/api/aims", name="owner_none", json={"title": "Shared"}).status_code == 400
    assert _count(db) == total


def test_an_administrator_must_still_name_a_real_unit_number(web):
    db, unit = web.world.db, web.world.unit
    total = _count(db)
    for bad in ("abc", 0, -1, True, 2.5):
        assert web("post", "/orm/api/aims", name="super", json={"title": "x", "business_unit_id": bad}).status_code == 400, repr(bad)
    assert _count(db) == total
    made = web("post", "/orm/api/aims", name="super", json={"title": "Anywhere", "business_unit_id": unit["B"]})
    assert made.status_code == 201 and _value(db, "aims_assessments", made.json()["id"], "business_unit_id") == unit["B"]


def test_the_unit_rule_comes_after_the_rule_that_the_assessment_exists_for_the_caller(web):
    """A bad unit on another unit's assessment answers 404 like any other write to it, so the 400 never confirms that it exists."""
    theirs = web.rows["B"]
    for body in ({"business_unit_id": web.world.unit["B"]}, {"business_unit_id": "abc"}, {"business_unit_id": None}):
        foreign = web("put", f"/orm/api/aims/{theirs.assessment}", name="owner_a", json=body)
        missing = web("put", "/orm/api/aims/987654", name="owner_a", json=body)
        assert foreign.status_code == missing.status_code == 404, body
        assert foreign.json() == missing.json(), body
