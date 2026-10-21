"""
Sentinel write scope: a record is reached through its id only by someone whose business unit scope contains it.

The GET-by-id routes for RoPA, DPIA and breach checked the caller's unit, but the PUT and DELETE routes, the routes
that act on a record through another one (spawn a DPIA from a RoPA, link a RoPA to a DPIA, the AI endpoints that take
a record id) and the request bodies that name a unit, a RoPA or a DPIA did not. A data protection officer in one unit
could therefore change, delete or read another unit's record by guessing its id.

Every route that takes one of these ids now answers with the 404 a missing record gets, and a body that points
outside the writer's scope is a 400. Each "cannot" has a positive twin (the same persona does reach its own record),
so an empty answer cannot pass for isolation. Vendors, retention, training and the other kinds that have no business
unit column are organization wide today; one test pins that so scoping them later is a deliberate change.
"""
import itertools

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
import modules.sentinel.routes as routes
from tests.test_platform_ownership import _insert, world  # noqa: F401

_REF = itertools.count(1)


@pytest.fixture
def http(world, monkeypatch):
    who = {"name": "dpo_a"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    # What a route announces and the hourly AI allowance are not what is under test.
    monkeypatch.setattr(routes, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "check_ai_rate_limit", lambda uid: True)
    monkeypatch.setattr(routes, "record_ai_call", lambda uid: None)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(method, path, name="dpo_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.world = world
    return call


@pytest.fixture
def ai(monkeypatch):
    """The four model calls that take a record, replaced by fakes that note which record they were given."""
    import modules.sentinel.ai_service as ai_service
    asked = []

    def fake(name, answer):
        async def call(record, *args, **kwargs):
            asked.append(record["id"])
            return answer, None
        monkeypatch.setattr(ai_service, name, call)

    fake("ai_score_ropa", {"risk_score": "high", "rationale": "because", "dpia_required": True})
    fake("ai_generate_full_dpia", "A full DPIA")
    fake("ai_assess_breach", "A breach assessment")
    fake("ai_draft_dsr_response", "A reply")
    return asked


# ── Records, one seed per kind and unit tag (A, A1 under A, B, org = organization wide) ──────────────────────────

def _ropa(world, tag):
    return _insert(world.db, "sentinel_ropa", ref_number=f"ROPA-{tag}-{next(_REF)}",
                   processing_name=f"Activity {tag}", business_unit_id=world.unit[tag])


def _dpia(world, tag):
    return _insert(world.db, "sentinel_dpias", ref_number=f"DPIA-{tag}-{next(_REF)}",
                   title=f"Assessment {tag}", business_unit_id=world.unit[tag])


def _breach(world, tag):
    return world.rec[("breach", tag)]  # the world fixture already files one breach under each unit


def _dsr(world, tag):
    return _insert(world.db, "sentinel_dsr", ref_number=f"DSR-{tag}-{next(_REF)}",
                   requester_name=f"Requester {tag}", business_unit_id=world.unit[tag])


def _consent(world, tag):
    return _insert(world.db, "sentinel_consent", purpose=f"Newsletter {tag}", subject_name=f"Subject {tag}",
                   subject_email=f"subject.{tag.lower()}@example.test", business_unit_id=world.unit[tag])


def _lia(world, tag):
    """A balancing test has no unit of its own: it sits where its RoPA entry sits (organization wide for tag org)."""
    return _insert(world.db, "sentinel_lia", ropa_id=_ropa(world, tag), title=f"Balancing test {tag}")


def _flow(world, tag):
    return _insert(world.db, "sentinel_data_flows", ropa_id=_ropa(world, tag), name=f"Flow {tag}")


def _row(db, table, row_id):
    row = db.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,)).fetchone()
    return dict(row) if row else None


def _count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


#             route base                  table                  the column a PUT changes   seed(world, tag)
KINDS = {
    "ropa":     ("/sentinel/api/ropa",      "sentinel_ropa",       "processing_name",         _ropa),
    "dpia":     ("/sentinel/api/dpias",     "sentinel_dpias",      "title",                   _dpia),
    "breach":   ("/sentinel/api/breaches",  "sentinel_breaches",   "title",                   _breach),
    "dsr":      ("/sentinel/api/dsrs",      "sentinel_dsr",        "requester_name",          _dsr),
    "consent":  ("/sentinel/api/consent",   "sentinel_consent",    "purpose",                 _consent),
    "lia":      ("/sentinel/api/lia",       "sentinel_lia",        "title",                   _lia),
    "dataflow": ("/sentinel/api/dataflows", "sentinel_data_flows", "name",                    _flow),
}
every_kind = pytest.mark.parametrize("kind", list(KINDS))


def _attempts(column, foreign_unit):
    """Everything one can do to a record through its own id. The change also names a unit the caller is not in, so a
    route that validated the body before it looked the record up would answer 400 here and give itself away."""
    return (
        ("get", {}),
        ("put", {"json": {column: "Hijacked", "business_unit_id": foreign_unit}}),
        ("delete", {}),
    )


# ── The record itself ───────────────────────────────────────────────────────

@every_kind
def test_another_units_record_answers_like_a_missing_one_and_is_left_alone(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    theirs = seed(world, "B")
    before = _row(world.db, table, theirs)
    for method, kwargs in _attempts(column, world.unit["B"]):
        refused = http(method, f"{base}/{theirs}", **kwargs)
        missing = http(method, f"{base}/987654", **kwargs)
        assert refused.status_code == missing.status_code == 404, (kind, method)
        assert refused.json() == missing.json(), f"{kind} {method}: it must say nothing a missing record does not"
    assert _row(world.db, table, theirs) == before, "the refused change did not happen"


@every_kind
def test_a_record_in_the_callers_own_unit_can_be_read_changed_and_deleted(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    mine = seed(world, "A")
    assert http("get", f"{base}/{mine}").status_code == 200
    assert http("put", f"{base}/{mine}", json={column: "Renamed"}).status_code == 200
    assert _row(world.db, table, mine)[column] == "Renamed"
    assert http("delete", f"{base}/{mine}").status_code == 200
    assert _row(world.db, table, mine) is None
    assert http("get", f"{base}/{mine}").status_code == 404


@every_kind
def test_a_parent_unit_reaches_a_child_units_record_and_a_child_does_not_reach_the_parents(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    child, parent = seed(world, "A1"), seed(world, "A")
    before = _row(world.db, table, parent)
    for method, kwargs in _attempts(column, world.unit["B"]):
        assert http(method, f"{base}/{parent}", name="dpo_a1", **kwargs).status_code == 404, (kind, method)
    assert _row(world.db, table, parent) == before
    assert http("get", f"{base}/{child}", name="dpo_a").status_code == 200
    assert http("put", f"{base}/{child}", name="dpo_a", json={column: "By the parent unit"}).status_code == 200
    assert _row(world.db, table, child)[column] == "By the parent unit"
    assert http("delete", f"{base}/{child}", name="dpo_a").status_code == 200
    assert _row(world.db, table, child) is None


@every_kind
def test_an_organization_wide_record_is_open_to_every_unit(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    shared = seed(world, "org")
    for name in ("dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit"):
        assert http("get", f"{base}/{shared}", name=name).status_code == 200, (kind, name)
    assert http("put", f"{base}/{shared}", name="dpo_b", json={column: "Edited elsewhere"}).status_code == 200
    assert http("delete", f"{base}/{shared}", name="dpo_no_unit").status_code == 200
    assert _row(world.db, table, shared) is None


@every_kind
def test_someone_with_no_unit_reaches_only_organization_wide_records(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    theirs = seed(world, "A")
    before = _row(world.db, table, theirs)
    for method, kwargs in _attempts(column, world.unit["A"]):
        assert http(method, f"{base}/{theirs}", name="dpo_no_unit", **kwargs).status_code == 404, (kind, method)
    assert _row(world.db, table, theirs) == before


@every_kind
def test_the_super_administrator_reaches_every_unit(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    theirs = seed(world, "B")
    assert http("get", f"{base}/{theirs}", name="super").status_code == 200
    assert http("put", f"{base}/{theirs}", name="super", json={column: "By the administrator"}).status_code == 200
    assert _row(world.db, table, theirs)[column] == "By the administrator"
    assert http("delete", f"{base}/{theirs}", name="super").status_code == 200
    assert _row(world.db, table, theirs) is None


# ── Routes that act on a record through another one ─────────────────────────

def test_spawning_a_dpia_from_another_units_ropa_is_refused(http):
    world = http.world
    theirs, mine = _ropa(world, "B"), _ropa(world, "A")
    dpias, before = _count(world.db, "sentinel_dpias"), _row(world.db, "sentinel_ropa", theirs)
    assert http("post", f"/sentinel/api/ropa/{theirs}/spawn-dpia").status_code == 404
    assert http("post", "/sentinel/api/ropa/987654/spawn-dpia").status_code == 404
    assert _count(world.db, "sentinel_dpias") == dpias, "nothing was copied out of a record the caller cannot open"
    assert _row(world.db, "sentinel_ropa", theirs) == before
    made = http("post", f"/sentinel/api/ropa/{mine}/spawn-dpia")
    assert made.status_code == 201
    assert _row(world.db, "sentinel_ropa", mine)["dpia_id"] == made.json()["dpia_id"]


def test_linking_a_ropa_to_a_dpia_needs_both_to_be_in_the_callers_scope(http):
    world = http.world
    mine_dpia, theirs_dpia = _dpia(world, "A"), _dpia(world, "B")
    mine_ropa, theirs_ropa = _ropa(world, "A"), _ropa(world, "B")
    untouched = {(t, i): _row(world.db, t, i) for t, i in (
        ("sentinel_dpias", mine_dpia), ("sentinel_dpias", theirs_dpia),
        ("sentinel_ropa", mine_ropa), ("sentinel_ropa", theirs_ropa))}

    def link(dpia, ropa):
        return http("post", f"/sentinel/api/dpias/{dpia}/link-ropa", json={"ropa_id": ropa})

    for dpia, ropa in ((mine_dpia, theirs_ropa), (theirs_dpia, mine_ropa), (theirs_dpia, theirs_ropa),
                       (mine_dpia, 987654), (987654, mine_ropa)):
        assert link(dpia, ropa).status_code == 404, (dpia, ropa)
    for (table, row_id), row in untouched.items():
        assert _row(world.db, table, row_id) == row, "a refused link copied nothing and changed nothing"
    linked = link(mine_dpia, mine_ropa)
    assert linked.status_code == 200
    assert _row(world.db, "sentinel_dpias", mine_dpia)["ropa_id"] == mine_ropa
    assert _row(world.db, "sentinel_ropa", mine_ropa)["dpia_id"] == mine_dpia


@pytest.mark.parametrize("kind, path", [
    ("ropa", "/sentinel/api/ai/score-ropa/{id}"),
    ("dpia", "/sentinel/api/ai/generate/{id}"),
    ("breach", "/sentinel/api/ai/breach-impact/{id}"),
    ("dsr", "/sentinel/api/ai/dsr-draft/{id}"),
])
def test_the_ai_endpoints_do_not_hand_another_units_record_to_the_model(http, ai, kind, path):
    world = http.world
    _, table, _, seed = KINDS[kind]
    theirs, mine = seed(world, "B"), seed(world, "A")
    before = _row(world.db, table, theirs)
    assert http("post", path.format(id=theirs)).status_code == 404
    assert http("post", path.format(id=987654)).status_code == 404
    assert ai == [], "the record never reached the model"
    assert _row(world.db, table, theirs) == before
    assert http("post", path.format(id=mine)).status_code == 200
    assert ai == [mine]


# ── What a body may name ────────────────────────────────────────────────────

@every_kind
def test_a_body_cannot_file_a_record_under_a_unit_the_writer_does_not_belong_to(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    mine = seed(world, "A")
    before, total = _row(world.db, table, mine), _count(world.db, table)
    assert http("post", base, json={column: "New", "business_unit_id": world.unit["B"]}).status_code == 400, kind
    assert http("post", base, json={column: "New", "business_unit_id": "abc"}).status_code == 400, kind
    assert _count(world.db, table) == total, "a refused create left no row behind"
    assert http("put", f"{base}/{mine}", json={column: "Moved", "business_unit_id": world.unit["B"]}).status_code == 400
    assert _row(world.db, table, mine) == before
    # A child unit is inside the scope, and a form sends numbers as text.
    assert http("post", base, json={column: "New", "business_unit_id": world.unit["A1"]}).status_code == 201, kind
    assert http("put", f"{base}/{mine}", json={"business_unit_id": str(world.unit["A1"])}).status_code == 200, kind


@pytest.mark.parametrize("kind", ["dsr", "consent"])
def test_a_record_whose_unit_can_be_changed_moves_only_inside_the_writers_scope(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    mine = seed(world, "A")
    assert http("put", f"{base}/{mine}", json={"business_unit_id": str(world.unit["A1"])}).status_code == 200
    assert _row(world.db, table, mine)["business_unit_id"] == world.unit["A1"], "stored as a number"
    assert http("put", f"{base}/{mine}", json={"business_unit_id": world.unit["B"]}).status_code == 400
    assert _row(world.db, table, mine)["business_unit_id"] == world.unit["A1"]
    assert http("put", f"{base}/{mine}", name="super", json={"business_unit_id": world.unit["B"]}).status_code == 200
    assert _row(world.db, table, mine)["business_unit_id"] == world.unit["B"], "an administrator is not confined"


def test_a_record_can_only_point_at_a_ropa_or_dpia_the_writer_may_open(http):
    world = http.world
    mine_ropa, theirs_ropa = _ropa(world, "A"), _ropa(world, "B")
    mine_dpia, theirs_dpia = _dpia(world, "A"), _dpia(world, "B")
    lia = _insert(world.db, "sentinel_lia", title="A balancing test")
    flow = _insert(world.db, "sentinel_data_flows", name="A flow")

    # (route, record, column that names the target, the targets the writer may not name)
    writes = [
        (f"/sentinel/api/dpias/{mine_dpia}", "sentinel_dpias", mine_dpia, "ropa_id", [theirs_ropa, 987654, "abc"]),
        (f"/sentinel/api/ropa/{mine_ropa}", "sentinel_ropa", mine_ropa, "dpia_id", [theirs_dpia, 987654, "abc"]),
        (f"/sentinel/api/lia/{lia}", "sentinel_lia", lia, "ropa_id", [theirs_ropa, 987654, "abc"]),
        (f"/sentinel/api/dataflows/{flow}", "sentinel_data_flows", flow, "ropa_id", [theirs_ropa, 987654, "abc"]),
    ]
    for path, table, row_id, column, bad in writes:
        before = _row(world.db, table, row_id)
        for target in bad:
            assert http("put", path, json={column: target}).status_code == 400, (path, column, target)
        assert _row(world.db, table, row_id) == before, f"{path}: a refused update changed nothing"

    # Creating is held to the same rule, and nothing is left behind.
    creates = [
        ("/sentinel/api/dpias", "sentinel_dpias", {"title": "New"}, "ropa_id", theirs_ropa),
        ("/sentinel/api/ropa", "sentinel_ropa", {"processing_name": "New"}, "dpia_id", theirs_dpia),
        ("/sentinel/api/lia", "sentinel_lia", {"title": "New"}, "ropa_id", theirs_ropa),
        ("/sentinel/api/dataflows", "sentinel_data_flows", {"name": "New"}, "ropa_id", theirs_ropa),
    ]
    for path, table, body, column, target in creates:
        total = _count(world.db, table)
        assert http("post", path, json={**body, column: target}).status_code == 400, path
        assert _count(world.db, table) == total, path

    # The positive twins: a target in scope is accepted, a form sends it as text, and an empty value unlinks.
    assert http("put", f"/sentinel/api/dpias/{mine_dpia}", json={"ropa_id": str(mine_ropa)}).json()["ropa_id"] == mine_ropa
    assert http("put", f"/sentinel/api/dpias/{mine_dpia}", json={"ropa_id": ""}).json()["ropa_id"] is None
    assert http("put", f"/sentinel/api/lia/{lia}", json={"ropa_id": mine_ropa}).json()["ropa_id"] == mine_ropa
    assert http("put", f"/sentinel/api/ropa/{mine_ropa}", json={"dpia_id": mine_dpia}).json()["dpia_id"] == mine_dpia
    assert http("post", "/sentinel/api/dataflows", json={"name": "New", "ropa_id": mine_ropa}).status_code == 201


@pytest.mark.parametrize("kind", ["lia", "dataflow"])
def test_the_list_of_records_that_follow_a_ropa_leaves_out_another_units(http, kind):
    world = http.world
    base, _, column, seed = KINDS[kind]
    ids = {tag: seed(world, tag) for tag in ("A", "A1", "B", "org")}
    names = {name: {row[column] for row in http("get", base, name=name).json()}
             for name in ("super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit")}
    label = {"lia": "Balancing test", "dataflow": "Flow"}[kind]
    assert names["super"] == {f"{label} {tag}" for tag in ("A", "A1", "B", "org")}
    assert names["dpo_a"] == {f"{label} {tag}" for tag in ("A", "A1", "org")}, "a parent unit sees its child's"
    assert names["dpo_a1"] == {f"{label} {tag}" for tag in ("A1", "org")}, "a child does not see its parent's"
    assert names["dpo_b"] == {f"{label} {tag}" for tag in ("B", "org")}
    assert names["dpo_no_unit"] == {f"{label} org"}
    if kind == "lia":  # the filter by RoPA cannot be used to reach into another unit either
        theirs = world.db.execute("SELECT ropa_id FROM sentinel_lia WHERE id = %s", (ids["B"],)).fetchone()[0]
        assert http("get", f"{base}?ropa_id={theirs}").json() == []
        assert len(http("get", f"{base}?ropa_id={theirs}", name="dpo_b").json()) == 1


def test_a_dpia_made_about_a_units_ropa_stays_in_that_unit(http):
    """Otherwise the copy of a unit's RoPA entry would be organization wide, and would show the entry's name to every
    unit through the join. Whoever writes the request has no say in it: the unit is the RoPA entry's."""
    world = http.world
    mine, shared = _ropa(world, "A"), _ropa(world, "org")
    spawned = http("post", f"/sentinel/api/ropa/{mine}/spawn-dpia").json()["dpia_id"]
    by_hand = http("post", "/sentinel/api/dpias", json={"title": "By hand", "ropa_id": str(mine)}).json()["id"]
    for dpia in (spawned, by_hand):
        assert _row(world.db, "sentinel_dpias", dpia)["business_unit_id"] == world.unit["A"]
        assert http("get", f"/sentinel/api/dpias/{dpia}", name="dpo_a").status_code == 200
        assert http("get", f"/sentinel/api/dpias/{dpia}", name="dpo_b").status_code == 404
        assert http("get", f"/sentinel/api/dpias/{dpia}", name="dpo_no_unit").status_code == 404
    open_spawned = http("post", f"/sentinel/api/ropa/{shared}/spawn-dpia").json()["dpia_id"]
    unlinked = http("post", "/sentinel/api/dpias", json={"title": "No RoPA entry"}).json()["id"]
    chosen = http("post", "/sentinel/api/dpias", json={"title": "Chosen", "business_unit_id": world.unit["A1"]}).json()["id"]
    assert _row(world.db, "sentinel_dpias", open_spawned)["business_unit_id"] is None
    assert http("get", f"/sentinel/api/dpias/{open_spawned}", name="dpo_b").status_code == 200
    for dpia in (unlinked, chosen):
        assert _row(world.db, "sentinel_dpias", dpia)["business_unit_id"] == world.unit["A"]
        assert http("get", f"/sentinel/api/dpias/{dpia}", name="dpo_b").status_code == 404
        assert http("get", f"/sentinel/api/dpias/{dpia}", name="dpo_a").status_code == 200


@pytest.mark.parametrize("base,table,body", [
    ("/sentinel/api/ropa", "sentinel_ropa", {"processing_name": "New activity"}),
    ("/sentinel/api/dpias", "sentinel_dpias", {"title": "New assessment"}),
    ("/sentinel/api/breaches", "sentinel_breaches", {"title": "New incident"}),
])
def test_new_privacy_records_use_the_creators_unit_not_the_requested_unit(http, base, table, body):
    world = http.world
    made = http("post", base, json={**body, "business_unit_id": world.unit["A1"]})
    assert made.status_code == 201, made.text
    record_id = made.json()["id"]
    assert _row(world.db, table, record_id)["business_unit_id"] == world.unit["A"]
    assert http("get", f"{base}/{record_id}", name="dpo_a").status_code == 200
    assert http("get", f"{base}/{record_id}", name="dpo_b").status_code == 404
    assert http("get", f"{base}/{record_id}", name="dpo_no_unit").status_code == 404
    shared = http("post", base, name="super", json=body)
    assert shared.status_code == 201, shared.text
    assert _row(world.db, table, shared.json()["id"])["business_unit_id"] is None


def test_erm_generated_breach_uses_the_source_risks_unit_not_event_payload(world, monkeypatch):
    from core import event_handlers

    risk = _insert(world.db, "erm_enterprise_risks", title="Privacy risk",
                   business_unit_id=world.unit["B"])
    monkeypatch.setattr(event_handlers, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_handlers, "_notify_admins", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_handlers, "notify_connectors", lambda *args, **kwargs: None)
    event_handlers.erm_data_breach_risk_creates_sentinel_breach(
        "erm.risk.identified", "erm", "enterprise_risk", risk,
        {"title": "Privacy risk", "category": "privacy", "business_unit_id": world.unit["A"]},
        world.users["dpo_b"]["id"])
    row = world.db.execute("SELECT business_unit_id FROM sentinel_breaches WHERE title = %s",
                           ("Privacy risk",)).fetchone()
    assert row is not None and row["business_unit_id"] == world.unit["B"]
    before = world.db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0]
    event_handlers.erm_data_breach_risk_creates_sentinel_breach(
        "erm.risk.identified", "erm", "enterprise_risk", 987654,
        {"title": "Missing risk", "category": "privacy", "business_unit_id": world.unit["A"]},
        world.users["dpo_b"]["id"])
    assert world.db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0] == before


@pytest.mark.parametrize("kind", ["dsr", "consent"])
def test_only_an_administrator_can_make_a_units_record_organization_wide(http, kind):
    world = http.world
    base, table, column, seed = KINDS[kind]
    mine, shared = seed(world, "A"), seed(world, "org")
    for empty in (None, ""):
        refused = http("put", f"{base}/{mine}", json={column: "Widened", "business_unit_id": empty})
        assert refused.status_code == 400, (kind, empty)
    after = _row(world.db, table, mine)
    assert after["business_unit_id"] == world.unit["A"] and after[column] != "Widened"
    # Nothing to widen on a record that is organization wide already, and an administrator may do it.
    assert http("put", f"{base}/{shared}", name="dpo_no_unit", json={"business_unit_id": None}).status_code == 200
    assert http("put", f"{base}/{mine}", name="super", json={"business_unit_id": None}).status_code == 200
    assert _row(world.db, table, mine)["business_unit_id"] is None


def test_a_consent_record_is_filed_under_the_unit_of_whoever_recorded_it(http):
    """Consent records hold names and e-mail addresses, as DSRs do, and are filed the same way: under the creator's
    unit, whatever the request says. Rows from before the column existed have no unit and stay organization wide."""
    world = http.world
    filed = {}
    for name in ("dpo_a", "dpo_b", "dpo_no_unit"):
        answer = http("post", "/sentinel/api/consent", name=name,
                      json={"purpose": f"Recorded by {name}", "subject_name": "A Subject"})
        assert answer.status_code == 201, name
        filed[name] = answer.json()["id"]
    assert _row(world.db, "sentinel_consent", filed["dpo_a"])["business_unit_id"] == world.unit["A"]
    assert _row(world.db, "sentinel_consent", filed["dpo_b"])["business_unit_id"] == world.unit["B"]
    assert _row(world.db, "sentinel_consent", filed["dpo_no_unit"])["business_unit_id"] is None
    chosen = http("post", "/sentinel/api/consent", json={"purpose": "Chosen", "business_unit_id": world.unit["A1"]})
    assert _row(world.db, "sentinel_consent", chosen.json()["id"])["business_unit_id"] == world.unit["A"]

    # What each person is shown follows from that: their unit and the ones under it, plus what is organization wide.
    seen = {name: {row["id"] for row in http("get", "/sentinel/api/consent", name=name).json()}
            for name in ("super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit")}
    assert seen["super"] >= set(filed.values())
    assert filed["dpo_a"] in seen["dpo_a"] and filed["dpo_b"] not in seen["dpo_a"]
    assert filed["dpo_a"] not in seen["dpo_a1"] and filed["dpo_a"] not in seen["dpo_b"]
    assert filed["dpo_no_unit"] in seen["dpo_a"] | seen["dpo_a1"] | seen["dpo_b"] | seen["dpo_no_unit"]
    assert seen["dpo_no_unit"] == {filed["dpo_no_unit"]}


def test_a_unit_that_consent_records_name_cannot_be_deleted(http):
    """The unit delete guard lists every table with a foreign key to a business unit; consent joined the list."""
    import modules.governance.data_service as gov
    assert ("sentinel_consent", "business_unit_id") in gov._BU_REFERENCES
    world = http.world
    _consent(world, "B")
    assert gov.delete_business_unit(world.unit["B"]) is False
    assert world.db.execute("SELECT COUNT(*) FROM business_units WHERE id = %s", (world.unit["B"],)).fetchone()[0] == 1


def test_a_ropa_entry_cannot_be_deleted_while_something_would_be_left_pointing_at_nothing_or_shown_to_everyone(http):
    """Deleting a RoPA entry used to fail with a foreign key error (a 500) when a data flow named it, and with an
    LIA ON DELETE SET NULL moved the LIA to no RoPA entry at all, which is organization wide. For an entry that sits in
    a unit that would show the assessment to every unit, so the delete is refused until the LIA is dealt with."""
    world = http.world
    mine, shared = _ropa(world, "A"), _ropa(world, "org")
    lia = _insert(world.db, "sentinel_lia", ropa_id=mine, title="Balancing test")
    flow = _insert(world.db, "sentinel_data_flows", ropa_id=mine, name="Flow")
    refused = http("delete", f"/sentinel/api/ropa/{mine}")
    assert refused.status_code == 409 and "data flow" in refused.json()["detail"], refused.text
    assert _row(world.db, "sentinel_ropa", mine) is not None
    assert http("delete", f"/sentinel/api/dataflows/{flow}").status_code == 200

    refused = http("delete", f"/sentinel/api/ropa/{mine}")  # the assessment is what is left
    assert refused.status_code == 409 and "assessment" in refused.json()["detail"], refused.text
    assert _row(world.db, "sentinel_ropa", mine) is not None
    assert _row(world.db, "sentinel_lia", lia)["ropa_id"] == mine

    assert http("delete", f"/sentinel/api/lia/{lia}").status_code == 200
    assert http("delete", f"/sentinel/api/ropa/{mine}").status_code == 200
    assert _row(world.db, "sentinel_ropa", mine) is None

    # An entry that is organization wide shows nothing new when it goes: its LIAs were visible to everyone already.
    open_lia = _insert(world.db, "sentinel_lia", ropa_id=shared, title="Shared balancing test")
    assert http("delete", f"/sentinel/api/ropa/{shared}").status_code == 200
    assert _row(world.db, "sentinel_lia", open_lia)["ropa_id"] is None
    assert http("get", f"/sentinel/api/lia/{open_lia}", name="dpo_b").status_code == 200


# ── Kinds with no business unit stay organization wide ──────────────────────

@pytest.mark.parametrize("path, table, columns", [
    ("/sentinel/api/vendors", "sentinel_vendors", {"name": "Acme Hosting"}),
    ("/sentinel/api/retention", "sentinel_retention",
     {"category": "HR", "data_type": "Payroll", "retention_period": "7 years"}),
    ("/sentinel/api/training", "sentinel_training", {"title": "Awareness"}),
])
def test_kinds_with_no_business_unit_column_are_organization_wide(http, path, table, columns):
    """sentinel_vendors, sentinel_retention, sentinel_training and the other unit-less tables have no unit to be
    outside of, and the platform registry (governance/entity_scope.py) registers vendors the same way. If one of them
    gains a business_unit_id, this is the test to change on purpose."""
    world = http.world
    row = _insert(world.db, table, **columns)
    for name in ("dpo_a", "dpo_b", "dpo_no_unit"):
        assert http("get", f"{path}/{row}", name=name).status_code == 200, (path, name)
    assert http("put", f"{path}/{row}", name="dpo_b", json={"notes": "Edited from another unit"}).status_code == 200
    assert _row(world.db, table, row)["notes"] == "Edited from another unit"
