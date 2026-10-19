"""
AI governance G6a: the review pack through the service layer.

Written by hand. A preview stores nothing and is exactly what is issued; a pack is issued only to an eligible person of the
organization; the recipient reads a frozen account and every open is recorded; a revoked, expired, wrong-recipient,
issuer-lost-the-right or tampered pack answers like one that does not exist; names and notes are in it only when chosen;
and nobody outside the use's unit can list, revoke or read the history of a pack.
"""
import json

import pytest

import modules.ai_governance.handlers  # noqa: F401  (registers the event handlers)
from core import rbac
from modules.ai_governance import review_packs as packs
from modules.ai_governance import service
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def system(world, roles):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    org = user(world, "dpo_a")["org_id"]
    for number, name, role in ((50, "auditor", rbac.EXTERNAL_AUDITOR), (51, "auditor_two", rbac.AUDITOR)):
        _insert(world.db, "users", id=number, username=name, email=f"{name}@example.test", full_name=name, password_hash="x", org_id=org)
        world.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (number, role))
        world.users[name] = {"id": number, "username": name, "org_id": org, "business_unit_id": None, "is_super_admin": 0, "roles": [role]}
    world.db.commit()
    return world


def options(world, **changes):
    return {"name": "Q4 AI review", "recipient_id": user(world, "auditor")["id"], **changes}


def issue(world, who="dpo_a", **changes):
    opts = options(world, **changes)
    shown = packs.preview(world.db, user(world, who), world.app, opts)
    done = packs.issue(world.db, user(world, who), world.app, opts, shown["hash"])
    commit(world, done, user(world, who))
    return done["pack"], done


def events_of(world, pack_id):
    return [tuple(r) for r in world.db.execute(
        "SELECT action, reason, user_id FROM ai_review_pack_events WHERE pack_id = %s ORDER BY id", (pack_id,)).fetchall()]


def opened(world, pack_id, who="auditor", action="viewed"):
    result = packs.open_pack(world.db, user(world, who), pack_id, action)
    world.db.commit()
    return result


def section(manifest, key):
    return next(s for s in manifest["sections"] if s["key"] == key)


def all_lines(manifest):
    return [line for s in manifest["sections"] for i in s["items"] for line in i["lines"]]


def adopt(world, reason="Adopted after the legal review"):
    profile = service.get_profile(world.db, user(world, "dpo_a"), world.app)
    commit(world, service.adopt_tier(world.db, user(world, "dpo_a"), world.app, "moderate", reason, profile["version"]), user(world, "dpo_a"))


def edit_purpose(world, text):
    profile = service.get_profile(world.db, user(world, "dpo_a"), world.app)
    commit(world, service.update_profile(world.db, user(world, "dpo_a"), world.app, {"purpose": text}, profile["version"]),
           user(world, "dpo_a"))


# ── Preview ─────────────────────────────────────────────────────────────────

def test_a_preview_needs_the_right_and_a_use_the_caller_may_open_and_stores_nothing(system):
    for name, status in (("employee_a", 403), ("auditor", 403), ("dpo_b", 404)):
        fail(lambda n=name: packs.preview(system.db, user(system, n), system.app, options(system)), status)
    shown = packs.preview(system.db, user(system, "dpo_a"), system.app, options(system))
    assert shown["hash"] == packs.preview_hash(shown["manifest"], shown["options"]) and shown["problems"] == {}
    assert shown["recipient"]["name"] == "auditor"
    assert count(system, "ai_review_packs") == 0 and count(system, "ai_review_pack_events") == 0


def test_a_preview_names_what_is_still_missing_without_failing(system):
    shown = packs.preview(system.db, user(system, "dpo_a"), system.app, {"name": "ab"})
    assert set(shown["problems"]) == {"name", "recipient_id"} and shown["recipient"] is None


def test_the_preview_holds_the_use_the_decision_and_the_gaps_and_says_it_is_not_a_certificate(system):
    manifest = packs.preview(system.db, user(system, "dpo_a"), system.app, options(system))["manifest"]
    keys = [s["key"] for s in manifest["sections"]]
    assert keys[0] == "use" and keys[1] == "decision" and {"controls", "evaluations", "regulatory", "gaps", "exceptions"} <= set(keys)
    use = section(manifest, "use")["items"][0]
    assert use["title"] == "Ticket summarizer" and "Purpose: Summarize support tickets" in use["lines"]
    assert section(manifest, "decision")["items"][0]["title"] == "Decision: No decision"
    assert any(i["title"].startswith("Provider review is required") for i in section(manifest, "gaps")["items"])
    assert "not a certification" in manifest["disclaimer"] and manifest["application"] == {"name": "Ticket summarizer"}
    assert "id" not in manifest["application"], "no internal id leaves with the pack"
    assert "/ai-governance/" not in json.dumps(manifest), "links stay behind"


def test_names_and_notes_are_in_the_manifest_only_when_chosen(system):
    adopt(system)
    def lines(**choice):
        return all_lines(packs.preview(system.db, user(system, "dpo_a"), system.app, options(system, **choice))["manifest"])
    plain = lines()
    assert not any("employee_a" in l or "Adopted after the legal review" in l for l in plain)
    assert "Owner: employee_a" in lines(include_people=True)
    assert "Why this tier was adopted: Adopted after the legal review" in lines(include_notes=True)
    both = lines(include_people=True, include_notes=True)
    assert "Tier adopted by: dpo_a" in both and "Owner: employee_a" in both


def test_what_the_author_may_not_open_is_not_in_the_pack(system):
    for ref, title, unit in (("AIIA-S1", "Assessment in unit A", "A"), ("AIIA-S2", "Assessment in unit B", "B")):
        _insert(system.db, "sentinel_aiia", ref_number=ref, title=title, business_unit_id=system.unit[unit],
                application_id=system.app, status="draft")
    def titles(who):
        manifest = packs.preview(system.db, user(system, who), system.app, options(system))["manifest"]
        return [i["title"] for i in section(manifest, "ai_impact_assessments")["items"]]
    assert titles("dpo_a") == ["AIIA-S1: Assessment in unit A"], "unit B is not the author's to open"
    assert sorted(titles("super")) == ["AIIA-S1: Assessment in unit A", "AIIA-S2: Assessment in unit B"]


def test_a_source_that_fails_is_listed_as_not_shown_and_never_as_empty(system, monkeypatch):
    from modules.ai_governance import regulation

    def broken(*args, **kwargs):
        raise RuntimeError("the table is gone")
    monkeypatch.setattr(regulation, "confirmed_for", broken)
    manifest = packs.preview(system.db, user(system, "dpo_a"), system.app, options(system))["manifest"]
    shown = section(manifest, "regulatory")
    assert shown["state"] == "unavailable" and "could not be read" in shown["note"] and shown["items"] == []
    assert "Regulatory changes confirmed for this use" in manifest["summary"]["not_shown"]


# ── Issue ───────────────────────────────────────────────────────────────────

def test_issuing_needs_the_hash_that_was_previewed(system):
    opts = options(system)
    who = user(system, "dpo_a")
    shown = packs.preview(system.db, who, system.app, opts)
    for wrong in (None, "", "0" * 64, 7):
        error = fail(lambda w=wrong: packs.issue(system.db, who, system.app, opts, w), 409)
        assert error.extra["hash"] == shown["hash"]
    edit_purpose(system, "Changed after the preview")
    error = fail(lambda: packs.issue(system.db, who, system.app, opts, shown["hash"]), 409)
    assert error.extra["hash"] != shown["hash"]
    assert count(system, "ai_review_packs") == 0


def test_changing_the_recipient_or_sharing_choices_requires_a_new_preview(system):
    who = user(system, "dpo_a")
    original = options(system)
    shown = packs.preview(system.db, who, system.app, original)
    for changes in ({"recipient_id": user(system, "auditor_two")["id"]}, {"allow_download": True},
                    {"expires_days": 3}, {"name": "Another pack"}, {"purpose": "Different purpose"}):
        changed = {**original, **changes}
        error = fail(lambda c=changed: packs.issue(system.db, who, system.app, c, shown["hash"]), 409)
        assert error.extra["hash"] != shown["hash"]
    assert count(system, "ai_review_packs") == 0


def test_a_recipient_must_be_an_active_person_of_the_organization_who_can_receive_packs(system):
    who = user(system, "dpo_a")
    system.db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    stranger = _insert(system.db, "users", id=60, username="stranger", email="s@example.test", full_name="Stranger",
                       password_hash="x", org_id=2)
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (60, %s)", (rbac.EXTERNAL_AUDITOR,))
    gone = _insert(system.db, "users", id=61, username="gone", email="g@example.test", full_name="Gone", password_hash="x",
                   org_id=1, is_active=0)
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (61, %s)", (rbac.EXTERNAL_AUDITOR,))
    system.db.commit()
    for recipient in (stranger, gone, user(system, "employee_a")["id"], who["id"], 9999):
        opts = options(system, recipient_id=recipient)
        shown = packs.preview(system.db, who, system.app, opts)
        assert "recipient_id" in shown["problems"], recipient
        error = fail(lambda o=opts, h=shown["hash"]: packs.issue(system.db, who, system.app, o, h), 422)
        assert "recipient_id" in error.extra["errors"]
    assert count(system, "ai_review_packs") == 0


def test_issue_stores_a_frozen_pack_audits_it_and_tells_the_recipient(system):
    pack, done = issue(system, expires_days=14, purpose="Annual review")
    row = system.db.execute("SELECT * FROM ai_review_packs WHERE id = %s", (pack["id"],)).fetchone()
    assert row["status"] == "issued" and row["recipient_user_id"] == user(system, "auditor")["id"]
    assert row["application_id"] == system.app and row["business_unit_id"] == system.unit["A"]
    assert (row["allow_download"], row["include_people"], row["include_notes"]) == (0, 0, 0)
    assert packs.verifies(row["manifest"], row["manifest_hash"]) is not None
    assert pack["state"] == "open" and pack["expires_at"][:10] > pack["issued_at"][:10]
    assert done["audit"][0][0] == "ai_pack_issued" and done["events"]
    told = system.db.execute("SELECT user_id, message FROM notifications WHERE module = 'ai_governance' "
                             "AND title = 'A review pack was shared with you'").fetchall()
    assert [r[0] for r in told] == [user(system, "auditor")["id"]]
    assert "Q4 AI review" in told[0][1]


# ── Open ────────────────────────────────────────────────────────────────────

def test_the_recipient_reads_a_frozen_account_and_the_open_is_recorded(system):
    pack, _ = issue(system)
    first = opened(system, pack["id"])
    assert first["manager"] is False and first["manifest"]["hash"] == pack["hash"]
    assert set(first["pack"]) == {"id", "name", "purpose", "application_name", "issued_by", "issued_at", "expires_at",
                                  "allow_download", "hash", "generated_at"}, "a recipient sees what they need to read it"
    edit_purpose(system, "Changed after issue")
    again = opened(system, pack["id"])
    assert "Purpose: Summarize support tickets" in all_lines(again["manifest"]), "the pack is a snapshot"
    assert events_of(system, pack["id"]) == [("viewed", None, user(system, "auditor")["id"])] * 2


def test_everyone_else_is_refused_like_a_pack_that_is_not_there_and_it_is_recorded(system):
    pack, _ = issue(system)
    for who in ("employee_a", "dpo_b", "auditor_two"):
        assert opened(system, pack["id"], who) == {"refused": "wrong_recipient", "http": 404}, who
    assert opened(system, 987654) == {"refused": "not_found", "http": 404}
    assert [e[:2] for e in events_of(system, pack["id"])] == [("denied", "wrong_recipient")] * 3
    assert count(system, "ai_review_pack_events") == 3, "a pack that does not exist leaves no record"


def test_a_recipient_who_has_lost_the_right_to_receive_packs_is_refused(system):
    pack, _ = issue(system)
    system.db.execute("DELETE FROM user_roles WHERE user_id = %s", (user(system, "auditor")["id"],))
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (user(system, "auditor")["id"], rbac.EMPLOYEE))
    system.db.commit()
    system.users["auditor"]["roles"] = [rbac.EMPLOYEE]
    assert opened(system, pack["id"]) == {"refused": "no_right", "http": 404}


def test_a_revoked_pack_shows_nothing_and_is_no_longer_listed(system):
    pack, _ = issue(system)
    assert [p["id"] for p in packs.list_mine(system.db, user(system, "auditor"))["packs"]] == [pack["id"]]
    commit(system, packs.revoke(system.db, user(system, "dpo_a"), pack["id"], "Sent to the wrong person.", pack["version"]),
           user(system, "dpo_a"))
    assert opened(system, pack["id"]) == {"refused": "revoked", "http": 404}
    assert packs.list_mine(system.db, user(system, "auditor"))["packs"] == []
    assert opened(system, pack["id"], "dpo_a")["manager"] is True, "the people who manage it can still see what was issued"


def test_an_expired_pack_shows_nothing(system):
    pack, _ = issue(system)
    system.db.execute("UPDATE ai_review_packs SET expires_at = '2020-01-01 00:00:00' WHERE id = %s", (pack["id"],))
    system.db.commit()
    assert opened(system, pack["id"]) == {"refused": "expired", "http": 404}
    assert packs.list_mine(system.db, user(system, "auditor"))["packs"] == []


def test_the_pack_is_withdrawn_from_view_when_the_issuer_loses_the_right_to_share_it(system):
    pack, _ = issue(system)
    who = user(system, "dpo_a")["id"]
    system.db.execute("DELETE FROM user_roles WHERE user_id = %s", (who,))
    system.db.commit()
    assert opened(system, pack["id"]) == {"refused": "issuer_lost_right", "http": 404}
    assert packs.list_mine(system.db, user(system, "auditor"))["packs"] == []
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (who, rbac.DPO))
    system.db.execute("UPDATE users SET business_unit_id = %s WHERE id = %s", (system.unit["B"], who))
    system.db.commit()
    assert opened(system, pack["id"]) == {"refused": "issuer_lost_scope", "http": 404}
    system.db.execute("UPDATE users SET business_unit_id = %s, is_active = 0 WHERE id = %s", (system.unit["A"], who))
    system.db.commit()
    assert opened(system, pack["id"]) == {"refused": "issuer_gone", "http": 404}
    system.db.execute("UPDATE users SET is_active = 1 WHERE id = %s", (who,))
    system.db.commit()
    assert opened(system, pack["id"])["manifest"], "the right came back, so did the pack"


def test_recipient_list_checks_the_issuers_current_scope_for_each_ai_use(system):
    first, _ = issue(system)
    second_app = approve_new(system, submitted(system, answers={"name": "Second AI use"}))["application_id"]
    opts = options(system, name="Second review")
    preview = packs.preview(system.db, user(system, "dpo_a"), second_app, opts)
    second = packs.issue(system.db, user(system, "dpo_a"), second_app, opts, preview["hash"])["pack"]
    commit(system)
    def visible():
        return [p["id"] for p in packs.list_mine(system.db, user(system, "auditor"))["packs"]]
    assert visible() == [second["id"], first["id"]]
    system.db.execute("UPDATE applications SET business_unit_id = %s WHERE id = %s", (system.unit["B"], system.app))
    system.db.commit()
    assert visible() == [second["id"]], "a hidden older use must not inherit another use's access"
    system.db.execute("UPDATE applications SET business_unit_id = %s WHERE id = %s", (system.unit["A"], system.app))
    system.db.execute("UPDATE applications SET business_unit_id = %s WHERE id = %s", (system.unit["B"], second_app))
    system.db.commit()
    assert visible() == [first["id"]], "a visible older use must not inherit another use's denial"


def test_a_pack_that_no_longer_matches_its_recorded_hash_is_never_shown(system):
    pack, _ = issue(system)
    row = system.db.execute("SELECT manifest FROM ai_review_packs WHERE id = %s", (pack["id"],)).fetchone()
    system.db.execute("UPDATE ai_review_packs SET manifest = %s WHERE id = %s", (row["manifest"].replace("Summarize", "Resummarize"), pack["id"]))
    system.db.commit()
    assert packs.list_mine(system.db, user(system, "auditor"))["packs"] == []
    for who in ("auditor", "dpo_a"):
        assert opened(system, pack["id"], who) == {"refused": "integrity", "http": 404}, who
    assert [e[1] for e in events_of(system, pack["id"])] == ["integrity", "integrity"]


def test_a_download_follows_the_authors_choice(system):
    closed, _ = issue(system)
    assert opened(system, closed["id"], action="downloaded") == {"refused": "download_not_allowed", "http": 403}
    allowed, _ = issue(system, name="Q4 pack with download", allow_download=True)
    got = opened(system, allowed["id"], action="downloaded")
    document = packs.export_document(got)
    assert document["manifest"]["hash"] == allowed["hash"] and "sha256" in document["check"]
    assert ("downloaded", None, user(system, "auditor")["id"]) in events_of(system, allowed["id"])
    assert opened(system, closed["id"], "dpo_a", "downloaded")["manager"] is True, "the author may always export it"
    fail(lambda: packs.open_pack(system.db, user(system, "auditor"), allowed["id"], "printed"), 400)


# ── What the people who manage it see ───────────────────────────────────────

def test_the_manager_sees_who_opened_it_and_what_changed_since(system):
    pack, _ = issue(system)
    opened(system, pack["id"])
    listing = packs.list_for_application(system.db, user(system, "dpo_a"), system.app)["packs"]
    assert [(p["id"], p["opened"], p["recipient"], p["state"]) for p in listing] == [(pack["id"], 1, "auditor", "open")]
    history = packs.access_history(system.db, user(system, "dpo_a"), pack["id"])
    assert [(e["who"], e["action"]) for e in history["events"]] == [("auditor", "viewed")]
    assert packs.changes_since(system.db, user(system, "dpo_a"), pack["id"])["same"] is True
    edit_purpose(system, "Changed after issue")
    after = packs.changes_since(system.db, user(system, "dpo_a"), pack["id"])
    assert after["same"] is False and "The AI use" in after["changed"]


def test_nobody_outside_the_unit_or_without_the_right_can_list_revoke_or_read_the_history(system):
    pack, _ = issue(system)
    for who, status in (("dpo_b", 404), ("employee_a", 403), ("auditor", 403)):
        fail(lambda w=who: packs.revoke(system.db, user(system, w), pack["id"], "Because.", pack["version"]), status)
        fail(lambda w=who: packs.access_history(system.db, user(system, w), pack["id"]), status)
        fail(lambda w=who: packs.changes_since(system.db, user(system, w), pack["id"]), status)
    assert packs.list_for_application(system.db, user(system, "dpo_b"), system.app) is None
    fail(lambda: packs.list_for_application(system.db, user(system, "employee_a"), system.app), 403)


def test_revoking_needs_a_reason_and_the_current_version_and_happens_once(system):
    pack, _ = issue(system)
    who = user(system, "dpo_a")
    fail(lambda: packs.revoke(system.db, who, pack["id"], " ", pack["version"]), 422)
    fail(lambda: packs.revoke(system.db, who, pack["id"], "x" * 1001, pack["version"]), 422)
    fail(lambda: packs.revoke(system.db, who, pack["id"], "Because.", True), 400)
    fail(lambda: packs.revoke(system.db, who, pack["id"], "Because.", 7), 409)
    done = packs.revoke(system.db, who, pack["id"], "Sent to the wrong person.", pack["version"])
    commit(system, done, who)
    assert done["pack"]["state"] == "revoked" and done["pack"]["revoke_reason"] == "Sent to the wrong person."
    assert done["audit"][0][0] == "ai_pack_revoked"
    fail(lambda: packs.revoke(system.db, who, pack["id"], "Again.", pack["version"] + 1), 409)


def test_recipients_are_found_by_name_or_email_within_the_organization_and_only_when_they_can_receive(system):
    who = user(system, "dpo_a")
    system.db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    _insert(system.db, "users", id=60, username="aud_x", email="aud_x@example.test", full_name="aud_x", password_hash="x", org_id=2)
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (60, %s)", (rbac.EXTERNAL_AUDITOR,))
    _insert(system.db, "users", id=61, username="aud_off", email="aud_off@example.test", full_name="aud_off", password_hash="x",
            org_id=1, is_active=0)
    system.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (61, %s)", (rbac.EXTERNAL_AUDITOR,))
    system.db.commit()
    assert packs.find_recipients(system.db, who, "a") == [], "one character matches nothing"
    assert [p["name"] for p in packs.find_recipients(system.db, who, "aud")] == ["auditor", "auditor_two"], \
        "not the person in another organization, not the one who is switched off"
    assert [p["name"] for p in packs.find_recipients(system.db, who, "auditor_two@example")] == ["auditor_two"], "email matches too"
    assert packs.find_recipients(system.db, who, "employee") == [], "an employee cannot receive packs"
    assert [p["name"] for p in packs.find_recipients(system.db, who, "dpo")] == ["dpo_a1", "dpo_b", "dpo_no_unit"], "not the caller"
    fail(lambda: packs.find_recipients(system.db, user(system, "employee_a"), "aud"), 403)


def test_a_person_is_listed_only_their_own_open_packs(system):
    mine, _ = issue(system)
    other, _ = issue(system, name="For the second auditor", recipient_id=user(system, "auditor_two")["id"])
    assert [p["id"] for p in packs.list_mine(system.db, user(system, "auditor"))["packs"]] == [mine["id"]]
    assert [p["id"] for p in packs.list_mine(system.db, user(system, "auditor_two"))["packs"]] == [other["id"]]
    fail(lambda: packs.list_mine(system.db, user(system, "employee_a")), 403)
