"""An independent report decision must acknowledge unresolved frozen assurance."""
import modules.launcher.routes_reports as reports
from modules.launcher import report_snapshot as snap
from modules.launcher.scoped_metrics import run_scope_key
from tests.test_platform_ownership import _insert, _request, signed_in, world  # noqa: F401


def _response(coroutine):
    # The mocked auth and JSON body have no asynchronous I/O. Driving them to
    # completion directly avoids an unrelated Windows event-loop teardown stall.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("A test-only report decision unexpectedly awaited I/O")


def test_new_report_freezes_scoped_assurance_state(world):
    user = world.users["super"]
    env = reports._envelope(world.db, user, None, "Privacy review", "privacy_overview", {})
    assert env["assurance"]["state"] in {"measured", "partial", "not_measured"}
    assert env["assurance"]["scope_note"].startswith("Open issues in the author's accessible")
    text, digest = snap.encode(env)
    assert snap.intact(text, digest)


def test_approval_requires_review_of_open_or_partially_checked_issues(world, monkeypatch):
    author = world.users["dpo_a"]
    signer = world.users["super"]
    env = {"assurance": {"state": "partial", "open": 2, "as_of": "2026-11-05"}}
    text, digest = snap.encode(env)
    definition_id = _insert(world.db, "report_definitions", name="Review test", report_type="privacy_overview",
                            created_by=author["id"])
    run_id = _insert(world.db, "report_runs", definition_id=definition_id, status="completed",
                     triggered_by=run_scope_key(author), result_json=text, snapshot_hash=digest)
    world.db.commit()

    # Grant access to the independent signer for this narrow decision test;
    # the report share and scope gates are covered by the report-run tests.
    def open_run(db, user, requested_id, request, action):
        return dict(db.execute("SELECT * FROM report_runs WHERE id=%s", (requested_id,)).fetchone()), None

    monkeypatch.setattr(reports, "_open", open_run)
    monkeypatch.setattr(reports, "log_audit", lambda *args, **kwargs: None)
    body = {"decision": "approved", "reason": "Reviewed the available report and its gaps"}
    assert _response(reports.api_report_signoff(_request(signer, payload=body), run_id)).status_code == 400
    assert _response(reports.api_report_signoff(
        _request(signer, payload={**body, "assurance_reviewed": True}), run_id)).status_code == 201
    row = world.db.execute("SELECT assurance_reviewed FROM report_run_signoffs WHERE run_id=%s", (run_id,)).fetchone()
    assert row[0] == 1


def test_approval_refuses_assurance_that_was_not_measured(world, monkeypatch):
    author = world.users["dpo_a"]
    signer = world.users["super"]
    definition_id = _insert(world.db, "report_definitions", name="No assurance", report_type="privacy_overview",
                            created_by=author["id"])
    for state in ("not_measured", "not_authorized"):
        text, digest = snap.encode({"assurance": {"state": state, "open": None}})
        run_id = _insert(world.db, "report_runs", definition_id=definition_id, status="completed",
                         triggered_by=run_scope_key(author), result_json=text, snapshot_hash=digest)
        world.db.commit()
        monkeypatch.setattr(reports, "_open", lambda db, user, requested_id, request, action: (
            dict(db.execute("SELECT * FROM report_runs WHERE id=%s", (requested_id,)).fetchone()), None))
        response = _response(reports.api_report_signoff(_request(signer, payload={
            "decision": "approved", "reason": "Reviewed the report and all available assurance state",
            "assurance_reviewed": True}), run_id))
        assert response.status_code == 400
        assert world.db.execute("SELECT COUNT(*) FROM report_run_signoffs WHERE run_id=%s", (run_id,)).fetchone()[0] == 0
