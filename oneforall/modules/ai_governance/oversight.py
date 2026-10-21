"""Versioned, content-neutral human oversight arrangements for an AI use.

This records an organization's own design and operating procedures. It makes no
claim about a legal classification or conformity with a particular rule pack.
"""

from core.sql_like import ci_like, like_pattern
from core.rbac import has_capability
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record


TRACKS = ("design", "operation")
FIELDS = ("monitoring_method", "intervention_method", "stop_procedure", "escalation_path")
MAX_FIELD = 2000


def _visible(db, user, application_id, capability="ai_use.view"):
    service._require(user, capability)
    if isinstance(application_id, bool) or not isinstance(application_id, int) or application_id < 1:
        raise ServiceError(404, "AI use not found.")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "AI use not found.")


def _track(track):
    if track not in TRACKS:
        raise ServiceError(404, "Oversight track not found.")


def _profile_version(db, application_id):
    row = db.execute("SELECT version FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone()
    return row["version"] if row else None


def _head(db, application_id, track):
    return db.execute("SELECT content_version, revision FROM ai_oversight_heads "
                      "WHERE application_id = %s AND track = %s", (application_id, track)).fetchone()


def _version(db, application_id, track, version):
    return db.execute(
        "SELECT v.*, owner.full_name AS responsible_name, author.full_name AS author_name, "
        "reviewer.full_name AS reviewer_name FROM ai_oversight_versions v "
        "LEFT JOIN users owner ON owner.id = v.responsible_user_id "
        "LEFT JOIN users author ON author.id = v.authored_by "
        "LEFT JOIN users reviewer ON reviewer.id = v.reviewed_by "
        "WHERE v.application_id = %s AND v.track = %s AND v.version = %s",
        (application_id, track, version)).fetchone()


def _public_version(row, current_profile_version):
    if row is None:
        return None
    return {
        "version": row["version"], "profile_version": row["profile_version"],
        "profile_changed": row["profile_version"] != current_profile_version,
        "responsible_user_id": row["responsible_user_id"], "responsible_name": row["responsible_name"],
        **{field: row[field] for field in FIELDS},
        "status": row["status"], "authored_by": row["authored_by"], "author_name": row["author_name"],
        "authored_at": str(row["authored_at"]), "reviewed_by": row["reviewed_by"],
        "reviewer_name": row["reviewer_name"],
        "reviewed_at": str(row["reviewed_at"]) if row["reviewed_at"] else None,
    }


def get_arrangement(db, user, application_id, track):
    _visible(db, user, application_id)
    _track(track)
    profile_version = _profile_version(db, application_id)
    head = _head(db, application_id, track)
    current = _version(db, application_id, track, head["content_version"]) if head and head["content_version"] else None
    history = []
    if head and head["content_version"] > 1:
        rows = db.execute("SELECT version FROM ai_oversight_versions WHERE application_id = %s AND track = %s "
                          "AND version < %s ORDER BY version DESC LIMIT 20",
                          (application_id, track, head["content_version"])).fetchall()
        history = [_public_version(_version(db, application_id, track, row["version"]), profile_version)
                   for row in rows]
    return {"oversight": {"application_id": application_id, "track": track,
                          "profile_version": profile_version, "revision": head["revision"] if head else 0,
                          "current": _public_version(current, profile_version), "history": history}}


def summary_for_use(db, user, application_id):
    """Small live status for connected views, without copying procedure text."""
    _visible(db, user, application_id)
    profile_version = _profile_version(db, application_id)
    rows = db.execute(
        "SELECT h.track, v.version, v.profile_version, v.status "
        "FROM ai_oversight_heads h JOIN ai_oversight_versions v ON "
        "v.application_id = h.application_id AND v.track = h.track AND v.version = h.content_version "
        "WHERE h.application_id = %s", (application_id,)).fetchall()
    by_track = {row["track"]: row for row in rows}
    tracks = {}
    for track in TRACKS:
        row = by_track.get(track)
        tracks[track] = ({"status": row["status"], "version": row["version"],
                          "profile_changed": row["profile_version"] != profile_version}
                         if row else {"status": "not_recorded", "version": None,
                                      "profile_changed": False})
    return {"tracks": tracks, "profile_version": profile_version}


def _expected_revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ServiceError(400, "Send the revision of the oversight record you opened.")
    return value


def _responsible(db, user, application_id, value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ServiceError(422, "Choose an active person in your organization.")
    row = db.execute("SELECT id, org_id, business_unit_id, is_active, is_super_admin, deleted_at "
                     "FROM users WHERE id = %s", (value,)).fetchone()
    if (not row or not row["is_active"] or row["deleted_at"]
            or (user.get("org_id") is not None and row["org_id"] != user["org_id"])):
        raise ServiceError(422, "Choose an active person in your organization.")
    roles = [r["role_key"] for r in db.execute("SELECT role_key FROM user_roles WHERE user_id = %s", (value,)).fetchall()]
    person = {"id": row["id"], "org_id": row["org_id"], "business_unit_id": row["business_unit_id"],
              "is_super_admin": bool(row["is_super_admin"]), "roles": roles}
    if not has_capability(person, "ai_use.view") or not describe_record(db, APP, application_id, person):
        raise ServiceError(422, "Choose a person who can open this AI use.")
    return value


def eligible_people(db, user, application_id, query):
    _visible(db, user, application_id, "ai_use.review")
    q = query.strip() if isinstance(query, str) else ""
    if len(q) < 2 or len(q) > 80:
        return {"items": []}
    sql = ("SELECT id, full_name FROM users WHERE is_active = 1 AND deleted_at IS NULL "
           f"AND ({ci_like('full_name')} OR {ci_like('username')})")
    params = [like_pattern(q), like_pattern(q)]
    if user.get("org_id") is not None:
        sql += " AND org_id = %s"
        params.append(user["org_id"])
    rows = db.execute(sql + " ORDER BY full_name LIMIT 100", params).fetchall()
    people = []
    for row in rows:
        try:
            _responsible(db, user, application_id, row["id"])
        except ServiceError:
            continue
        people.append({"id": row["id"], "name": row["full_name"]})
        if len(people) == 30:
            break
    return {"items": people}


def save_arrangement(db, user, application_id, track, raw, expected_revision):
    _visible(db, user, application_id, "ai_use.review")
    _track(track)
    revision = _expected_revision(expected_revision)
    profile_version = _profile_version(db, application_id)
    if profile_version is None:
        raise ServiceError(409, "Add the AI profile before recording oversight.")
    if not isinstance(raw, dict) or set(raw) - {*FIELDS, "responsible_user_id"}:
        raise ServiceError(422, "Send only the oversight fields shown on the form.")
    person = _responsible(db, user, application_id, raw.get("responsible_user_id"))
    fields = {}
    for field in FIELDS:
        value = raw.get(field, "")
        if not isinstance(value, str) or len(value.strip()) > MAX_FIELD:
            raise ServiceError(422, f"{field.replace('_', ' ').capitalize()} must be text of at most {MAX_FIELD} characters.")
        fields[field] = value.strip()
    db.execute("INSERT INTO ai_oversight_heads (application_id, track) VALUES (%s, %s) ON CONFLICT DO NOTHING",
               (application_id, track))
    head = _head(db, application_id, track)
    if head["revision"] != revision:
        raise ServiceError(409, "This oversight record changed. Reload it before saving.")
    version = head["content_version"] + 1
    changed = db.execute("UPDATE ai_oversight_heads SET content_version = %s, revision = revision + 1 "
                         "WHERE application_id = %s AND track = %s AND revision = %s",
                         (version, application_id, track, revision)).rowcount
    if changed != 1:
        raise ServiceError(409, "This oversight record changed. Reload it before saving.")
    db.execute("INSERT INTO ai_oversight_versions (application_id, track, version, profile_version, "
               "responsible_user_id, monitoring_method, intervention_method, stop_procedure, escalation_path, "
               "authored_by, authored_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
               (application_id, track, version, profile_version, person, *(fields[f] for f in FIELDS),
                user["id"], service._now()))
    return {**get_arrangement(db, user, application_id, track), "events": [],
            "audit": [("oversight_draft_saved", "application", application_id, f"{track} version {version}")]}


def review_arrangement(db, user, application_id, track, expected_revision):
    _visible(db, user, application_id, "ai_use.decide")
    _track(track)
    revision = _expected_revision(expected_revision)
    head = _head(db, application_id, track)
    if not head or not head["content_version"]:
        raise ServiceError(409, "Save an oversight draft before reviewing it.")
    if head["revision"] != revision:
        raise ServiceError(409, "This oversight record changed. Reload it before reviewing.")
    row = _version(db, application_id, track, head["content_version"])
    if row["status"] != "draft":
        raise ServiceError(409, "This version has already been reviewed.")
    if row["authored_by"] == user["id"]:
        raise ServiceError(403, "Ask another reviewer to review this version.")
    if row["profile_version"] != _profile_version(db, application_id):
        raise ServiceError(409, "The AI profile changed. Save a new oversight draft before reviewing.")
    if not row["responsible_user_id"] or any(not row[field] for field in FIELDS):
        raise ServiceError(422, "Name a responsible person and complete each procedure before review.")
    _responsible(db, user, application_id, row["responsible_user_id"])
    changed = db.execute("UPDATE ai_oversight_heads SET revision = revision + 1 "
                         "WHERE application_id = %s AND track = %s AND revision = %s",
                         (application_id, track, revision)).rowcount
    if changed != 1:
        raise ServiceError(409, "This oversight record changed. Reload it before reviewing.")
    db.execute("UPDATE ai_oversight_versions SET status = 'reviewed', reviewed_by = %s, reviewed_at = %s "
               "WHERE application_id = %s AND track = %s AND version = %s AND status = 'draft'",
               (user["id"], service._now(), application_id, track, row["version"]))
    return {**get_arrangement(db, user, application_id, track), "events": [],
            "audit": [("oversight_reviewed", "application", application_id,
                       f"{track} version {row['version']}")]}
