"""AI literacy courses, assignments, completions and unit-scoped coverage.

Published versions and completions are append-only. Assignment is derived from
the current organization, roles, unit and active AI-use ownership on every read.
Services do not commit; callers commit before delivering returned events.
"""
import calendar
import json
import re
from datetime import datetime, timedelta

from core import events
from core.rbac import ALL_ROLES, EMPLOYEE, EXTERNAL_AUDITOR
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import ServiceError
from modules.governance.data_service import bu_scope_ids


AUDIENCE_ROLES = tuple(role for role in ALL_ROLES if role not in (EXTERNAL_AUDITOR, EMPLOYEE))  # ai_literacy.take
MAX_QUESTIONS = 20
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_NOT_FOUND = "Course not found."


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit() and len(value) <= 9:
        return int(value)
    return None


def _text(value, limit, label):
    if not isinstance(value, str):
        raise ServiceError(422, f"{label} must be text.")
    cleaned = _CONTROL.sub("", value).strip()
    if len(cleaned) > limit:
        raise ServiceError(422, f"{label} must be {limit} characters or fewer.")
    return cleaned


def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _when(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _stamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _plus_months(moment, months):
    year = moment.year + (moment.month - 1 + months) // 12
    month = (moment.month - 1 + months) % 12 + 1
    return moment.replace(year=year, month=month,
                          day=min(moment.day, calendar.monthrange(year, month)[1]))


def _scope(user):
    return bu_scope_ids(user)


def _visible(user, unit):
    return _visible_in(_scope(user), unit)


def _visible_in(scope, unit):
    return scope is None or unit is None or unit in scope


def _course(db, user, course_id, capability):
    service._require(user, capability)
    row = db.execute("SELECT * FROM ai_literacy_courses WHERE id = %s", (course_id,)).fetchone()
    if not row or not _visible(user, row["business_unit_id"]):
        raise ServiceError(404, _NOT_FOUND)
    return dict(row)


def _unit_exists(db, unit):
    return db.execute("SELECT id FROM business_units WHERE id = %s AND is_active = 1", (unit,)).fetchone() is not None


def _clean_questions(raw):
    if not isinstance(raw, list) or len(raw) > MAX_QUESTIONS:
        raise ServiceError(422, f"Questions must be a list of at most {MAX_QUESTIONS} items.")
    cleaned = []
    for number, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ServiceError(422, f"Question {number} must be an object.")
        prompt = _text(item.get("prompt"), 1000, f"Question {number} prompt")
        options = item.get("options")
        if not prompt or not isinstance(options, list) or not 2 <= len(options) <= 6:
            raise ServiceError(422, f"Question {number} needs a prompt and 2 to 6 options.")
        options = [_text(o, 500, f"Question {number} option") for o in options]
        correct = _int(item.get("correct"))
        if any(not o for o in options) or len(set(options)) != len(options) or correct is None or not 0 <= correct < len(options):
            raise ServiceError(422, f"Question {number} needs distinct options and one valid correct option.")
        cleaned.append({"prompt": prompt, "options": options, "correct": correct})
    return cleaned


def _clean(db, user, raw, previous=None):
    if not isinstance(raw, dict):
        raise ServiceError(422, "Send the course as an object.")
    prior = previous or {}
    title = _text(raw.get("title", prior.get("title") or ""), 200, "Title")
    summary = _text(raw.get("summary", prior.get("summary") or ""), 500, "Summary")
    body = _text(raw.get("body", prior.get("body") or ""), 20000, "Body")
    # A course saved before employees lost AI Governance may still name them: they are dropped, not refused.
    roles = raw.get("audience_roles", [r for r in _json(prior.get("audience_roles"), []) if r in AUDIENCE_ROLES])
    if not isinstance(roles, list) or len(roles) > len(AUDIENCE_ROLES) or any(not isinstance(r, str) or r not in AUDIENCE_ROLES for r in roles):
        raise ServiceError(422, "Choose valid audience roles. Employees and external auditors cannot be assigned.")
    roles = sorted(set(roles))
    owners = raw.get("audience_owners", bool(prior.get("audience_owners")))
    if not isinstance(owners, bool):
        raise ServiceError(422, "Choose yes or no for AI use owners.")
    unit = raw.get("business_unit_id", prior.get("business_unit_id"))
    if unit in (None, ""):
        unit = None
    else:
        unit = _int(unit)
        if not unit or not _unit_exists(db, unit) or not _visible(user, unit):
            raise ServiceError(422, "Choose a business unit you can manage.")
    if previous and previous.get("business_unit_id") is not None and unit is None and _scope(user) is not None:
        raise ServiceError(403, "Only an unrestricted manager can make this course organization wide.")
    renewal = _int(raw.get("renewal_months", prior.get("renewal_months", 12)))
    due = _int(raw.get("due_days", prior.get("due_days", 30)))
    if renewal is None or not 1 <= renewal <= 60 or due is None or not 1 <= due <= 365:
        raise ServiceError(422, "Renewal must be 1 to 60 months and due time 1 to 365 days.")
    questions = _clean_questions(raw.get("questions", _json(prior.get("questions"), [])))
    mark = raw.get("pass_mark", prior.get("pass_mark"))
    if questions:
        mark = _int(mark)
        if mark is None or not 1 <= mark <= 100:
            raise ServiceError(422, "Choose a pass mark from 1 to 100.")
    else:
        mark = None
    return {"title": title, "summary": summary, "body": body, "questions": questions, "pass_mark": mark,
            "audience_roles": roles, "audience_owners": owners, "business_unit_id": unit,
            "renewal_months": renewal, "due_days": due}


def _manager_view(row):
    item = {key: row[key] for key in ("id", "title", "summary", "body", "pass_mark", "audience_owners",
            "business_unit_id", "renewal_months", "due_days", "status", "current_version", "retake_from",
            "published_at", "version", "created_at", "updated_at")} | {
                "questions": _json(row.get("questions"), []),
                "audience_roles": _json(row.get("audience_roles"), [])}
    for key in ("published_at", "created_at", "updated_at"):
        item[key] = _stamp(_when(item[key]))
    return item


def create_course(db, user, raw):
    service._require(user, "ai_literacy.manage")
    item = _clean(db, user, raw)
    if not item["title"]:
        raise ServiceError(422, "Give the course a title.")
    now = _stamp(utcnow())
    course_id = insert_returning_id(db, "INSERT INTO ai_literacy_courses "
        "(title, summary, body, questions, pass_mark, audience_roles, audience_owners, business_unit_id, "
        "renewal_months, due_days, created_by, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (item["title"], item["summary"], item["body"], json.dumps(item["questions"]), item["pass_mark"],
         json.dumps(item["audience_roles"]), int(item["audience_owners"]), item["business_unit_id"],
         item["renewal_months"], item["due_days"], user["id"], now, now))
    return {"course": get_course(db, user, course_id), "events": [],
            "audit": [("ai_literacy_course_created", "ai_literacy_course", course_id, item["title"])]}


def update_course(db, user, course_id, raw, expected_version):
    row = _course(db, user, course_id, "ai_literacy.manage")
    if row["status"] == "retired":
        raise ServiceError(409, "A retired course cannot be edited.")
    expected = _int(expected_version)
    if expected is None or expected != row["version"]:
        raise ServiceError(409, "The course changed. Reload it before saving.")
    item = _clean(db, user, raw, row)
    if not item["title"]:
        raise ServiceError(422, "Give the course a title.")
    if row["status"] == "active" and not (item["audience_roles"] or item["audience_owners"]):
        raise ServiceError(422, "An active course must keep an audience. Retire it to end assignments.")
    now = _stamp(utcnow())
    changed = db.execute("UPDATE ai_literacy_courses SET title=%s, summary=%s, body=%s, questions=%s, "
        "pass_mark=%s, audience_roles=%s, audience_owners=%s, business_unit_id=%s, renewal_months=%s, due_days=%s, "
        "version=version+1, updated_at=%s WHERE id=%s AND version=%s AND status != 'retired'",
        (item["title"], item["summary"], item["body"], json.dumps(item["questions"]), item["pass_mark"],
         json.dumps(item["audience_roles"]), int(item["audience_owners"]), item["business_unit_id"],
         item["renewal_months"], item["due_days"], now, course_id, expected)).rowcount
    if changed != 1:
        raise ServiceError(409, "The course changed. Reload it before saving.")
    return {"course": get_course(db, user, course_id), "events": [],
            "audit": [("ai_literacy_course_updated", "ai_literacy_course", course_id, item["title"])]}


def publish_course(db, user, course_id, retake, expected_version):
    row = _course(db, user, course_id, "ai_literacy.manage")
    expected = _int(expected_version)
    if expected is None or expected != row["version"]:
        raise ServiceError(409, "The course changed. Reload it before publishing.")
    if row["status"] == "retired" or not isinstance(retake, bool):
        raise ServiceError(422, "Choose whether this publication needs a retake.")
    item = _clean(db, user, {}, row)
    if not item["title"] or not item["body"] or not (item["audience_roles"] or item["audience_owners"]):
        raise ServiceError(422, "A published course needs a title, content and an audience.")
    number = row["current_version"] + 1
    needs_retake = bool(retake or number == 1)
    now = _stamp(utcnow())
    updated = db.execute("UPDATE ai_literacy_courses SET current_version=%s, retake_from=%s, "
        "status='active', published_at=%s, version=version+1, updated_at=%s "
        "WHERE id=%s AND version=%s AND status != 'retired'",
        (number, number if needs_retake else row["retake_from"], now, now, course_id, expected)).rowcount
    if updated != 1:
        raise ServiceError(409, "The course changed. Reload it before publishing.")
    db.execute("INSERT INTO ai_literacy_versions (course_id, version, title, body, questions, pass_mark, "
        "retake, published_by, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (course_id, number, item["title"], item["body"], json.dumps(item["questions"]), item["pass_mark"],
         int(needs_retake), user["id"], now))
    out_events = []
    if needs_retake:
        out_events.append(events.enqueue(db, events.AI_LITERACY_PUBLISHED, "ai_governance", "ai_literacy_course",
                                         course_id, {"course_id": course_id, "title": item["title"],
                                                     "due_days": item["due_days"]}, user["id"], user.get("org_id"),
                                         dedup_key=f"ai-literacy:{user.get('org_id')}:{course_id}:{number}"))
    return {"course": get_course(db, user, course_id), "events": out_events,
            "audit": [("ai_literacy_published", "ai_literacy_course", course_id,
                       f"version {number}; retake {needs_retake}")]}


def retire_course(db, user, course_id, expected_version):
    row = _course(db, user, course_id, "ai_literacy.manage")
    expected = _int(expected_version)
    if expected is None or expected != row["version"]:
        raise ServiceError(409, "The course changed. Reload it before retiring.")
    if row["status"] == "retired":
        return {"course": _manager_view(row), "events": [], "audit": [], "already": True}
    changed = db.execute("UPDATE ai_literacy_courses SET status='retired', version=version+1, updated_at=%s "
                         "WHERE id=%s AND version=%s AND status != 'retired'",
                         (_stamp(utcnow()), course_id, expected)).rowcount
    if changed != 1:
        raise ServiceError(409, "The course changed. Reload it before retiring.")
    return {"course": get_course(db, user, course_id), "events": [],
            "audit": [("ai_literacy_retired", "ai_literacy_course", course_id, row["title"])]}


def list_courses(db, user):
    service._require(user, "ai_literacy.manage")
    scope = _scope(user)
    rows = db.execute("SELECT * FROM ai_literacy_courses ORDER BY updated_at DESC, id DESC").fetchall()
    return {"items": [_manager_view(dict(r)) for r in rows if _visible_in(scope, r["business_unit_id"])],
            "roles": list(AUDIENCE_ROLES)}


def list_units(db, user):
    service._require(user, "ai_literacy.manage")
    scope = _scope(user)
    rows = db.execute("SELECT id, name FROM business_units WHERE is_active=1 ORDER BY name, id").fetchall()
    return {"items": [dict(row) for row in rows if _visible_in(scope, row["id"])]}


def get_course(db, user, course_id):
    return _manager_view(_course(db, user, course_id, "ai_literacy.manage"))


def _people(db, org_id, user_id=None):
    if org_id is None:
        return []
    only = " AND id=%s" if user_id is not None else ""
    params = (org_id, user_id) if user_id is not None else (org_id,)
    rows = db.execute("SELECT id, full_name, business_unit_id, created_at FROM users "
                      f"WHERE org_id=%s AND is_active=1 AND deleted_at IS NULL{only} ORDER BY full_name, id", params).fetchall()
    people = {r["id"]: {**dict(r), "roles": set(), "owns": False} for r in rows}
    if not people:
        return []
    role_only = " AND u.id=%s" if user_id is not None else ""
    for r in db.execute("SELECT ur.user_id, ur.role_key FROM user_roles ur JOIN users u ON u.id=ur.user_id "
                        f"WHERE u.org_id=%s AND u.is_active=1 AND u.deleted_at IS NULL{role_only}", params).fetchall():
        if r["user_id"] in people:
            people[r["user_id"]]["roles"].add(r["role_key"])
    owner_only = " AND a.owner_user_id=%s" if user_id is not None else ""
    for r in db.execute("SELECT DISTINCT a.owner_user_id AS id FROM applications a "
                        "JOIN ai_use_profiles p ON p.application_id=a.id "
                        f"WHERE a.is_active=1 AND a.owner_user_id IS NOT NULL{owner_only}",
                        (user_id,) if user_id is not None else ()).fetchall():
        if r["id"] in people:
            people[r["id"]]["owns"] = True
    return list(people.values())


def _assigned(course, person, unit_ids):
    if not person["roles"] & set(AUDIENCE_ROLES):
        return False  # only employee or outside auditor roles: AI Governance does not open for them
    unit = course["business_unit_id"]
    if unit is not None and (person["business_unit_id"] is None or person["business_unit_id"] not in unit_ids):
        return False
    roles = set(_json(course["audience_roles"], []))
    return bool((person["roles"] & roles) or (course["audience_owners"] and person["owns"]))


def _audience(db, course, people):
    unit_ids = (_scope({"business_unit_id": course["business_unit_id"], "is_super_admin": False})
                if course["business_unit_id"] is not None else None)
    return [p for p in people if _assigned(course, p, unit_ids)]


def assignees_of(db, course_id, org_id):
    """Event handler audience. The event's tenant context selects the course schema."""
    if org_id is None:
        return []
    row = db.execute("SELECT * FROM ai_literacy_courses WHERE id=%s AND status='active'", (course_id,)).fetchone()
    return [p["id"] for p in _audience(db, dict(row), _people(db, org_id))] if row else []


def _completion(db, course_id, person_id, retake_from):
    return db.execute("SELECT * FROM ai_literacy_completions WHERE course_id=%s AND user_id=%s "
                      "AND course_version >= %s ORDER BY completed_at DESC, id DESC LIMIT 1",
                      (course_id, person_id, retake_from)).fetchone()


def _state(db, course, person, now, done=None, have_done=False):
    if "_retake_at" not in course:
        start = db.execute("SELECT published_at FROM ai_literacy_versions WHERE course_id=%s AND version=%s",
                           (course["id"], course["retake_from"])).fetchone()
        course["_retake_at"] = _when(start["published_at"]) if start else _when(course["published_at"])
    published = course["_retake_at"]
    account = _when(person["created_at"])
    base = max((d for d in (published, account) if d), default=now)
    due = base + timedelta(days=course["due_days"])
    if not have_done:
        done = _completion(db, course["id"], person["id"], course["retake_from"])
    expires = _when(done["expires_at"]) if done else None
    if done:
        state = "expired" if expires is None or expires <= now else "completed"
    else:
        state = "overdue" if due < now else "to_do"
    return {"state": state, "due_at": _stamp(due), "completed_at": _stamp(_when(done["completed_at"])) if done else None,
            "renew_at": _stamp(expires)}


def my_courses(db, user):
    service._require(user, "ai_literacy.take")
    people = _people(db, user.get("org_id"), user["id"])
    person = next((p for p in people if p["id"] == user["id"]), None)
    if person is None:
        return {"items": []}
    now = utcnow().replace(tzinfo=None)
    courses = db.execute("SELECT * FROM ai_literacy_courses WHERE status='active' ORDER BY title, id").fetchall()
    items = []
    for row in courses:
        course = dict(row)
        if not _audience(db, course, [person]):
            continue
        published = db.execute("SELECT title FROM ai_literacy_versions WHERE course_id=%s AND version=%s",
                               (course["id"], course["current_version"])).fetchone()
        items.append({"id": course["id"], "title": published["title"] if published else course["title"],
                      "current_version": course["current_version"], **_state(db, course, person, now)})
    return {"items": items}


def get_for_learning(db, user, course_id):
    service._require(user, "ai_literacy.take")
    course = db.execute("SELECT * FROM ai_literacy_courses WHERE id=%s AND status='active'", (course_id,)).fetchone()
    if not course:
        raise ServiceError(404, _NOT_FOUND)
    people = _people(db, user.get("org_id"), user["id"])
    person = next((p for p in people if p["id"] == user["id"]), None)
    course = dict(course)
    if not person or not _audience(db, course, [person]):
        raise ServiceError(404, _NOT_FOUND)
    version = db.execute("SELECT title, body, questions, pass_mark, version FROM ai_literacy_versions "
                         "WHERE course_id=%s AND version=%s", (course_id, course["current_version"])).fetchone()
    if not version:
        raise ServiceError(503, "The published course is unavailable.")
    questions = [{"prompt": q["prompt"], "options": q["options"]} for q in _json(version["questions"], [])]
    return {"course": {"id": course_id, "title": version["title"], "body": version["body"],
                       "questions": questions, "pass_mark": version["pass_mark"], "version": version["version"],
                       **_state(db, course, person, utcnow().replace(tzinfo=None))}}


def complete(db, user, course_id, answers, acknowledged, expected_version):
    """Record only a passing attempt. Failed attempts return feedback without answer keys."""
    service._require(user, "ai_literacy.take")
    # A harmless row write serializes simultaneous submissions for the same course on PostgreSQL and SQLite.
    # The second writer reads the first completion only after that transaction commits.
    db.execute("UPDATE ai_literacy_courses SET id=id WHERE id=%s AND status='active'", (course_id,))
    course = db.execute("SELECT * FROM ai_literacy_courses WHERE id=%s AND status='active'", (course_id,)).fetchone()
    if not course:
        raise ServiceError(404, _NOT_FOUND)
    course = dict(course)
    people = _people(db, user.get("org_id"), user["id"])
    person = next((p for p in people if p["id"] == user["id"]), None)
    if not person or not _audience(db, course, [person]):
        raise ServiceError(404, _NOT_FOUND)
    if _int(expected_version) != course["current_version"]:
        raise ServiceError(409, "The course changed. Reload it before completing.")
    now = utcnow().replace(tzinfo=None)
    state = _state(db, course, person, now)
    if state["state"] == "completed":
        return {"result": {"passed": True, "already": True, **state}, "events": [], "audit": []}
    published = db.execute("SELECT questions, pass_mark FROM ai_literacy_versions WHERE course_id=%s AND version=%s",
                           (course_id, course["current_version"])).fetchone()
    if not published:
        raise ServiceError(503, "The published course is unavailable.")
    questions = _json(published["questions"], [])
    if questions:
        if not isinstance(answers, list) or len(answers) != len(questions) or any(
                not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(q["options"])
                for answer, q in zip(answers, questions)):
            raise ServiceError(422, "Answer every question by choosing one listed option.")
        wrong = [i + 1 for i, (answer, q) in enumerate(zip(answers, questions)) if answer != q["correct"]]
        score = round(100 * (len(questions) - len(wrong)) / len(questions))
        if score < published["pass_mark"]:
            return {"result": {"passed": False, "score": score, "wrong_questions": wrong},
                    "events": [], "audit": []}
        outcome = "passed"
    else:
        if acknowledged is not True:
            raise ServiceError(422, "Confirm that you read and understood the course.")
        outcome, score = "acknowledged", None
    expires = _plus_months(now, course["renewal_months"])
    completion_id = insert_returning_id(db, "INSERT INTO ai_literacy_completions "
        "(course_id, course_version, user_id, business_unit_id, outcome, score, completed_at, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (course_id, course["current_version"], user["id"], person["business_unit_id"], outcome, score,
         _stamp(now), _stamp(expires)))
    return {"result": {"passed": True, "score": score, "completion_id": completion_id,
                       "completed_at": _stamp(now), "renew_at": _stamp(expires)}, "events": [],
            "audit": [("ai_literacy_completed", "ai_literacy_course", course_id,
                       f"version {course['current_version']}; {outcome}")]}


def _report_people(db, user, course, people=None, scope=None):
    if scope is None:
        scope = _scope(user)
    people = _audience(db, course, people if people is not None else _people(db, user.get("org_id")))
    if scope is not None:
        people = [p for p in people if p["business_unit_id"] is not None and p["business_unit_id"] in scope]
    return people


def _coverage_row(db, course, people, detail=False):
    now = utcnow().replace(tzinfo=None)
    counts = {"completed": 0, "expired": 0, "overdue": 0, "to_do": 0}
    rows = []
    ids = {person["id"] for person in people}
    completions = {}
    if ids:
        for done in db.execute("SELECT * FROM ai_literacy_completions WHERE course_id=%s "
                               "AND course_version >= %s ORDER BY user_id, completed_at DESC, id DESC",
                               (course["id"], course["retake_from"])).fetchall():
            if done["user_id"] in ids and done["user_id"] not in completions:
                completions[done["user_id"]] = done
    for person in people:
        state = _state(db, course, person, now, completions.get(person["id"]), have_done=True)
        counts[state["state"]] += 1
        if detail and len(rows) < 200:
            rows.append({"user_id": person["id"], "name": person["full_name"],
                         "business_unit_id": person["business_unit_id"], **state})
    published = db.execute("SELECT title FROM ai_literacy_versions WHERE course_id=%s AND version=%s",
                           (course["id"], course["current_version"])).fetchone()
    return {"id": course["id"], "title": published["title"] if published else course["title"],
            "version": course["current_version"],
            "denominator": len(people), **counts, **({"people": rows} if detail else {})}


def coverage(db, user):
    service._require(user, "ai_literacy.report")
    courses = db.execute("SELECT * FROM ai_literacy_courses WHERE status='active' ORDER BY title, id").fetchall()
    people = _people(db, user.get("org_id"))
    scope = _scope(user)
    return {"items": [_coverage_row(db, dict(c), _report_people(db, user, dict(c), people, scope)) for c in courses
                      if _visible_in(scope, c["business_unit_id"])]}


def course_coverage(db, user, course_id):
    course = _course(db, user, course_id, "ai_literacy.report")
    if course["status"] != "active":
        raise ServiceError(404, _NOT_FOUND)
    return {"course": _coverage_row(db, course, _report_people(db, user, course), detail=True)}


def owner_gap(db, viewer, owner_id):
    """One quality signal, only where the viewer may also see the owner's course coverage."""
    if owner_id is None or viewer.get("org_id") is None:
        return None
    person = next((p for p in _people(db, viewer["org_id"], owner_id) if p["id"] == owner_id), None)
    if person is None:
        return None
    scope = _scope(viewer)
    if (scope is not None and viewer["id"] != owner_id
            and (person["business_unit_id"] is None or person["business_unit_id"] not in scope)):
        return None
    now = utcnow().replace(tzinfo=None)
    missing = []
    for row in db.execute("SELECT * FROM ai_literacy_courses WHERE status='active' AND audience_owners=1").fetchall():
        course = dict(row)
        if (_visible_in(scope, course["business_unit_id"]) and _audience(db, course, [person])
                and _state(db, course, person, now)["state"] != "completed"):
            missing.append((course["id"], course["retake_from"]))
    return sorted(missing)
