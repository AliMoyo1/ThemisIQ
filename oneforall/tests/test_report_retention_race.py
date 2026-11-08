"""A hold set after the purge scan must preserve the saved report."""

from modules.launcher import report_retention
from tests.test_platform_ownership import _insert, world  # noqa: F401


def test_new_hold_between_scan_and_delete_wins(world, monkeypatch):
    db = world.db
    definition = _insert(db, "report_definitions", name="Due report")
    run = _insert(db, "report_runs", definition_id=definition, status="completed",
                  result_json='{"summary":"kept"}', snapshot_hash="known-hash")
    _insert(db, "report_run_retention", run_id=run, delete_after="2020-01-01")
    db.commit()

    class HoldAfterScan:
        def execute(self, sql, params=()):
            result = db.execute(sql, params)
            if sql.startswith("SELECT r.run_id"):
                db.execute("UPDATE report_run_retention SET hold_reason='Legal hold' WHERE run_id=%s", (run,))
                db.commit()
            return result

        def __getattr__(self, key):
            if key == "close":
                return lambda: None
            return getattr(db, key)

    monkeypatch.setattr(report_retention, "get_db_background", lambda: HoldAfterScan())
    assert report_retention.purge_due(world.users["super"]["org_id"]) == 0
    saved = db.execute("SELECT status,result_json,snapshot_hash FROM report_runs WHERE id=%s", (run,)).fetchone()
    assert (saved["status"], saved["result_json"], saved["snapshot_hash"]) == (
        "completed", '{"summary":"kept"}', "known-hash")
