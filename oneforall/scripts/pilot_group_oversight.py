#!/usr/bin/env python3
"""Group oversight pilot (plan 23, P4; plan 19 acceptance): a synthetic parent and two subsidiaries on disposable data.

Three customer organizations are set up as the service sets up a customer: an organization record, a licence, its own
tenant schema on PostgreSQL, and its people with their roles (each customer's DPO named at user creation). Every person
then signs in through the real /login form with a second factor, and the group journey is walked through the real
application (every middleware, route and permission check) over HTTP:

  relationship proposed by the platform operator, acknowledged and DPO reviewed by each subsidiary; a subsidiary
  document released to the parent and found there; proof requested by requirement and accepted; a parent policy
  released to a subsidiary and an exception recorded; subsidiary figures (Vault claim figures included) published and
  read; a board pack issued; an external auditor's question answered in an audit room; a cited question over released
  documents; a new version filed and released again.

Between the steps it checks what must be refused: another tenant, another business unit, a person without a grant, a
revoked grant, a superseded version. Each step is timed (system time, not a person's).

Never point this at a real database. SQLite (default) uses a new temporary file. PostgreSQL needs PILOT_DATABASE_URL
naming a database whose name starts with themisiq_test_; after setup every request runs as an ordinary login role that
is subject to row level security (NOSUPERUSER, NOBYPASSRLS). No AI provider is called: the assistant is switched off.

Run from oneforall/:  python scripts/pilot_group_oversight.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PG_URL = os.environ.get("PILOT_DATABASE_URL", "")
if PG_URL and not urlsplit(PG_URL).path.lstrip("/").startswith("themisiq_test_"):
    sys.exit("PILOT_DATABASE_URL must name a throwaway database whose name starts with themisiq_test_")
os.environ["DATABASE_URL"] = PG_URL
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["EVIDENCE_DIR"] = tempfile.mkdtemp(prefix="pilot_evidence_")
os.environ["EVIDENCE_STAGING_DIR"] = tempfile.mkdtemp(prefix="pilot_staging_")
from cryptography.fernet import Fernet  # noqa: E402
os.environ["MFA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import pyotp  # noqa: E402

import database  # noqa: E402
from config import settings  # noqa: E402
from core import ai_client  # noqa: E402

ai_client.is_configured = lambda: False   # the pilot never sends text to a model provider
BASE = "https://pilot.themisiq.test"
PURPOSE = "Group governance"
PROBE_ROLE = "themisiq_pilot_probe"


def _when(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def _date(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


# ── set up three customers, as onboarding does ─────────────────────────────

ORGS = {"holdings": "Pilot Holdings", "mining": "Pilot Mining", "retail": "Pilot Retail"}
PEOPLE = {
    "holdings": {"admin": "org_admin", "dpo": "dpo", "cm": "compliance_manager", "grc": "grc_officer",
                 "audit": "audit_lead", "auditor": "external_auditor"},
    "mining": {"admin": "org_admin", "dpo": "dpo", "cm": "compliance_manager", "grc": "grc_officer",
               "unit_grc": "grc_officer"},
    "retail": {"admin": "org_admin", "dpo": "dpo", "cm": "compliance_manager", "grc": "grc_officer"},
}


def _insert(db, sql, params):
    return database.insert_returning_id(db, sql, params)


def setup(tag):
    world = {"orgs": {}, "people": {}, "password": "Pilot-" + secrets.token_urlsafe(12) + "-9a!"}
    from core.auth import hash_password
    hashed = hash_password(world["password"])
    db = database.get_db_bypass_rls()
    try:
        for key, name in ORGS.items():
            slug = f"pilot_{key}_{tag}"
            org = _insert(db, "INSERT INTO organizations (name, slug, plan, status) VALUES (%s,%s,'enterprise','active')",
                          (name, slug))
            db.execute("INSERT INTO licenses (org_id, module_keys, seats) VALUES (%s,'aria,bcm,erm,grid,orm,sentinel',50)",
                       (org,))
            world["orgs"][key] = {"id": org, "slug": slug}
        operator = _insert(db, "INSERT INTO users (username, email, full_name, password_hash, is_super_admin, is_active, "
                               "must_change_password) VALUES (%s,%s,'Platform operator',%s,1,1,0)",
                           (f"pilot_operator_{tag}", f"operator_{tag}@pilot.invalid", hashed))
        db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,'super_admin')", (operator,))
        world["people"]["operator"] = {"id": operator, "username": f"pilot_operator_{tag}", "org": None}
        for org_key, people in PEOPLE.items():
            for who, role in people.items():
                username = f"pilot_{org_key}_{who}_{tag}"
                uid = _insert(db, "INSERT INTO users (username, email, full_name, password_hash, org_id, is_active, "
                                  "must_change_password) VALUES (%s,%s,%s,%s,%s,1,0)",
                              (username, username + "@pilot.invalid", f"{ORGS[org_key]} {who}", hashed,
                               world["orgs"][org_key]["id"]))
                db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role))
                world["people"][f"{org_key}.{who}"] = {"id": uid, "username": username, "org": org_key}
        db.commit()
    finally:
        db.close()
    for key in ORGS:
        database.provision_tenant_schema(world["orgs"][key]["slug"])
    _seed_records(world)
    from core import mfa
    for person in world["people"].values():
        secret, _codes = mfa.start_enrollment(person["id"])
        step = int(time.time() // 30) - 1
        assert mfa.confirm_enrollment(person["id"], pyotp.TOTP(secret).at(step * 30)), "MFA enrollment failed"
        person["totp"] = secret
    return world


def _seed_records(world):
    """The records each customer already holds: files in its Vault, controls, a parent policy, a business unit."""
    from modules.governance.data_service import assign_user_business_unit, create_business_unit

    def in_org(key):
        org = world["orgs"][key]
        return database.tenant_context(org["id"], org["slug"], is_super_admin=True)

    def item(db, org_key, title, category, unit=None, text=None, policy_version=None):
        org = world["orgs"][org_key]["id"]
        digest = secrets.token_hex(32)
        eid = _insert(db, "INSERT INTO evidence_items (title, category, status, version, file_hash, file_name, org_id, "
                          "business_unit_id, aria_policy_version_id) VALUES (%s,%s,'current',1,%s,%s,%s,%s,%s)",
                      (title, category, digest, title.replace(" ", "_") + ".txt", org, unit, policy_version))
        if text:
            db.execute("INSERT INTO evidence_text_index (evidence_id, org_id, business_unit_id, file_hash, "
                       "indexer_version, status, content_text) VALUES (%s,%s,%s,%s,'pilot','indexed',%s)",
                       (eid, org, unit, digest, text))
        return eid

    with in_org("mining"):
        unit1 = create_business_unit({"name": "Mine one"})
        unit2 = create_business_unit({"name": "Mine two"})
        assign_user_business_unit(world["people"]["mining.unit_grc"]["id"], unit1)
        db = database.get_db()
        try:
            world["mining_doc"] = item(db, "mining", "Mining access control standard", "report", text=(
                "Access control standard. Access reviews are done every quarter by each system owner, and leavers "
                "lose access on their last working day."))
            world["mining_unit2_doc"] = item(db, "mining", "Mine two safety file", "report", unit=unit2)
            db.commit()
        finally:
            db.close()
    with in_org("retail"):
        db = database.get_db()
        try:
            framework = db.execute("SELECT id FROM frameworks ORDER BY id LIMIT 1").fetchone()[0]
            world["retail_control"] = _insert(
                db, "INSERT INTO controls (framework_id, ref, name, status) VALUES (%s,'R-AC-1',"
                    "'Quarterly access review','Implemented')", (framework,))
            world["retail_doc"] = item(db, "retail", "Retail access review Q3", "report")
            db.commit()
        finally:
            db.close()
    with in_org("holdings"):
        db = database.get_db()
        try:
            org = world["orgs"]["holdings"]["id"]
            document = _insert(db, "INSERT INTO aria_documents (doc_id, framework, title, org_id) VALUES "
                                   "('GRP-POL-1','ISO 27001','Group acceptable use policy',%s)", (org,))
            version = _insert(db, "INSERT INTO aria_policy_versions (org_id, document_id, version_major, version_minor, "
                                  "version, state, origin) VALUES (%s,%s,1,0,'1.0','approved','authored')",
                              (org, document))
            world["holdings_policy"] = item(db, "holdings", "Group acceptable use policy", "policy",
                                            policy_version=version)
            db.commit()
        finally:
            db.close()


def as_ordinary_role():
    """Every request after setup runs as a login role that row level security applies to, as the service's own does."""
    password = secrets.token_urlsafe(18)
    db = database.get_db_bypass_rls()
    try:
        db.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '" + PROBE_ROLE + "') THEN "
                   "CREATE ROLE " + PROBE_ROLE + " LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$")
        db.execute(f"ALTER ROLE {PROBE_ROLE} WITH LOGIN PASSWORD %s", (password,))
        for schema in [r[0] for r in db.execute("SELECT nspname FROM pg_namespace WHERE nspname = 'public' "
                                                "OR nspname LIKE 'tenant_%%'").fetchall()]:
            db.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {PROBE_ROLE}')
            db.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO {PROBE_ROLE}')
            db.execute(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO {PROBE_ROLE}')
        db.commit()
    finally:
        db.close()
    database._pg_pool.closeall()
    database._pg_pool = None
    parts = urlsplit(PG_URL)
    netloc = f"{PROBE_ROLE}:{password}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    settings.DATABASE_URL = urlunsplit(parts._replace(netloc=netloc))
    database._read_pg_password = lambda: ""
    check = database.get_db()
    try:
        row = check.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
        assert not row[0] and not row[1], "the pilot must run under row level security"
    finally:
        check.close()


# ── people signing in and working ──────────────────────────────────────────

class Person:
    def __init__(self, app, world, key):
        from starlette.testclient import TestClient
        self.key, self.info, self.password = key, world["people"][key], world["password"]
        self.client = TestClient(app, base_url=BASE, follow_redirects=False)

    @staticmethod
    def _csrf(html):
        found = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        assert found, "no CSRF field on the page"
        return found.group(1)

    def sign_in(self):
        page = self.client.get("/login")
        response = self.client.post("/login", data={"username": self.info["username"], "password": self.password,
                                                    "csrf_token": self._csrf(page.text)})
        assert response.status_code == 303 and response.headers["location"] == "/mfa/verify", response.text[:200]
        page = self.client.get("/mfa/verify")
        code = pyotp.TOTP(self.info["totp"]).now()
        response = self.client.post("/mfa/verify", data={"code": code, "csrf_token": self._csrf(page.text)})
        assert response.status_code == 303 and response.headers["location"] == "/", "second factor refused"
        return self

    def call(self, method, path, body=None):
        response = self.client.request(method, path, json=body, headers={"Accept": "application/json"})
        try:
            data = response.json()
        except ValueError:
            data = None
        return response.status_code, data


class Pilot:
    def __init__(self):
        self.steps = []

    def step(self, name, who, work):
        start = time.perf_counter()
        try:
            detail = work() or ""
            ok = True
        except Exception as failed:  # a crash in one step is a failed step, and the pilot goes on
            detail, ok = f"{type(failed).__name__}: {failed}", False
        self.steps.append({"step": name, "who": who, "ok": ok, "ms": round((time.perf_counter() - start) * 1000, 1),
                           "detail": str(detail)[:300]})
        return ok


def expect(result, *codes):
    status, data = result
    assert status in codes, f"HTTP {status} (wanted {codes}): {json.dumps(data)[:240] if data is not None else ''}"
    return data


def run(world):
    import main
    app = main.app
    p = {key: Person(app, world, key) for key in world["people"]}
    pilot = Pilot()
    o = world["orgs"]
    ids = {}

    pilot.step("Everyone signs in with a password and a second factor", f"all {len(p)} people",
               lambda: [person.sign_in() for person in p.values()] and f"{len(p)} sessions")

    from modules.governance import group_figures
    terms = {"data_classes": ["document_metadata"], "classifications": ["internal"],
             "audiences": ["grc_officer", "compliance_manager", "audit_lead", "dpo"],
             "fields": ["title", "category", "version", "source_name", "classification", "expires_at"],
             "jurisdictions": ["Zimbabwe"], "legal_basis": "Synthetic pilot agreement, not a real contract",
             "agreement_ref": "PILOT-ONLY-001", "figure_measures": list(group_figures.PUBLISHABLE), "issue_types": []}

    def propose():
        for child in ("mining", "retail"):
            ids[child] = expect(p["operator"].call("POST", "/evidence/api/group/relationships", {
                "parent_org_id": o["holdings"]["id"], "child_org_id": o[child]["id"], "purpose": PURPOSE,
                "terms": terms, "review_due_at": _when(180)}), 201)["id"]
        return f"relationships {ids['mining']} and {ids['retail']} proposed"
    pilot.step("The platform operator proposes both relationships", "operator", propose)

    pilot.step("A customer administrator cannot propose a relationship", "holdings.admin", lambda: expect(
        p["holdings.admin"].call("POST", "/evidence/api/group/relationships", {
            "parent_org_id": o["holdings"]["id"], "child_org_id": o["retail"]["id"], "purpose": PURPOSE,
            "terms": terms, "review_due_at": _when(180)}), 403, 404) and "refused")

    pilot.step("Another subsidiary's DPO cannot review Mining's terms", "retail.dpo", lambda: expect(
        p["retail.dpo"].call("POST", f"/evidence/api/group/relationships/{ids['mining']}/decisions",
                             {"kind": "privacy"}), 404) and "refused")

    def activate(child, legal):
        expect(p[f"{child}.admin"].call("POST", f"/evidence/api/group/relationships/{ids[child]}/decisions",
                                        {"kind": "ack"}), 200)
        expect(p[f"{child}.dpo"].call("POST", f"/evidence/api/group/relationships/{ids[child]}/decisions",
                                      {"kind": "privacy"}), 200)
        state = expect(p[legal].call("POST", f"/evidence/api/group/relationships/{ids[child]}/decisions",
                                     {"kind": "legal"}), 200)
        assert state["status"] == "active", state
        return "active"
    pilot.step("Mining acknowledges; its DPO records the privacy and legal reviews", "mining.admin, mining.dpo",
               lambda: activate("mining", "mining.dpo"))
    pilot.step("Retail acknowledges; its DPO and compliance manager review", "retail.admin, retail.dpo, retail.cm",
               lambda: activate("retail", "retail.cm"))

    def release(child, doc, rights_by="dpo", publisher="grc", relation=None):
        expect(p[f"{child}.{rights_by}"].call("POST", f"/evidence/api/group/rights/{doc}", {
            "rights_state": "owned", "permit_group_view": True, "permit_group_download": False,
            "basis": "Our own document, approved for group circulation"}), 200)
        return expect(p[f"{child}.{publisher}"].call(
            "POST", f"/evidence/api/group/relationships/{relation or ids[child]}/publications",
            {"evidence_id": doc, "classification": "internal", "purpose": PURPOSE, "expires_at": _when(90)}), 201)["id"]

    def mining_release():
        ids["mining_pub"] = release("mining", world["mining_doc"])
        return f"publication {ids['mining_pub']}"
    pilot.step("Mining's DPO approves the rights and its GRC officer releases a document", "mining.dpo, mining.grc",
               mining_release)

    pilot.step("A person confined to Mine one cannot release Mine two's file", "mining.unit_grc", lambda: expect(
        p["mining.unit_grc"].call("POST", f"/evidence/api/group/relationships/{ids['mining']}/publications", {
            "evidence_id": world["mining_unit2_doc"], "classification": "internal", "purpose": PURPOSE,
            "expires_at": _when(90)}), 404, 409) and "refused")

    def grants():
        for relation, cap in ((ids["mining"], "document.view"), (ids["mining"], "figure.view"),
                              (ids["retail"], "figure.view"), (ids["retail"], "document.view")):
            ids[f"grant_{relation}_{cap}"] = expect(p["holdings.admin"].call(
                "POST", f"/evidence/api/group/relationships/{relation}/grants", {
                    "user_id": world["people"]["holdings.grc"]["id"], "capability": cap,
                    "expires_at": _when(60), "review_due_at": _when(30)}), 201)["id"]
        return "4 named grants"
    pilot.step("Holdings' administrator grants its GRC officer named access", "holdings.admin", grants)

    def find_known():
        companies = expect(p["holdings.grc"].call("GET", "/evidence/api/group/companies"), 200)["companies"]
        mining = next(c for c in companies if c.get("name") == "Pilot Mining")
        listed = expect(p["holdings.grc"].call(
            "GET", f"/evidence/api/group/companies/{mining['id']}/publications"), 200)
        titles = [i["title"] for i in listed["items"]]
        assert titles == ["Mining access control standard"], titles
        opened = expect(p["holdings.grc"].call("GET", f"/evidence/api/group/publications/{ids['mining_pub']}"), 200)
        assert opened["source_name"] == "Pilot Mining", opened
        return f"found among {len(companies)} companies"
    pilot.step("Task: find a known subsidiary document", "holdings.grc", find_known)

    def no_grant_refused():
        for key in ("holdings.audit", "retail.grc", "holdings.auditor", "mining.unit_grc"):
            expect(p[key].call("GET", f"/evidence/api/group/publications/{ids['mining_pub']}"), 403, 404)
        return "4 refusals"
    pilot.step("Nobody without a named grant opens it (parent colleague, sibling, auditor)", "4 people",
               no_grant_refused)

    def ask():
        answer = expect(p["holdings.grc"].call("POST", "/evidence/api/group/ask",
                                               {"question": "How often are access reviews done?"}), 200)
        assert answer["state"] == "search_only" and answer["results"], answer
        assert "every quarter" in answer["results"][0]["text"], answer["results"][0]
        return "cited passage from Pilot Mining (assistant switched off)"
    pilot.step("A question over released documents returns the cited passage", "holdings.grc", ask)

    def request_proof():
        rid = expect(p["holdings.grc"].call("POST", f"/evidence/api/group/relationships/{ids['retail']}/requests", {
            "requirement_ref": "ISO 27001 A.5.18 access rights review", "purpose": "Year end assurance",
            "needed_by": _when(20)}), 201)["id"]
        ids["request"] = rid
        expect(p["retail.cm"].call("POST", f"/evidence/api/group/requests/{rid}/mapping", {
            "module": "aria", "entity_type": "control", "entity_id": world["retail_control"]}), 200)
        expect(p["retail.cm"].call("POST", f"/evidence/api/group/requests/{rid}/decisions", {
            "decision": "approved", "reason": "Our quarterly access review control covers this"}), 200)
        ids["retail_pub"] = release("retail", world["retail_doc"])
        expect(p["retail.grc"].call("POST", f"/evidence/api/group/requests/{rid}/fulfillment",
                                    {"publication_id": ids["retail_pub"]}), 200)
        stuck = expect(p["holdings.cm"].call("POST", f"/evidence/api/group/requests/{rid}/verdict", {
            "outcome": "accepted", "reason": "The Q3 review covers every system in scope"}), 409)
        assert "ask your administrator" in json.dumps(stuck), stuck
        expect(p["holdings.admin"].call("POST", f"/evidence/api/group/relationships/{ids['retail']}/grants", {
            "user_id": world["people"]["holdings.cm"]["id"], "capability": "document.view",
            "expires_at": _when(60), "review_due_at": _when(30)}), 201)
        verdict = expect(p["holdings.cm"].call("POST", f"/evidence/api/group/requests/{rid}/verdict", {
            "outcome": "accepted", "reason": "The Q3 review covers every system in scope"}), 200)
        assert verdict["status"] == "accepted", verdict
        return f"request {rid} accepted"
    pilot.step("Task: request unknown proof by requirement; the reviewer is told to get access, then accepts it",
               "holdings.grc, retail.cm, retail.grc, holdings.admin, holdings.cm", request_proof)

    def policy_exception():
        ids["policy_pub"] = release("holdings", world["holdings_policy"], relation=ids["mining"])
        for who in ("mining.grc", "mining.cm"):
            expect(p["mining.admin"].call("POST", f"/evidence/api/group/relationships/{ids['mining']}/grants", {
                "user_id": world["people"][who]["id"], "capability": "document.view",
                "expires_at": _when(60), "review_due_at": _when(30)}), 201)
        adoption = expect(p["mining.grc"].call("POST", f"/evidence/api/group/publications/{ids['policy_pub']}/adoptions", {
            "proposed_state": "exception_requested", "reason": "Underground sites have no network for the "
                                                               "screen lock rule; a local control replaces it",
            "review_due_at": _date(120)}), 201)["id"]
        state = expect(p["mining.cm"].call("POST", f"/evidence/api/group/adoptions/{adoption}/review", {
            "decision": "approve", "reason": "Checked against the local compensating control"}), 200)["status"]
        rollup = expect(p["holdings.grc"].call("GET", "/evidence/api/group/adoptions/rollup"), 200)
        text = json.dumps(rollup)
        assert "Pilot Mining" in text and "exception" in text, text[:300]
        assert "Underground" not in text, "the parent sees the outcome, not the subsidiary's reasons"
        return f"state {state}; parent rollup shows it"
    pilot.step("Task: record a child policy exception, and the parent sees the outcome", "holdings.dpo, holdings.grc, "
               "mining.admin, mining.grc, mining.cm", policy_exception)

    def figures():
        for child in ("mining", "retail"):
            written = expect(p["operator"].call("POST", "/governance/api/group/figures/publish",
                                                {"org_id": o[child]["id"]}), 200)["written"]
            assert written > 5, written
        view = expect(p["holdings.grc"].call("GET", f"/governance/api/group/figures?view=subsidiary"
                                                    f"&org_id={o['mining']['id']}"), 200)
        keys = {f["key"]: f for e in view["entities"] for f in e["figures"]}
        for key in ("vault.linked", "vault.current_proof", "vault.accepted"):
            assert key in keys, sorted(keys)[:12]
        group = expect(p["holdings.grc"].call("GET", "/governance/api/group/figures?view=group"), 200)
        names = sorted(e["name"] for e in group["entities"])
        assert {"Pilot Mining", "Pilot Retail"} <= set(names), names
        return f"{len(keys)} Mining figures, Vault claim figures included"
    pilot.step("Subsidiary figures are published and the parent reads them", "operator, holdings.grc", figures)

    pilot.step("A sibling cannot read Mining's figures", "retail.grc", lambda: expect(
        p["retail.grc"].call("GET", f"/governance/api/group/figures?view=subsidiary&org_id={o['mining']['id']}"),
        403, 404) and "refused")

    def pack():
        ids["pack"] = expect(p["holdings.grc"].call("POST", "/governance/api/group/packs", {
            "title": "Pilot board pack", "period": "Q4 2026"}), 201)["id"]
        expect(p["holdings.cm"].call("POST", f"/governance/api/group/packs/{ids['pack']}/review", {
            "decision": "issued", "note": "Checked against the published figures"}), 200)
        got = expect(p["holdings.grc"].call("GET", f"/governance/api/group/packs/{ids['pack']}"), 200)
        assert got["integrity"] == "passed", got.get("integrity_text")
        return f"pack {ids['pack']} issued, integrity check passed"
    pilot.step("A board pack is built and issued by a second person", "holdings.grc, holdings.cm", pack)

    def room():
        rid = expect(p["holdings.grc"].call("POST", "/governance/api/group/rooms", {
            "title": "Pilot year end audit", "auditor_user_id": world["people"]["holdings.auditor"]["id"],
            "starts_at": _when(-1)[:19], "ends_at": _when(30)[:19]}), 201)["id"]
        item = expect(p["holdings.grc"].call("POST", f"/governance/api/group/rooms/{rid}/items", {
            "kind": "pack", "ref_id": ids["pack"]}), 201)["id"]
        expect(p["holdings.audit"].call("POST", f"/governance/api/group/rooms/{rid}/decision", {
            "decision": "open", "reason": "Scope agreed with the audit firm"}), 200)
        expect(p["holdings.auditor"].call("GET", f"/governance/api/group/rooms/{rid}/items/{item}"), 200)
        question = expect(p["holdings.auditor"].call("POST", f"/governance/api/group/rooms/{rid}/messages", {
            "body": "How was the accepted proof share counted for Pilot Mining?"}), 201)["id"]
        expect(p["holdings.grc"].call("POST", f"/governance/api/group/rooms/{rid}/messages", {
            "body": "From Mining's own Vault: claims a second reviewer accepted, see the pack.",
            "reply_to": question, "cites": [item]}), 201)
        seen = expect(p["holdings.auditor"].call("GET", f"/governance/api/group/rooms/{rid}"), 200)
        kinds = [m["kind"] for m in seen["messages"]]
        assert kinds == ["question", "answer"], kinds
        expect(p["holdings.auditor"].call("GET", f"/governance/api/group/packs/{ids['pack']}"), 403, 404)
        ids["room"] = rid
        return f"room {rid}: question answered with a citation"
    pilot.step("Task: resolve an auditor question in an audit room", "holdings.grc, holdings.audit, "
               "holdings.auditor", room)

    def new_version():
        files = {"file": ("standard_v2.txt", b"Access control standard, version 2. Reviews every quarter.",
                          "text/plain")}
        data = {"title": "Mining access control standard", "category": "report", "replace_id": str(world["mining_doc"]),
                "filing_scope": "organization"}
        response = p["mining.grc"].client.post("/evidence/api/items", files=files, data=data,
                                              headers={"Accept": "application/json"})
        assert response.status_code in (200, 201), f"HTTP {response.status_code}: {response.text[:240]}"
        new_id = response.json().get("id")
        assert new_id and new_id != world["mining_doc"], response.text[:200]
        expect(p["holdings.grc"].call("GET", f"/evidence/api/group/publications/{ids['mining_pub']}"), 404)
        ids["mining_pub_v2"] = release("mining", new_id)
        opened = expect(p["holdings.grc"].call("GET", f"/evidence/api/group/publications/{ids['mining_pub_v2']}"), 200)
        assert opened["version"] == 2, opened
        return "the old release closed by itself; version 2 released and opened"
    pilot.step("Task: file a new version; the old release stops, the new one is released", "mining.grc, mining.dpo, "
               "holdings.grc", new_version)

    def revoke():
        grant = ids[f"grant_{ids['mining']}_document.view"]
        expect(p["holdings.admin"].call("DELETE", f"/evidence/api/group/grants/{grant}"), 200)
        expect(p["holdings.grc"].call("GET", f"/evidence/api/group/publications/{ids['mining_pub_v2']}"), 404)
        companies = expect(p["holdings.grc"].call("GET", "/evidence/api/group/companies"), 200)["companies"]
        assert "Pilot Mining" not in [c.get("name") for c in companies], companies
        return "access ended at once, in the same session"
    pilot.step("A revoked grant ends access at once", "holdings.admin, holdings.grc", revoke)

    def access_log():
        org = o["mining"]
        db = database.get_db_bypass_rls()
        try:
            rows = db.execute("SELECT action, COUNT(*) AS n FROM public.group_access_events WHERE source_org_id=%s "
                              "GROUP BY action ORDER BY action" if settings.is_postgres() else
                              "SELECT action, COUNT(*) AS n FROM group_access_events WHERE source_org_id=%s "
                              "GROUP BY action ORDER BY action", (org["id"],)).fetchall()
        finally:
            db.close()
        actions = {r["action"]: r["n"] for r in rows}
        assert actions.get("open"), actions
        return ", ".join(f"{k} {v}" for k, v in actions.items())
    pilot.step("Mining's access log records every parent read", "check", access_log)
    return pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json")
    args = parser.parse_args()
    if not PG_URL:
        database._DB_PATH = str(Path(tempfile.mkdtemp(prefix="pilot_")) / "pilot.db")
    database.init_db()
    world = setup(secrets.token_hex(3))
    if PG_URL:
        as_ordinary_role()
    engine = "PostgreSQL, a tenant schema per customer, ordinary role under row level security" if PG_URL else "SQLite"
    pilot = run(world)
    passed = sum(s["ok"] for s in pilot.steps)
    print(f"Group oversight pilot ({engine}): {passed} of {len(pilot.steps)} steps passed\n")
    print("| Step | Who | Result | ms |")
    print("|---|---|---|---|")
    for s in pilot.steps:
        print(f"| {s['step']} | {s['who']} | {'passed' if s['ok'] else 'FAILED'}: {s['detail']} | {s['ms']} |")
    if args.json:
        Path(args.json).write_text(json.dumps({"engine": engine, "steps": pilot.steps}, indent=2), encoding="utf-8")
    sys.exit(0 if passed == len(pilot.steps) else 1)


if __name__ == "__main__":
    main()
