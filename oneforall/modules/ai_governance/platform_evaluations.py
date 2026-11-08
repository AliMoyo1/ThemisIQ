"""Bounded, provider-free checks of ThemisIQ's own AI feature contracts.

The current set tests Ask ARIA citation identity only. It does not grade prose,
run a provider, read a tenant, or evaluate a customer's AI application.
"""

import hashlib
import inspect
import json

from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import platform_features
from modules.ai_governance.service import ServiceError
from modules.aria import ask_service
from modules.aria.ask_grounding import _local_path, verified_citations

TEST_SET = "aria.ask.citation-identity"
TEST_SET_VERSION = "1"
RUBRIC_VERSION = "1"
SUPPORTED = {"aria.ask"}


def _cases():
    source = {"content_type": "document", "title": "Synthetic policy",
              "section": "Access", "url_path": "/aria/documents/SYNTHETIC-1"}
    return (
        ("exact authorized source", [source], [source], True),
        ("fabricated title", [{**source, "title": "Other policy"}], [source], False),
        ("external URL", [{**source, "url_path": "https://example.invalid/policy"}], [source], False),
        ("missing citation", [], [source], False),
        ("mixed genuine and fabricated", [source, {**source, "title": "Other policy"}],
         [source, {**source, "title": "Second synthetic policy", "url_path": "/aria/documents/SYNTHETIC-2"}], False),
    )


def execute_fixture_set():
    """Execute fixed cases against production citation verification, no I/O."""
    cases = []
    for name, proposed, retrieved, expect_valid in _cases():
        actual = verified_citations(proposed, retrieved)
        passed = (actual is not None) == expect_valid
        cases.append({"case": name, "passed": passed})
    fingerprint = _source_hash()
    return {"source_hash": fingerprint, "checks_total": len(cases),
            "checks_failed": sum(not case["passed"] for case in cases), "cases": cases}


def _source_hash():
    checked_code = "\n".join(inspect.getsource(item) for item in
                             (ask_service.ask, _local_path, verified_citations, _cases))
    return hashlib.sha256(checked_code.encode("utf-8")).hexdigest()


def _require_feature(db, user, feature_key):
    platform_features._require(user)
    platform_features._require_public(db)
    if feature_key not in SUPPORTED:
        raise ServiceError(404, "No executable fixture set is registered for this feature.")


def _present(row):
    return {"id": row["id"], "feature_key": row["feature_key"],
            "test_set": row["test_set"], "test_set_version": row["test_set_version"],
            "rubric_version": row["rubric_version"], "source_hash": row["source_hash"],
            "status": row["status"], "checks_total": row["checks_total"],
            "checks_failed": row["checks_failed"], "cases": json.loads(row["results_json"]),
            "run_by": row["run_by"], "ran_at": str(row["ran_at"]),
            "reviewed_by": row["reviewed_by"], "reviewed_at": str(row["reviewed_at"]) if row["reviewed_at"] else None,
            "review_outcome": row["review_outcome"], "version": row["version"],
            "stale": (row["source_hash"] != _source_hash() or row["test_set"] != TEST_SET or
                      row["test_set_version"] != TEST_SET_VERSION or row["rubric_version"] != RUBRIC_VERSION)}


def run(db, user, feature_key):
    _require_feature(db, user, feature_key)
    result = execute_fixture_set()
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    status = "failed" if result["checks_failed"] else "passed"
    run_id = insert_returning_id(db,
        "INSERT INTO platform_ai_evaluation_runs "
        "(feature_key, test_set, test_set_version, rubric_version, source_hash, status, "
        "checks_total, checks_failed, results_json, run_by, ran_at, version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
        (feature_key, TEST_SET, TEST_SET_VERSION, RUBRIC_VERSION, result["source_hash"], status,
         result["checks_total"], result["checks_failed"], json.dumps(result["cases"]), user["id"], now))
    row = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
    return {"run": _present(row),
            "audit": [("platform_feature_fixture_run", "platform_ai_feature", 0, f"{feature_key}: {status}")]}


def list_runs(db, user, feature_key):
    _require_feature(db, user, feature_key)
    rows = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE feature_key = %s "
                      "ORDER BY id DESC LIMIT 20", (feature_key,)).fetchall()
    return {"runs": [_present(row) for row in rows], "viewer_id": user["id"],
            "scope": "Synthetic citation contract only; no provider, tenant record or customer system was tested."}


def review(db, user, feature_key, run_id, outcome, expected_version):
    _require_feature(db, user, feature_key)
    if outcome not in ("accepted", "finding"):
        raise ServiceError(422, "Choose accepted or finding.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
        raise ServiceError(422, "Send the current run version.")
    row = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE id = %s AND feature_key = %s",
                     (run_id, feature_key)).fetchone()
    if not row:
        raise ServiceError(404, "Run not found.")
    if row["review_outcome"] or row["version"] != expected_version:
        raise ServiceError(409, "This run changed. Reload it before reviewing.")
    if (row["source_hash"] != _source_hash() or row["test_set"] != TEST_SET or
            row["test_set_version"] != TEST_SET_VERSION or row["rubric_version"] != RUBRIC_VERSION):
        raise ServiceError(409, "The checked code or fixture set changed. Run the current checks first.")
    if row["run_by"] == user["id"]:
        raise ServiceError(403, "A different operator must review this run.")
    if outcome == "accepted" and row["status"] != "passed":
        raise ServiceError(409, "A failed run cannot be accepted.")
    if outcome == "finding" and row["status"] != "failed":
        raise ServiceError(409, "A passing run has no failed check to review as a finding.")
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    changed = db.execute("UPDATE platform_ai_evaluation_runs SET review_outcome = %s, reviewed_by = %s, "
                         "reviewed_at = %s, version = version + 1 WHERE id = %s AND feature_key = %s "
                         "AND review_outcome IS NULL AND version = %s",
                         (outcome, user["id"], now, run_id, feature_key, expected_version)).rowcount
    if changed != 1:
        raise ServiceError(409, "This run changed. Reload it before reviewing.")
    done = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
    return {"run": _present(done),
            "audit": [("platform_feature_fixture_reviewed", "platform_ai_feature", 0, f"{feature_key}: {outcome}")]}
