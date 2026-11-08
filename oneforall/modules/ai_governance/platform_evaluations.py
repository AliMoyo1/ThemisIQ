"""Bounded, provider-free checks of ThemisIQ's own AI feature contracts.

Two fixture sets exist. Every registered feature has the AI policy refusal set: with synthetic policies it checks that
the feature cannot send data when the organization's policy is off, was never approved by a named manager, is unreadable,
names another provider, switches the feature off or leaves out a kind of data the feature declares. Ask ARIA also has
the citation identity set. Neither set grades prose, runs a provider, reads a tenant or evaluates a customer's AI
application; what a model would answer is recorded as not measured.
"""

import hashlib
import inspect
import json

from core import ai_policy
from core.ai_declarations import DECLARATIONS
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import platform_features
from modules.ai_governance.service import ServiceError
from modules.aria import ask_service
from modules.aria.ask_grounding import _local_path, verified_citations

# Ask ARIA citation identity. The module-level names are read at call time, so changing one makes old runs stale.
TEST_SET = "aria.ask.citation-identity"
TEST_SET_VERSION = "1"
RUBRIC_VERSION = "1"

# AI policy refusal, for every registered feature.
POLICY_TEST_SET = "ai-policy.refusal"
POLICY_TEST_SET_VERSION = "1"
POLICY_RUBRIC_VERSION = "1"

NOT_MEASURED = "Model output: not measured. No provider was called and no answer was produced or graded."


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


def _policy_cases(feature_key):
    """(case, synthetic stored policy, provider asked for, expected refusal reason or None)."""
    approved = {"enabled": True, "providers": ["anthropic"], "categories": list(ai_policy.CATEGORIES),
                "blocked_features": [], "approved_by": 1, "approved_at": "2026-01-01 00:00:00"}
    unapproved = {key: value for key, value in approved.items() if key not in ("approved_by", "approved_at")}
    cases = [
        ("allowed when the policy permits this provider, feature and data", approved, "anthropic", None),
        ("refused when AI is switched off", {**approved, "enabled": False}, "anthropic", "disabled"),
        ("refused when an enabled policy was never approved by a named manager", unapproved, "anthropic", "disabled"),
        ("refused for a provider the policy does not name", approved, "openai", "provider_not_allowed"),
        ("refused when this feature is switched off", {**approved, "blocked_features": [feature_key]},
         "anthropic", "feature_blocked"),
        ("refused when the stored policy is unreadable", {**approved, "providers": ["not-a-provider"]},
         "anthropic", "unreadable"),
    ]
    for category in ai_policy.FEATURES[feature_key][1]:
        cases.append((f"refused when {category} data is not allowed",
                      {**approved, "categories": [c for c in ai_policy.CATEGORIES if c != category]},
                      "anthropic", "category_not_allowed"))
    return cases


def _policy_decision(raw, provider, feature_key):
    """The decision core/ai_policy.authorize makes once it has read a stored policy, without the database."""
    try:
        policy = ai_policy._effective_policy(raw)
    except ValueError:
        return "unreadable"
    refusal = ai_policy._refusal(policy, 0, provider, feature_key, ai_policy.categories_for(feature_key))
    return refusal[0] if refusal else None


def execute_policy_set(feature_key):
    label, categories = ai_policy.FEATURES[feature_key]
    cases = [{"case": "declares what it sends and has a written declaration",
              "passed": (ai_policy.categories_for(feature_key) == tuple(categories) and
                         ai_policy.UNLABELLED not in categories and feature_key in DECLARATIONS)}]
    for name, raw, provider, expected in _policy_cases(feature_key):
        cases.append({"case": name, "passed": _policy_decision(raw, provider, feature_key) == expected})
    return {"source_hash": _policy_source_hash(feature_key), "checks_total": len(cases),
            "checks_failed": sum(not case["passed"] for case in cases), "cases": cases}


def _policy_source_hash(feature_key):
    checked_code = "\n".join(inspect.getsource(item) for item in (
        ai_policy._clean_policy, ai_policy._effective_policy, ai_policy._refusal, ai_policy.categories_for,
        _policy_cases, _policy_decision, execute_policy_set))
    declared = json.dumps([feature_key, list(ai_policy.FEATURES[feature_key][1]),
                           repr(DECLARATIONS.get(feature_key))])
    return hashlib.sha256((checked_code + "\n" + declared).encode("utf-8")).hexdigest()


def _sets():
    """test set -> what it is, which features it applies to, how to run it and its current identity."""
    return {
        TEST_SET: {
            "label": "Citation identity",
            "scope": "Synthetic citation contract only; no provider, tenant record or customer system was tested.",
            "applies": lambda key: key == "aria.ask",
            "execute": lambda key: execute_fixture_set(),
            "identity": lambda key: (_source_hash(), TEST_SET_VERSION, RUBRIC_VERSION),
        },
        POLICY_TEST_SET: {
            "label": "AI policy refusal",
            "scope": ("Synthetic AI policy decisions only; no provider, tenant record or customer system was tested. "
                      + NOT_MEASURED),
            "applies": lambda key: key in ai_policy.FEATURES,
            "execute": execute_policy_set,
            "identity": lambda key: (_policy_source_hash(key), POLICY_TEST_SET_VERSION, POLICY_RUBRIC_VERSION),
        },
    }


def _sets_for(feature_key):
    return [name for name, spec in _sets().items() if spec["applies"](feature_key)]


def _require_feature(db, user, feature_key):
    platform_features._require(user)
    platform_features._require_public(db)
    if not _sets_for(feature_key):
        raise ServiceError(404, "No executable fixture set is registered for this feature.")


def _stale(row):
    spec = _sets().get(row["test_set"])
    if not spec or not spec["applies"](row["feature_key"]):
        return True
    source_hash, version, rubric = spec["identity"](row["feature_key"])
    return (row["source_hash"] != source_hash or row["test_set_version"] != version or
            row["rubric_version"] != rubric)


def _present(row):
    return {"id": row["id"], "feature_key": row["feature_key"],
            "test_set": row["test_set"], "test_set_version": row["test_set_version"],
            "rubric_version": row["rubric_version"], "source_hash": row["source_hash"],
            "status": row["status"], "checks_total": row["checks_total"],
            "checks_failed": row["checks_failed"], "cases": json.loads(row["results_json"]),
            "run_by": row["run_by"], "ran_at": str(row["ran_at"]),
            "reviewed_by": row["reviewed_by"], "reviewed_at": str(row["reviewed_at"]) if row["reviewed_at"] else None,
            "review_outcome": row["review_outcome"], "version": row["version"], "stale": _stale(row)}


def run(db, user, feature_key, test_set=None):
    _require_feature(db, user, feature_key)
    available = _sets_for(feature_key)
    if test_set is None:
        test_set = available[0]
    if test_set not in available:
        raise ServiceError(422, "Choose a fixture set registered for this feature.")
    spec = _sets()[test_set]
    result = spec["execute"](feature_key)
    _hash, version, rubric = spec["identity"](feature_key)
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    status = "failed" if result["checks_failed"] else "passed"
    run_id = insert_returning_id(db,
        "INSERT INTO platform_ai_evaluation_runs "
        "(feature_key, test_set, test_set_version, rubric_version, source_hash, status, "
        "checks_total, checks_failed, results_json, run_by, ran_at, version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
        (feature_key, test_set, version, rubric, result["source_hash"], status,
         result["checks_total"], result["checks_failed"], json.dumps(result["cases"]), user["id"], now))
    row = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
    return {"run": _present(row),
            "audit": [("platform_feature_fixture_run", "platform_ai_feature", 0,
                       f"{feature_key} {test_set}: {status}")]}


def list_runs(db, user, feature_key):
    _require_feature(db, user, feature_key)
    rows = db.execute("SELECT * FROM platform_ai_evaluation_runs WHERE feature_key = %s "
                      "ORDER BY id DESC LIMIT 20", (feature_key,)).fetchall()
    sets = _sets()
    available = _sets_for(feature_key)
    return {"runs": [_present(row) for row in rows], "viewer_id": user["id"],
            "test_sets": [{"key": name, "label": sets[name]["label"], "scope": sets[name]["scope"]}
                          for name in available],
            "scope": " ".join(sets[name]["scope"] for name in available)}


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
    if _stale(row):
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
