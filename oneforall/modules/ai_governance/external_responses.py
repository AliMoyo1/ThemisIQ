"""
AI governance: the response to a requester (plans/2026-10-governance-rework/01 section 6).

An external response is a short document that tells a requester the outcome of the organization's review of their AI use:
the outcome, its scope and conditions, what the requester still has to do, and when it will be looked at again. It is not
the internal decision, the internal brief or a review pack, and it never leaves by itself:

* it is drafted from a standing, signed decision, so the outcome and the conditions are the decision's own words;
* a specialist writes the summary and the requester's actions, and that is the whole of what is redacted by choice: the
  response carries no internal ids, no names of reviewers, no scores and no evidence;
* a different person with the right to decide approves it (the same separation of duties as the decision itself), which
  freezes its content under a hash;
* the specialist downloads it and sends it by the channel the organization uses. A download is recorded as an export, and
  only a person can record that it was sent, with the date, the channel and a reference. Nothing here sends anything, and
  an export is never taken as delivery.

If the decision it rests on is revoked or replaced, the response can no longer be exported, and a new revision is drafted.
"""
import hashlib
import io
import json

from core import ai_rollout
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import decisions, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record

STATUSES = ("draft", "approved", "exported", "sent", "withdrawn")
FORMATS = ("json", "pdf")
SUMMARY_MAX, SCOPE_MAX, ACTION_MAX, ACTIONS_MAX = 2000, 1000, 300, 10
CHANNEL_MAX, REFERENCE_MAX, REASON_MAX = 80, 120, 500
LIMITATION = ("This response states the outcome of the organization's internal review of this AI use on the date shown. It is "
              "not a certification, a legal opinion or a statement that the use complies with any law.")
OUTCOMES = {"approved": "Approved", "approved_with_conditions": "Approved with conditions", "rejected": "Not approved"}


def _day(value, what, required=False):
    if value in (None, ""):
        if required:
            raise ServiceError(422, f"Give {what}.", errors={what: f"Give {what}."})
        return None
    from modules.ai_governance import import_rules
    iso, ok = import_rules.norm_date(str(value), "iso")
    if not ok or iso is None:
        raise ServiceError(422, f"Write {what} as YYYY-MM-DD.", errors={what: f"Write {what} as YYYY-MM-DD."})
    return iso


def _text(value, what, limit, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ServiceError(422, f"Say {what}.", errors={what: f"Say {what}."})
        return None
    if not isinstance(value, str):
        raise ServiceError(422, f"The {what} must be text.", errors={what: f"The {what} must be text."})
    value = value.strip()
    if len(value) > limit:
        raise ServiceError(422, f"Keep the {what} to {limit} characters or fewer.", errors={what: f"Keep it to {limit} characters or fewer."})
    return value


def _actions(value):
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > ACTIONS_MAX:
        raise ServiceError(422, f"Send the requester actions as a list of at most {ACTIONS_MAX}.",
                           errors={"requester_actions": f"At most {ACTIONS_MAX} actions."})
    out = []
    for item in value:
        text = _text(item, "requester action", ACTION_MAX, required=True)
        out.append(text)
    return out


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(content: dict) -> str:
    return hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()


def build_content(row, application_name: str, org_name: "str | None") -> dict:
    """The document as it would be sent, from the row's fields. Pure: the same row always gives the same document."""
    requester = json.loads(row["requester"] or "{}")
    return {
        "format": 1, "revision": row["revision"], "organization": org_name, "response_date": row["response_date"],
        "subject": {"name": application_name},
        "requester": {"name": requester.get("name"), "organization": requester.get("organization")},
        "outcome": {"code": row["outcome"], "label": OUTCOMES.get(row["outcome"], row["outcome"])},
        "decision_date": row["decision_date"], "scope": row["scope_text"], "summary": row["summary"],
        "conditions": json.loads(row["conditions"] or "[]"), "requester_actions": json.loads(row["requester_actions"] or "[]"),
        "review_due": row["review_due"], "source_reference": row["source_reference"], "limitations": LIMITATION,
    }


def render_pdf(content: dict) -> bytes:
    """A one or two page PDF of the frozen content, with no more in it than the JSON has."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Response: {content['subject']['name']}"[:100], author=(content.get("organization") or "ThemisIQ")[:100])
    flow = []

    def para(text, style="BodyText", markup=False):
        """One paragraph. Words are escaped here; `markup=True` is only for a line this function assembled from escaped parts."""
        flow.append(Paragraph((str(text) if markup else escape(str(text))).replace("\n", "<br/>"), styles[style]))

    para(f"Response to a request about an AI use", "Title")
    if content.get("organization"):
        para(content["organization"], "Heading3")
    para(f"AI use: {content['subject']['name']}", "Heading2")
    bits = [("Outcome", content["outcome"]["label"]), ("Date of the response", content.get("response_date")),
            ("Decision date", content.get("decision_date")), ("To review again by", content.get("review_due")),
            ("For", " ".join(x for x in (content["requester"].get("name"), f"({content['requester']['organization']})"
                                          if content["requester"].get("organization") else "") if x)),
            ("Reference", content.get("source_reference")), ("Revision", content.get("revision"))]
    for label, value in bits:
        if value:
            para(f"<b>{escape(label)}:</b> {escape(str(value))}", markup=True)
    for heading, text in (("Summary", content.get("summary")), ("Scope", content.get("scope"))):
        if text:
            flow.append(Spacer(1, 6))
            para(heading, "Heading3")
            para(text)
    for heading, items in (("Conditions", [c["text"] + (f" (by {c['due_date']})" if c.get("due_date") else "")
                                           for c in content.get("conditions", [])]),
                           ("What we need from you", content.get("requester_actions", []))):
        if items:
            flow.append(Spacer(1, 6))
            para(heading, "Heading3")
            for n, item in enumerate(items, start=1):
                para(f"{n}. {item}")
    flow.append(Spacer(1, 10))
    para(content["limitations"], "Italic")
    doc.build(flow)
    return out.getvalue()


# ── Reading ─────────────────────────────────────────────────────────────────

def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(wanted))})", wanted).fetchall()
    return {r["id"]: r["full_name"] for r in rows}


def _present(db, row, app_name=None, org_name=None) -> dict:
    names = _names(db, [row["drafted_by"], row["approved_by"], row["exported_by"], row["sent_by"], row["withdrawn_by"]])
    preview = build_content(row, app_name or "", org_name)
    return {
        "id": row["id"], "application_id": row["application_id"], "intake_id": row["intake_id"], "revision": row["revision"],
        "status": row["status"], "version": row["version"], "outcome": row["outcome"], "outcome_label": OUTCOMES.get(row["outcome"]),
        "summary": row["summary"], "scope": row["scope_text"], "requester_actions": json.loads(row["requester_actions"] or "[]"),
        "conditions": json.loads(row["conditions"] or "[]"), "review_due": row["review_due"], "response_date": row["response_date"],
        "decision_date": row["decision_date"], "source_reference": row["source_reference"],
        "requester": json.loads(row["requester"] or "{}"), "content_hash": row["content_hash"],
        "preview": json.loads(row["content"]) if row["content"] else preview, "frozen": bool(row["content"]),
        "drafted_by": names.get(row["drafted_by"]), "drafted_at": service._text(row["drafted_at"]),
        "approved_by": names.get(row["approved_by"]), "approved_at": service._text(row["approved_at"]),
        "exported_by": names.get(row["exported_by"]), "exported_at": service._text(row["exported_at"]),
        "export_count": row["export_count"], "sent_by": names.get(row["sent_by"]), "sent_at": service._text(row["sent_at"]),
        "sent_channel": row["sent_channel"], "sent_reference": row["sent_reference"],
        "withdrawn_by": names.get(row["withdrawn_by"]), "withdrawn_at": service._text(row["withdrawn_at"]),
        "withdraw_reason": row["withdraw_reason"],
    }


def _app(db, user, application_id):
    if not describe_record(db, APP, application_id, user):
        return None
    return db.execute("SELECT a.id, a.name, a.business_unit_id, a.owner_user_id FROM applications a WHERE a.id = %s",
                      (application_id,)).fetchone()


def _org_name(db, user):
    if user.get("org_id") is None:
        return None
    row = db.execute("SELECT name FROM organizations WHERE id = %s", (user["org_id"],)).fetchone()
    return row["name"] if row else None


def _load(db, user, response_id):
    service._require(user, "ai_use.review")
    row = db.execute("SELECT * FROM ai_external_responses WHERE id = %s", (response_id,)).fetchone()
    if row is None or _app(db, user, row["application_id"]) is None:
        raise ServiceError(404, "Response not found.")
    if row["intake_id"] is not None:
        request = service._review_intake(db, user, row["intake_id"])
        if request["application_id"] != row["application_id"]:
            raise ServiceError(404, "Response not found.")
    elif row["requester"] not in (None, "", "{}") or row["source_reference"]:
        # A legacy unlinked response can carry a requester snapshot with no scoped
        # intake to authorize it against. Do not expose such a snapshot by app scope.
        raise ServiceError(404, "Response not found.")
    return row


def _standing(db, user, application_id):
    """The decision a response may rest on: the latest signed one, if it is an approval or a rejection and not revoked."""
    got = decisions.get_decisions(db, user, application_id)
    latest = got["latest"] if got else None
    # A decision that expired, was revoked, or no longer describes the use is not something to answer a requester with.
    if latest is None or got["state"]["state"] not in ("approved", "approved_with_conditions", "rejected"):
        return None, got
    return latest, got


def list_for_use(db, user, application_id: int, intake_id=None) -> "dict | None":
    service._require(user, "ai_use.review")
    app = _app(db, user, application_id)
    if app is None:
        return None
    if intake_id is not None:
        if isinstance(intake_id, bool) or not isinstance(intake_id, int) or intake_id < 0:
            raise ServiceError(400, "Choose a valid request.")
        if intake_id:
            request = service._review_intake(db, user, intake_id)
            if request["application_id"] != application_id:
                raise ServiceError(404, "Request not found.")
    scope, scope_params = service._review_scope(user, alias="r")
    visible_intakes = "SELECT r.id FROM ai_use_intake_requests r" + scope + " AND r.application_id = %s"
    if intake_id is None:
        rows = db.execute("SELECT * FROM ai_external_responses e WHERE e.application_id = %s "
                          "AND ((e.intake_id IS NULL AND e.requester = '{}' AND e.source_reference IS NULL) "
                          "OR e.intake_id IN (" + visible_intakes + ")) "
                          "ORDER BY e.id DESC LIMIT 50", (application_id, *scope_params, application_id)).fetchall()
    elif intake_id == 0:
        rows = db.execute("SELECT * FROM ai_external_responses e WHERE e.application_id = %s "
                          "AND e.intake_id IS NULL AND e.requester = '{}' AND e.source_reference IS NULL "
                          "ORDER BY e.id DESC LIMIT 50", (application_id,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM ai_external_responses e WHERE e.application_id = %s "
                          "AND e.intake_id = %s ORDER BY e.id DESC LIMIT 50", (application_id, intake_id)).fetchall()
    requests = db.execute("SELECT r.id, r.payload, r.source_ref, r.closed_at FROM ai_use_intake_requests r" + scope +
                          " AND r.application_id = %s AND r.status = 'approved' "
                          "ORDER BY r.id DESC LIMIT 50", (*scope_params, application_id)).fetchall()
    org = _org_name(db, user)
    latest, got = _standing(db, user, application_id)
    # "stands" says whether the decision a response rests on is still the one in force; only then can it be approved or sent.
    return {"responses": [{**_present(db, r, app["name"], org), "stands": latest is not None and r["decision_id"] == latest["id"]}
                          for r in rows],
            "requests": [{"id": r["id"], "name": str((service._json_object(r["payload"]) or {}).get("name") or
                                                   "Untitled request")[:120], "source_ref": r["source_ref"],
                          "closed": bool(r["closed_at"])}
                         for r in requests],
            "can_draft": latest is not None, "decision": ({"status": latest["status"], "decided_at": (latest["decided_at"] or "")[:10]}
                                                           if latest else None),
            "can": {"draft": has_capability(user, "ai_use.review"), "approve": has_capability(user, "ai_use.decide")}}


def get_response(db, user, response_id: int) -> dict:
    row = _load(db, user, response_id)
    app = _app(db, user, row["application_id"])
    return {"response": _present(db, row, app["name"], _org_name(db, user))}


# ── Drafting ────────────────────────────────────────────────────────────────

def _requester_from(db, user, application_id, intake_id):
    row = None
    if intake_id == 0 and not isinstance(intake_id, bool):
        return None, {}, None
    if intake_id is not None:
        if isinstance(intake_id, bool) or not isinstance(intake_id, int) or intake_id < 1:
            raise ServiceError(400, "Choose a valid request.")
        row = service._review_intake(db, user, intake_id)
        if row["application_id"] != application_id or row["status"] != "approved" or row["closed_at"]:
            raise ServiceError(404, "Request not found.")
    else:
        scope, scope_params = service._review_scope(user, alias="r")
        row = db.execute("SELECT r.id, r.requester, r.revision, r.source_kind "
                         "FROM ai_use_intake_requests r" + scope +
                         " AND r.application_id = %s AND r.status = 'approved' AND r.closed_at IS NULL "
                         "ORDER BY r.id DESC LIMIT 1", (*scope_params, application_id)).fetchone()
    if row is None:
        return None, {}, None
    data = json.loads(row["requester"] or "{}")
    reference = f"Request {row['id']}" + (f", revision {row['revision']}" if (row["revision"] or 1) > 1 else "")
    if data.get("source_form"):
        reference += f", from {data['source_form']}"
    return row["id"], {k: data.get(k) for k in ("name", "email", "organization") if data.get(k)}, reference


def create_draft(db, user, application_id: int, intake_id=None) -> dict:
    """Draft a response from the standing decision. Drafting again for the same decision returns the draft already there; a
    changed decision starts the next revision."""
    service._require(user, "ai_use.review")
    app = _app(db, user, application_id)
    if app is None:
        raise ServiceError(404, "AI use not found.")
    latest, got = _standing(db, user, application_id)
    if latest is None:
        raise ServiceError(409, "There is no standing decision to respond with. Ask for a decision first.")
    request_id, requester, reference = _requester_from(db, user, application_id, intake_id)
    request_filter = ("intake_id IS NULL AND requester = '{}' AND source_reference IS NULL"
                      if request_id is None else "intake_id = %s")
    request_params = () if request_id is None else (request_id,)
    last = db.execute("SELECT * FROM ai_external_responses WHERE application_id = %s AND " + request_filter +
                      " ORDER BY revision DESC, id DESC LIMIT 1", (application_id, *request_params)).fetchone()
    if last is not None and last["decision_id"] == latest["id"] and last["status"] != "withdrawn":
        return {"response": _present(db, last, app["name"], _org_name(db, user)), "created": False, "audit": [], "events": []}
    conditions = [{"text": c["text"], "due_date": c["due_date"]} for c in latest.get("conditions", []) if c["status"] == "open"]
    revision = (last["revision"] + 1) if last is not None else 1
    now = service._now()
    review_due = latest["expires_at"]
    if not review_due:
        profile = service.get_profile(db, user, application_id)
        review_due = (profile or {}).get("next_review_at")
        review_due = str(review_due)[:10] if review_due else None
    new_id = insert_returning_id(
        db,
        "INSERT INTO ai_external_responses (org_id, application_id, intake_id, business_unit_id, revision, supersedes_id, status, "
        "outcome, decision_id, decision_date, summary, scope_text, requester_actions, conditions, review_due, requester, "
        "source_reference, drafted_by, drafted_at, export_count, version, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s, %s, %s, NULL, NULL, '[]', %s, %s, %s, %s, %s, %s, 0, 1, %s, %s)",
        (user.get("org_id"), application_id, request_id, app["business_unit_id"], revision, last["id"] if last else None,
         latest["status"], latest["id"], (latest["decided_at"] or "")[:10] or None, json.dumps(conditions), review_due,
         json.dumps(requester), reference, user["id"], now, now, now))
    row = db.execute("SELECT * FROM ai_external_responses WHERE id = %s", (new_id,)).fetchone()
    return {"response": _present(db, row, app["name"], _org_name(db, user)), "created": True, "events": [],
            "audit": [("ai_response_drafted", "application", application_id, f"revision {revision}")]}


def update_draft(db, user, response_id: int, raw, expected_version) -> dict:
    row = _load(db, user, response_id)
    if not isinstance(raw, dict):
        raise ServiceError(400, "Send the fields as an object.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the response you are editing.")
    if row["status"] != "draft":
        raise ServiceError(409, "Only a draft can be edited. Draft a new revision to change what was approved.")
    sets = {}
    if "summary" in raw:
        sets["summary"] = _text(raw["summary"], "summary", SUMMARY_MAX)
    if "scope" in raw:
        sets["scope_text"] = _text(raw["scope"], "scope", SCOPE_MAX)
    if "requester_actions" in raw:
        sets["requester_actions"] = json.dumps(_actions(raw["requester_actions"]))
    if "response_date" in raw:
        sets["response_date"] = _day(raw["response_date"], "response date")
    if "review_due" in raw:
        sets["review_due"] = _day(raw["review_due"], "review date")
    if not sets:
        raise ServiceError(422, "Send at least one of the summary, scope, requester actions or dates.")
    columns = ", ".join(f"{c} = %s" for c in sets)
    moved = db.execute(f"UPDATE ai_external_responses SET {columns}, version = version + 1, updated_at = %s "
                       "WHERE id = %s AND version = %s AND status = 'draft'",
                       (*sets.values(), service._now(), response_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This draft was changed by someone else. Reload it and try again.")
    return {**get_response(db, user, response_id), "events": [],
            "audit": [("ai_response_edited", "application", row["application_id"], f"revision {row['revision']}")]}


# ── Approving, exporting, recording that it was sent ────────────────────────

def approve(db, user, response_id: int, expected_version) -> dict:
    """Freeze the draft under a hash. Needs the right to decide; the person who drafted it may not approve it where
    separation of duties is on, and the decision it rests on must still stand."""
    service._require(user, "ai_use.decide")
    row = _load(db, user, response_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the response you are approving.")
    if row["status"] != "draft":
        raise ServiceError(409, "Only a draft can be approved.")
    if ai_rollout.separation_required(user.get("org_id")) and row["drafted_by"] == user["id"]:
        raise ServiceError(403, "Someone other than the person who drafted the response has to approve it.")
    latest, _ = _standing(db, user, row["application_id"])
    if latest is None or latest["id"] != row["decision_id"]:
        raise ServiceError(409, "The decision this response rests on has changed. Draft a new revision.")
    missing = {"summary": row["summary"], "response date": row["response_date"]}
    absent = [k for k, v in missing.items() if not v]
    if absent:
        raise ServiceError(422, "Complete the response before approving it: " + ", ".join(absent) + ".",
                           errors={k.replace(" ", "_"): f"Give the {k}." for k in absent})
    app = _app(db, user, row["application_id"])
    content = build_content(row, app["name"], _org_name(db, user))
    now = service._now()
    moved = db.execute("UPDATE ai_external_responses SET status = 'approved', content = %s, content_hash = %s, approved_by = %s, "
                       "approved_at = %s, version = version + 1, updated_at = %s WHERE id = %s AND version = %s AND status = 'draft'",
                       (canonical(content), content_hash(content), user["id"], now, now, response_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This draft was changed by someone else. Reload it and try again.")
    return {**get_response(db, user, response_id), "events": [],
            "audit": [("ai_response_approved", "application", row["application_id"], f"revision {row['revision']}")]}


def export(db, user, response_id: int, fmt: str) -> dict:
    """The frozen document as JSON or PDF, and the record that it was taken out. The hash is checked first, so a document
    that no longer matches its frozen content is never handed over, and a response whose decision stopped standing is not
    exported."""
    row = _load(db, user, response_id)
    if fmt not in FORMATS:
        raise ServiceError(400, "Choose json or pdf.")
    if row["status"] not in ("approved", "exported", "sent"):
        raise ServiceError(409, "Only an approved response can be exported.")
    try:
        content = json.loads(row["content"])
    except (TypeError, ValueError):
        content = None
    if not isinstance(content, dict) or content_hash(content) != row["content_hash"]:
        raise ServiceError(409, "This response no longer matches the content that was approved, so it cannot be exported.")
    latest, _ = _standing(db, user, row["application_id"])
    if latest is None or latest["id"] != row["decision_id"]:
        raise ServiceError(409, "The decision this response rests on no longer stands. Draft a new revision.")
    now = service._now()
    status = "exported" if row["status"] == "approved" else row["status"]
    db.execute("UPDATE ai_external_responses SET status = %s, exported_by = %s, exported_at = %s, export_count = export_count + 1, "
               "version = version + 1, updated_at = %s WHERE id = %s", (status, user["id"], now, now, response_id))
    if fmt == "pdf":
        body, media, extension = render_pdf(content), "application/pdf", "pdf"
    else:
        body, media, extension = json.dumps({"response": content, "hash": row["content_hash"],
                                              "hash_method": "sha256 of the response as JSON with sorted keys and no spaces"},
                                             indent=2, ensure_ascii=False).encode("utf-8"), "application/json", "json"
    return {"body": body, "media_type": media, "filename": f"ai-use-response-r{row['revision']}.{extension}", "events": [],
            "audit": [("ai_response_exported", "application", row["application_id"], f"revision {row['revision']} as {fmt}")]}


def mark_sent(db, user, response_id: int, sent_at, channel, reference, expected_version) -> dict:
    row = _load(db, user, response_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the response you are recording.")
    if row["status"] != "exported":
        raise ServiceError(409, "Export the response before recording that it was sent. A download is not a delivery.")
    day = _day(sent_at, "date sent", required=True)
    channel = _text(channel, "channel", CHANNEL_MAX, required=True)
    reference = _text(reference, "reference", REFERENCE_MAX)
    now = service._now()
    moved = db.execute("UPDATE ai_external_responses SET status = 'sent', sent_by = %s, sent_at = %s, sent_channel = %s, "
                       "sent_reference = %s, version = version + 1, updated_at = %s WHERE id = %s AND version = %s "
                       "AND status = 'exported'", (user["id"], day, channel, reference, now, response_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This response was changed by someone else. Reload it and try again.")
    return {**get_response(db, user, response_id), "events": [],
            "audit": [("ai_response_sent", "application", row["application_id"], f"revision {row['revision']} via {channel}")]}


def withdraw(db, user, response_id: int, reason, expected_version) -> dict:
    row = _load(db, user, response_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the response you are withdrawing.")
    if row["status"] == "withdrawn":
        raise ServiceError(409, "This response was already withdrawn.")
    reason = _text(reason, "reason", REASON_MAX, required=True)
    now = service._now()
    moved = db.execute("UPDATE ai_external_responses SET status = 'withdrawn', withdrawn_by = %s, withdrawn_at = %s, "
                       "withdraw_reason = %s, version = version + 1, updated_at = %s WHERE id = %s AND version = %s "
                       "AND status != 'withdrawn'", (user["id"], now, reason, now, response_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This response was changed by someone else. Reload it and try again.")
    return {**get_response(db, user, response_id), "events": [],
            "audit": [("ai_response_withdrawn", "application", row["application_id"], f"revision {row['revision']}")]}
