"""
AI governance: the questions a specialist needs a requester to answer (plans/2026-10-governance-rework/01 section 5).

A request that came from an external form has a requester who has no account. When the review needs something more, the
specialist writes a short, bounded set of questions, takes them out as text to send by the channel the customer uses, and
records the answer when it comes back, with where it came from. Nothing is sent from here and nothing about the requester
is exposed: a question and its answer belong to the request, and only a reviewer in its unit (and the request's own author,
read-only) can see them.

A request with an open question is "waiting for information": that is read here, and the Overview counts it from here.
"""
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import ServiceError

MAX_QUESTIONS = 12
QUESTION_MIN, QUESTION_MAX = 5, 500
ANSWER_MAX, SOURCE_MAX = 2000, 120


def _clean(value, what, low, high, required=True) -> "str | None":
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ServiceError(422, f"Say {what}.")
        return None
    if not isinstance(value, str):
        raise ServiceError(422, f"The {what} must be text.")
    value = " ".join(value.split()) if what == "the question" else value.strip()
    if len(value) < low:
        raise ServiceError(422, f"Say {what} in at least {low} characters.")
    if len(value) > high:
        raise ServiceError(422, f"Keep {what} to {high} characters or fewer.")
    return value


def _present(row, names=None) -> dict:
    names = names or {}
    return {"id": row["id"], "intake_id": row["intake_id"], "position": row["position"], "text": row["text"],
            "status": row["status"], "asked_by": names.get(row["asked_by"]), "asked_at": service._text(row["asked_at"]),
            "answer": row["answer"], "answer_source": row["answer_source"], "answered_by": names.get(row["answered_by"]),
            "answered_at": service._text(row["answered_at"]), "version": row["version"]}


def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(wanted))})", wanted).fetchall()
    return {r["id"]: r["full_name"] for r in rows}


def _request_for(db, user, intake_id: int, *, reviewer: bool):
    """A request the caller may work with: a reviewer in its unit, or (reading only) its own author."""
    row = service._load(db, intake_id)
    if row is None:
        raise ServiceError(404, "Request not found.")
    if reviewer:
        if not service._visible_to_reviewer(user, row):
            raise ServiceError(404, "Request not found.")
    elif not (service._visible_to_reviewer(user, row) or service._visible_to_author(user, row)):
        raise ServiceError(404, "Request not found.")
    return row


def list_questions(db, user, intake_id: int) -> dict:
    service._require(user, "ai_use.view")
    row = _request_for(db, user, intake_id, reviewer=False)
    rows = db.execute("SELECT * FROM ai_request_questions WHERE intake_id = %s ORDER BY position, id", (intake_id,)).fetchall()
    names = _names(db, [i for r in rows for i in (r["asked_by"], r["answered_by"])])
    items = [_present(r, names) for r in rows]
    can = service._visible_to_reviewer(user, row)
    return {"questions": items, "open": sum(1 for q in items if q["status"] == "open"),
            "can_ask": can and row["status"] in ("draft", "submitted", "returned"),
            "limit": MAX_QUESTIONS}


def ask(db, user, intake_id: int, texts) -> dict:
    """Add questions to a request that has not been decided. At most twelve live questions per request."""
    service._require(user, "ai_use.review")
    row = _request_for(db, user, intake_id, reviewer=True)
    if row["status"] not in ("draft", "submitted", "returned"):
        raise ServiceError(409, "This request has been decided. Questions belong to a request still being reviewed.")
    if not isinstance(texts, list) or not texts:
        raise ServiceError(422, "Send the questions as a list.")
    cleaned = [_clean(t, "the question", QUESTION_MIN, QUESTION_MAX) for t in texts]
    live = db.execute("SELECT COUNT(*) FROM ai_request_questions WHERE intake_id = %s AND status != 'withdrawn'",
                      (intake_id,)).fetchone()[0]
    if live + len(cleaned) > MAX_QUESTIONS:
        raise ServiceError(422, f"A request can carry at most {MAX_QUESTIONS} questions, and it has {live}.")
    last = db.execute("SELECT COALESCE(MAX(position), 0) FROM ai_request_questions WHERE intake_id = %s", (intake_id,)).fetchone()[0]
    now = service._now()
    created = []
    for offset, text in enumerate(cleaned, start=1):
        created.append(insert_returning_id(
            db, "INSERT INTO ai_request_questions (org_id, intake_id, position, text, status, asked_by, asked_at, version) "
                "VALUES (%s, %s, %s, %s, 'open', %s, %s, 1)", (row["org_id"], intake_id, last + offset, text, user["id"], now)))
    return {"created": created, "events": [],
            "audit": [("ai_questions_asked", "ai_use_intake", intake_id, f"{len(cleaned)} question(s)")], **list_questions(db, user, intake_id)}


def _question(db, user, question_id: int):
    q = db.execute("SELECT * FROM ai_request_questions WHERE id = %s", (question_id,)).fetchone()
    if q is None:
        raise ServiceError(404, "Question not found.")
    _request_for(db, user, q["intake_id"], reviewer=True)
    return q


def answer(db, user, question_id: int, text, source, expected_version) -> dict:
    """Record the answer a specialist received, and how it arrived. Answering again replaces the earlier answer."""
    service._require(user, "ai_use.review")
    q = _question(db, user, question_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the question you are answering.")
    if q["status"] == "withdrawn":
        raise ServiceError(409, "This question was withdrawn.")
    text = _clean(text, "the answer", 1, ANSWER_MAX)
    source = _clean(source, "where the answer came from", 3, SOURCE_MAX)
    moved = db.execute(
        "UPDATE ai_request_questions SET status = 'answered', answer = %s, answer_source = %s, answered_by = %s, "
        "answered_at = %s, version = version + 1 WHERE id = %s AND version = %s",
        (text, source, user["id"], service._now(), question_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This question was changed by someone else. Reload it and try again.")
    return {"question": _present(db.execute("SELECT * FROM ai_request_questions WHERE id = %s", (question_id,)).fetchone(),
                                 _names(db, [user["id"], q["asked_by"]])), "events": [],
            "audit": [("ai_question_answered", "ai_use_intake", q["intake_id"], f"question {q['position']} answered ({source})")]}


def withdraw(db, user, question_id: int, expected_version) -> dict:
    service._require(user, "ai_use.review")
    q = _question(db, user, question_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the question you are withdrawing.")
    if q["status"] != "open":
        raise ServiceError(409, "Only a question still waiting for an answer can be withdrawn.")
    moved = db.execute("UPDATE ai_request_questions SET status = 'withdrawn', version = version + 1 WHERE id = %s AND version = %s "
                       "AND status = 'open'", (question_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This question was changed by someone else. Reload it and try again.")
    return {"events": [], "audit": [("ai_question_withdrawn", "ai_use_intake", q["intake_id"], f"question {q['position']}")],
            **list_questions(db, user, q["intake_id"])}


def export_text(db, user, intake_id: int) -> dict:
    """The open questions as plain text to paste into an email or message, and the audit entry that it was taken out. The
    text names the request and the person who asked, and nothing internal."""
    service._require(user, "ai_use.review")
    row = _request_for(db, user, intake_id, reviewer=True)
    intake = service._intake(row)
    open_rows = db.execute("SELECT * FROM ai_request_questions WHERE intake_id = %s AND status = 'open' ORDER BY position, id",
                           (intake_id,)).fetchall()
    if not open_rows:
        raise ServiceError(409, "There is no open question to send.")
    requester = intake.get("requester") or {}
    lines = [f"Questions about: {intake['answers'].get('name') or 'an AI use'}", ""]
    if requester.get("name"):
        lines.append(f"For: {requester['name']}")
    lines.append(f"From: {user.get('full_name') or user.get('username') or 'the governance team'}")
    lines.append(f"Date: {utcnow().strftime('%Y-%m-%d')}")
    lines.append("")
    lines += [f"{n}. {q['text']}" for n, q in enumerate(open_rows, start=1)]
    lines += ["", "Please reply to the person who sent you this message."]
    return {"text": "\n".join(lines) + "\n", "count": len(open_rows), "events": [],
            "audit": [("ai_questions_exported", "ai_use_intake", intake_id, f"{len(open_rows)} open question(s)")]}


def waiting_ids(db, user) -> list:
    """Ids of the requests in the reviewer's scope that have an open question and have not been decided."""
    service._require(user, "ai_use.review")
    where, params = service._review_scope(user)
    rows = db.execute(
        "SELECT id FROM ai_use_intake_requests" + where + " AND status IN ('draft', 'submitted', 'returned') AND id IN "
        "(SELECT intake_id FROM ai_request_questions WHERE status = 'open')", params).fetchall()
    return [r[0] for r in rows]
