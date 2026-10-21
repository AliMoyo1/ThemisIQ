"""G6 core wiring: DDL (both blocks), unit references, capabilities, events, notification handlers.

Run from oneforall/ after patch_g5_core.py (it anchors on the G5 index line)."""
import pathlib


def read(path):
    raw = pathlib.Path(path).read_bytes()
    return raw.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in raw


def write(path, text, crlf):
    pathlib.Path(path).write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print(path, "patched; crlf preserved:", crlf)


def patch(path, edits):
    s, crlf = read(path)
    for old, new in edits:
        assert s.count(old) == 1, (path, old[:80], s.count(old))
        s = s.replace(old, new)
    write(path, s, crlf)


TENANT_DDL = '''CREATE INDEX IF NOT EXISTS idx_ai_regulatory_queue ON ai_regulatory_impacts(status, business_unit_id);

-- ── AI governance (G6): review packs and AI literacy ────────────────────────
-- A frozen, named, read-only account of one AI use, issued to one signed-in person with an expiry. The manifest is the
-- account; its hash is checked on every open. People's names and free text are in it only when the author chose so.
CREATE TABLE IF NOT EXISTS ai_review_packs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id     INTEGER NOT NULL REFERENCES applications(id),
    application_name   TEXT NOT NULL,
    business_unit_id   INTEGER REFERENCES business_units(id),
    name               TEXT NOT NULL,
    purpose            TEXT,
    status             TEXT NOT NULL DEFAULT 'issued',
    recipient_user_id  INTEGER NOT NULL REFERENCES users(id),
    allow_download     INTEGER NOT NULL DEFAULT 0,
    include_people     INTEGER NOT NULL DEFAULT 0,
    include_notes      INTEGER NOT NULL DEFAULT 0,
    expires_at         TEXT NOT NULL,
    manifest           TEXT NOT NULL,
    manifest_hash      TEXT NOT NULL,
    generated_at       TEXT NOT NULL,
    issued_by          INTEGER REFERENCES users(id),
    issued_at          TEXT NOT NULL,
    revoked_by         INTEGER REFERENCES users(id),
    revoked_at         TEXT,
    revoke_reason      TEXT,
    version            INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_pack_application ON ai_review_packs(application_id, issued_at);
CREATE INDEX IF NOT EXISTS idx_ai_pack_recipient ON ai_review_packs(recipient_user_id, status);
CREATE TABLE IF NOT EXISTS ai_review_pack_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id     INTEGER NOT NULL REFERENCES ai_review_packs(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_pack_events ON ai_review_pack_events(pack_id, created_at);

-- A course in AI literacy. The working copy (body, questions, pass mark) is edited freely; publishing copies it into an
-- immutable version row, and a completion belongs to one version.
CREATE TABLE IF NOT EXISTS ai_literacy_courses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    summary            TEXT,
    body               TEXT,
    questions          TEXT,
    pass_mark          INTEGER,
    audience_roles     TEXT,
    audience_owners    INTEGER NOT NULL DEFAULT 0,
    business_unit_id   INTEGER REFERENCES business_units(id),
    renewal_months     INTEGER NOT NULL DEFAULT 12,
    due_days           INTEGER NOT NULL DEFAULT 30,
    status             TEXT NOT NULL DEFAULT 'draft',
    current_version    INTEGER NOT NULL DEFAULT 0,
    retake_from        INTEGER NOT NULL DEFAULT 0,
    published_at       TEXT,
    created_by         INTEGER REFERENCES users(id),
    version            INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ai_literacy_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id     INTEGER NOT NULL REFERENCES ai_literacy_courses(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    questions     TEXT,
    pass_mark     INTEGER,
    retake        INTEGER NOT NULL DEFAULT 1,
    published_by  INTEGER REFERENCES users(id),
    published_at  TEXT,
    UNIQUE (course_id, version)
);
CREATE TABLE IF NOT EXISTS ai_literacy_completions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id         INTEGER NOT NULL REFERENCES ai_literacy_courses(id) ON DELETE CASCADE,
    course_version    INTEGER NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    business_unit_id  INTEGER REFERENCES business_units(id),
    outcome           TEXT NOT NULL,
    score             INTEGER,
    completed_at      TEXT NOT NULL,
    expires_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_literacy_completions_user ON ai_literacy_completions(user_id, course_id);
'''

PLATFORM_ONLY_DDL = '''
-- The operator's notes on the platform's own AI features. The feature list itself comes from core/ai_policy.FEATURES; this
-- holds only what a person recorded about each. No customer prompt, answer or evidence is ever stored here.
CREATE TABLE IF NOT EXISTS platform_ai_features (
    feature_key        TEXT PRIMARY KEY,
    owner              TEXT,
    provider_note      TEXT,
    known_limitations  TEXT,
    incident_path      TEXT,
    deployment         TEXT NOT NULL DEFAULT 'in_service',
    review_due         TEXT,
    last_reviewed_at   TEXT,
    last_reviewed_by   INTEGER REFERENCES users(id),
    version            INTEGER NOT NULL DEFAULT 1,
    updated_at         TEXT DEFAULT (datetime('now'))
);
'''

s, crlf = read("database.py")
anchor = "CREATE INDEX IF NOT EXISTS idx_ai_regulatory_queue ON ai_regulatory_impacts(status, business_unit_id);\n"
assert s.count(anchor) == 2, s.count(anchor)
first = s.index(anchor)
s = s[:first] + TENANT_DDL + s[first + len(anchor):]
second = s.index(anchor, first + len(TENANT_DDL))
s = s[:second] + TENANT_DDL + PLATFORM_ONLY_DDL + s[second + len(anchor):]
assert s.count("CREATE TABLE IF NOT EXISTS ai_review_packs") == 2 and s.count("CREATE TABLE IF NOT EXISTS platform_ai_features") == 1
write("database.py", s, crlf)

patch("modules/governance/data_service.py", [
    ('"ai_evaluation_runs", "ai_regulatory_impacts",',
     '"ai_evaluation_runs", "ai_regulatory_impacts", "ai_review_packs", "ai_literacy_courses", "ai_literacy_completions",'),
])

patch("core/rbac.py", [
    ('''    "ai_use.decide":             {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER, DPO},
''', '''    "ai_use.decide":             {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER, DPO},
    # Review packs (plans/ai-governance/09). Issuing and revoking sit with the people who decide uses. Receiving also covers
    # the audit roles, who need no other AI governance access to read a pack addressed to them.
    "ai_pack.manage":            {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER, DPO},
    "ai_pack.receive":           {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER, DPO, AUDIT_LEAD, AUDITOR, EXTERNAL_AUDITOR},
    # AI literacy: everyone but an outside auditor may be assigned and complete a course; defining courses and reading who
    # has completed them are separate rights.
    "ai_literacy.take":          set(ALL_ROLES) - {EXTERNAL_AUDITOR},
    "ai_literacy.manage":        {SUPER_ADMIN, ORG_ADMIN, DPO, GRC_OFFICER, COMPLIANCE_MGR},
    "ai_literacy.report":        {SUPER_ADMIN, ORG_ADMIN, DPO, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER},
    # The platform's own AI features: platform operators only.
    "ai_governance.platform.manage": {SUPER_ADMIN},
'''),
])

patch("core/events.py", [
    ('''AI_REGULATORY_CONFIRMED = "ai_use.regulatory_confirmed"
''', '''AI_REGULATORY_CONFIRMED = "ai_use.regulatory_confirmed"
AI_PACK_ISSUED          = "ai_use.pack_issued"
AI_LITERACY_PUBLISHED   = "ai_literacy.published"
'''),
])

HANDLERS = '''

# ── Review packs and AI literacy ────────────────────────────────────────────

@events.on(events.AI_PACK_ISSUED)
def tell_recipient_of_pack(*, payload=None, event_id=None, user_id=None, **kw):
    """The named recipient hears that a pack was shared with them, once."""
    db = get_db()
    try:
        data = payload or {}
        row = db.execute("SELECT id, name, application_name, status FROM ai_review_packs WHERE id = %s", (data.get("pack_id"),)).fetchone()
        if row is None or row["status"] != "issued" or data.get("recipient_id") in (None, user_id):
            return
        _notify(db, event_id, data["recipient_id"], "A review pack was shared with you",
                f"{row['name']}: {row['application_name']}.", f"/ai-governance/packs/{row['id']}")
        db.commit()
    finally:
        db.close()


@events.on(events.AI_LITERACY_PUBLISHED)
def tell_assignees_of_course(*, payload=None, event_id=None, org_id=None, user_id=None, **kw):
    """People a published course applies to hear once that it is theirs to complete, whoever published it excepted."""
    from modules.ai_governance import literacy
    db = get_db()
    try:
        data = payload or {}
        for person in literacy.assignees_of(db, data.get("course_id"), org_id):
            if person != user_id:
                _notify(db, event_id, person, "An AI literacy course was assigned to you",
                        f"{data.get('title') or 'A course'} is due within {data.get('due_days') or 30} days.",
                        f"/ai-governance/literacy/{data.get('course_id')}")
        db.commit()
    finally:
        db.close()
'''
s, crlf = read("modules/ai_governance/handlers.py")
write("modules/ai_governance/handlers.py", s.rstrip("\n") + "\n" + HANDLERS, crlf)
