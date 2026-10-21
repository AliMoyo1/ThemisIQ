import pathlib


def patch(path, edits):
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    s = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new in edits:
        assert s.count(old) == 1, (path, old[:70], s.count(old))
        s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print(path, "patched; crlf preserved:", crlf)


DDL = '''CREATE INDEX IF NOT EXISTS idx_ai_decision_conditions ON ai_use_decision_conditions(decision_id);

-- ── AI governance (G5): evaluation records and regulatory impact ────────────
-- A recorded evaluation run. ThemisIQ does not run the evaluation and keeps no prompts or answers: it keeps what was
-- evaluated, against what, by whom, the numbers, and a reading of them computed when the run was recorded.
CREATE TABLE IF NOT EXISTS ai_evaluation_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id    INTEGER NOT NULL REFERENCES applications(id),
    business_unit_id  INTEGER REFERENCES business_units(id),
    name              TEXT NOT NULL,
    test_set_name     TEXT,
    test_set_version  TEXT,
    rubric_version    TEXT,
    subject_version   TEXT NOT NULL,
    evaluator         TEXT NOT NULL,
    status            TEXT NOT NULL,
    result_state      TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    thresholds        TEXT,
    scores            TEXT,
    cases_total       INTEGER,
    cases_failed      INTEGER,
    retention         TEXT NOT NULL DEFAULT 'none',
    artifact_id       INTEGER,
    notes             TEXT,
    recorded_by       INTEGER REFERENCES users(id),
    recorded_at       TEXT,
    review_outcome    TEXT,
    reviewed_by       INTEGER REFERENCES users(id),
    reviewed_at       TEXT,
    review_note       TEXT,
    review_task_id    INTEGER,
    version           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_evaluation_application ON ai_evaluation_runs(application_id, recorded_at);

-- A change in the Regulatory Inbox proposed as relevant to an AI use, and what a person decided about it.
CREATE TABLE IF NOT EXISTS ai_regulatory_impacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    update_id           INTEGER NOT NULL REFERENCES regulatory_updates(id) ON DELETE CASCADE,
    application_id      INTEGER NOT NULL REFERENCES applications(id),
    business_unit_id    INTEGER REFERENCES business_units(id),
    status              TEXT NOT NULL DEFAULT 'candidate',
    basis               TEXT,
    update_fingerprint  TEXT,
    reviewed_by         INTEGER REFERENCES users(id),
    reviewed_at         TEXT,
    review_note         TEXT,
    task_id             INTEGER,
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    UNIQUE (update_id, application_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_regulatory_queue ON ai_regulatory_impacts(status, business_unit_id);
'''

p = pathlib.Path("database.py")
raw = p.read_bytes()
crlf = b"\r\n" in raw
s = raw.decode("utf-8").replace("\r\n", "\n")
anchor = "CREATE INDEX IF NOT EXISTS idx_ai_decision_conditions ON ai_use_decision_conditions(decision_id);\n"
assert s.count(anchor) == 2, s.count(anchor)
s = s.replace(anchor, DDL)
if crlf:
    s = s.replace("\n", "\r\n")
p.write_bytes(s.encode("utf-8"))
print("database.py patched; crlf preserved:", crlf)

patch("modules/governance/data_service.py", [
    ('"sentinel_consent", "ai_use_intake_requests", "ai_use_decisions",',
     '"sentinel_consent", "ai_use_intake_requests", "ai_use_decisions", "ai_evaluation_runs", "ai_regulatory_impacts",'),
])

patch("core/events.py", [
    ('''AI_DECISION_REVOKED     = "ai_use.decision_revoked"
''', '''AI_DECISION_REVOKED     = "ai_use.decision_revoked"
AI_REGULATORY_CONFIRMED = "ai_use.regulatory_confirmed"
'''),
])

patch("core/ai_policy.py", [
    ('''    "sentinel.ai_gap_analysis":            ("Cross-regulation gap analysis", ("business", "personal")),
}''', '''    "sentinel.ai_gap_analysis":            ("Cross-regulation gap analysis", ("business", "personal")),
    "governance.explain_ai_use":           ("Explain the status of an AI use", ("business",)),
}'''),
])

# ── decisions: signals from evaluations and regulatory changes reopen an approval ──
patch("modules/ai_governance/decisions.py", [
    ('''from modules.ai_governance import controls, guidance, quality, rules, service''',
     '''from modules.ai_governance import controls, evaluations, guidance, quality, regulation, rules, service'''),
    ('''def derive_state(standing, current, today, proof_expired=False, waiting=False) -> dict:''',
     '''def derive_state(standing, current, today, proof_expired=False, waiting=False, signals=()) -> dict:'''),
    ('''    if proof_expired:
        reasons.append("Proof the decision relied on has expired.")
    if reasons:''', '''    if proof_expired:
        reasons.append("Proof the decision relied on has expired.")
    reasons.extend(signals)
    if reasons:'''),
    ('''def _state_of(standing, current, today, waiting) -> dict:
    manifest = None''', '''def reopening_facts(db, application_id: int, decided_at) -> list:
    """What was recorded about a use after a decision was signed that reopens it. Names no record."""
    facts = []
    if evaluations.failed_since(db, application_id, decided_at):
        facts.append("An evaluation failed or did not finish after the decision was signed.")
    if regulation.confirmed_since(db, application_id, decided_at):
        facts.append("A regulatory change was confirmed for this use after the decision was signed.")
    return facts


def _state_of(standing, current, today, waiting, signals=()) -> dict:
    manifest = None'''),
    ('''        current, today, proof_expired=proof_expired_in(manifest, today), waiting=waiting)''',
     '''        current, today, proof_expired=proof_expired_in(manifest, today), waiting=waiting, signals=signals)'''),
    ('''    state = _state_of(standing, current, today, waiting=open_request is not None)''',
     '''    signals = reopening_facts(db, application_id, standing["decided_at"]) if standing is not None and standing["status"] in APPROVALS else ()
    state = _state_of(standing, current, today, waiting=open_request is not None, signals=signals)'''),
    ('''    re_reviews = []
    for r in standing:
        state = _state_of(r, profiles.get(r["application_id"], {"fingerprint": None, "tier": None}), today, False)''',
     '''    re_reviews = []
    for r in standing:
        state = _state_of(r, profiles.get(r["application_id"], {"fingerprint": None, "tier": None}), today, False,
                          signals=reopening_facts(db, r["application_id"], r["decided_at"]))'''),
])

# ── quality: a failed or stale evaluation is a check ────────────────────────
patch("modules/ai_governance/quality.py", [
    ('''    dismissed = _dismissals(db, application_id, today)''', '''    try:
        from modules.ai_governance import evaluations
        latest = (evaluations.list_runs(db, user, application_id) or {}).get("latest")
        if latest and latest["state"] in ("failed", "interrupted") and not latest["review_outcome"]:
            findings.append(_finding("evaluation_failed", "error", "evaluation", latest["id"],
                                     f"The latest evaluation, {latest['name']}, " + ("failed" if latest["state"] == "failed" else "did not finish"),
                                     "A run that failed or did not finish is not a pass, and nobody has reviewed it.",
                                     "Review the run", base + "#monitoring", {"state": latest["state"], "run": latest["id"]}))
        elif latest and latest["stale"]:
            findings.append(_finding("evaluation_stale", "warning", "evaluation", latest["id"],
                                     f"The latest evaluation, {latest['name']}, is out of date",
                                     "The use changed after it was run, or it is older than 180 days.",
                                     "Record a new evaluation", base + "#monitoring", {"run": latest["id"], "stale": True}))
    except Exception:
        log.warning("AI governance quality: evaluations could not be read", exc_info=True)
        unchecked.append("Evaluations")

    dismissed = _dismissals(db, application_id, today)'''),
])

# ── people are told ─────────────────────────────────────────────────────────
HANDLERS = '''

# ── Evaluations and regulatory changes ──────────────────────────────────────

@events.on(events.EVALUATION_FAILED)
def tell_about_failed_evaluation(*, payload=None, event_id=None, org_id=None, user_id=None, **kw):
    """A run failed or did not finish: the owner and the deciders hear once, whoever recorded it excepted."""
    db = get_db()
    try:
        data = payload or {}
        if not data.get("application_id"):
            return  # a platform level run names no application
        app = _application(db, data["application_id"])
        if app is None:
            return
        people = set(_holders(db, "ai_use.decide", app["business_unit_id"], org_id, exclude={user_id}))
        if app["owner_user_id"] is not None:
            people.add(app["owner_user_id"])
        word = "failed" if data.get("state") == "failed" else "did not finish"
        for person in people - {user_id}:
            _notify(db, event_id, person, "An AI evaluation did not pass", f"An evaluation of {app['name']} {word}.",
                    f"/ai-governance/systems/{app['id']}#monitoring")
        db.commit()
    finally:
        db.close()


@events.on(events.AI_REGULATORY_CONFIRMED)
def tell_owner_about_regulatory_change(*, payload=None, event_id=None, user_id=None, **kw):
    db = get_db()
    try:
        app = _application(db, (payload or {}).get("application_id"))
        if app is None or app["owner_user_id"] in (None, user_id):
            return
        _notify(db, event_id, app["owner_user_id"], "A regulatory change was confirmed for your AI use",
                f"{app['name']}: there is a task for it.", f"/ai-governance/systems/{app['id']}#monitoring")
        db.commit()
    finally:
        db.close()
'''
p = pathlib.Path("modules/ai_governance/handlers.py")
raw = p.read_bytes()
crlf = b"\r\n" in raw
s = raw.decode("utf-8").replace("\r\n", "\n").rstrip("\n") + "\n" + HANDLERS
if crlf:
    s = s.replace("\n", "\r\n")
p.write_bytes(s.encode("utf-8"))
print("handlers.py appended; crlf:", crlf)
