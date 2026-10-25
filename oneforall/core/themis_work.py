"""Read-only, source-linked answers for work already open in ThemisIQ.

The page path is a candidate ID, never authority. Owning AI Governance services
recheck the signed-in viewer before any case fact is returned. This adapter does
not call an AI provider, cache case data or mutate a source record.
"""

import logging
import re
from urllib.parse import parse_qs, urlsplit

from core.rbac import has_capability

log = logging.getLogger(__name__)

_SYSTEM = re.compile(r"/ai-governance/systems/([1-9][0-9]{0,8})/?\Z")
_REQUEST = re.compile(r"/ai-governance/requests/([1-9][0-9]{0,8})/?\Z")
_AUDIT = re.compile(r"/grid/audits/([1-9][0-9]{0,8})/?\Z")
_RECORD_ID = re.compile(r"[1-9][0-9]{0,8}\Z")
_AI = re.compile(r"\b(?:ai|artificial intelligence)\b", re.I)
_ONBOARD = re.compile(r"\b(?:onboard|onboarding|introduce|deploy|adopt|register|new|bring in)\b", re.I)
_USE = re.compile(r"\b(?:model|tool|system|use|chatbot|copilot|application)\b", re.I)
_CASE = re.compile(r"\b(?:status|state|why|next|block\w*|outstand\w*|miss\w*|ready|"
                   r"decision|approv\w*|assess\w*|evidence|review|explain|submit|progress)\b", re.I)
_RELATED = re.compile(r"\b(?:relat\w*|linked|connected|relationship|evidence|proof|document|changes?|changed|signal)\b", re.I)
_PROOF = re.compile(r"\b(?:evidence|proof|document|file)\b", re.I)
_CHANGES = re.compile(r"\b(?:changes?|changed|signal)\b", re.I)
_DRAFT = re.compile(r"^(?:draft|prepare|write)\b", re.I)
_FOLLOW_UP = re.compile(r"\b(?:follow[ -]?up|questions?|clarification)\b", re.I)
_ASSESSMENT = re.compile(r"\b(?:assessment|review)\s+(?:note|summary)\b|\bnote\b", re.I)
_REPLY = re.compile(r"\b(?:external|reply|response|respond)\b", re.I)

# Fixed SQL shapes; the page and any selected-record hint are only candidate IDs.
# The shared entity scope is repeated on the fact query after describe_record.
_OTHER = {
    ("grid", "audit"): ("grid_audits", "status, end_date", "Audit"),
    ("grid", "control"): ("grid_controls", "status, due_date", "Audit control"),
    ("bcm", "incident"): ("bcm_incidents", "status, severity, updated_at", "Continuity incident"),
    ("sentinel", "breach"): ("sentinel_breaches", "status, severity, updated_at", "Privacy breach"),
    ("erm", "risk"): ("erm_enterprise_risks", "status, review_date, updated_at", "Enterprise risk"),
    ("sentinel", "dpia"): ("sentinel_dpias", "status, overall_risk, updated_at", "Privacy impact assessment"),
    ("evidence", "item"): ("evidence_items", "status, version, expiry_date, updated_at", "Vault artifact"),
}
_OPEN_PAGES = {
    "/grid/": {"control": ("grid", "control")},
    "/grid/controls": {"control": ("grid", "control")},
    "/bcm/": {"incident": ("bcm", "incident")},
    "/sentinel/": {"dpia": ("sentinel", "dpia"), "breach": ("sentinel", "breach")},
    "/erm/": {"risk": ("erm", "risk")},
    "/erm/register": {"risk": ("erm", "risk")},
    "/evidence/": {"item": ("evidence", "item")},
}


def _selected_other(page):
    if not isinstance(page, str) or len(page) > 200 or "\\" in page or "#" in page:
        return None
    try:
        parsed = urlsplit(page)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    audit = _AUDIT.fullmatch(parsed.path)
    if audit and not parsed.query:
        return ("grid", "audit"), int(audit.group(1))
    options = _OPEN_PAGES.get(parsed.path)
    if not options:
        return None
    params = parse_qs(parsed.query, keep_blank_values=True)
    if set(params) != {"open"} or len(params["open"]) != 1:
        return None
    kind, sep, ident = params["open"][0].partition(":")
    if not sep or kind not in options or not _RECORD_ID.fullmatch(ident):
        return None
    return options[kind], int(ident)


def _action(label, path):
    return {"label": label, "path": path}


def _source(label, path, updated_at=None, version=None, **reference):
    return {"label": label, "path": path, "updated_at": updated_at, "version": version, **reference}


def _brief(value, limit=180):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _unavailable():
    # Same answer for an inaccessible, removed or nonexistent record.
    return {"answer": "I cannot open that record in your current scope. Choose a record you can open in its module.",
            "source": "unavailable", "actions": [], "sources": []}


def _onboard(user, areas):
    if "ai_governance" not in areas:
        return {"answer": "AI Governance is not available to your current role or organization.",
                "source": "guide", "actions": [], "sources": []}
    can_create = has_capability(user, "ai_use.intake_create")
    can_review = has_capability(user, "ai_use.review")
    actions = [_action("Search existing AI systems", "/ai-governance/systems")]
    if can_create:
        actions.append(_action("Register an AI use", "/ai-governance/register"))
    if can_review:
        actions.append(_action("Import form responses", "/ai-governance/import"))
        if not can_create:
            actions.append(_action("Review requests", "/ai-governance/review"))
    if not (can_create or can_review):
        return {"answer": "Check the AI systems already in your scope. Your current role cannot start or review an AI use.",
                "source": "guide", "actions": actions, "sources": []}
    start = ("Register the proposed AI use, or import a response from an external request form. " if can_create and can_review
             else "Register the proposed AI use. " if can_create
             else "Import the requester's form response or open the review queue. ")
    return {"answer": (
        "Start by checking the AI systems already recorded for your organization. " + start +
        "A specialist checks for an existing system, resolves missing information and assesses the use. "
        "Accepting a request into the inventory is separate from a decision to approve its operation."),
        "source": "guide", "actions": actions[:3], "sources": []}


def _request_answer(db, user, request_id):
    from modules.ai_governance import questions, rules, service

    # Mirror the HTML request page's capability gate before reading the row.
    if not (has_capability(user, "ai_use.submit") or has_capability(user, "ai_use.review")):
        return _unavailable()
    try:
        intake = service.get_intake(db, user, request_id)
    except service.ServiceError as exc:
        if exc.status in (403, 404):
            return _unavailable()
        raise

    path = f"/ai-governance/requests/{request_id}"
    status = intake["status"]
    answers = intake["answers"]
    missing = rules.missing_for_submit(answers) if status in ("draft", "returned") else []
    actions = [_action("Open this request", path)]
    sources = [_source("AI use request", path, intake.get("updated_at"), intake.get("version"))]
    if status == "draft":
        if missing:
            labels = ", ".join(rules.label(field) for field in missing[:5])
            extra = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            answer = f"This request is a draft. Before submission, complete: {labels}{extra}."
        else:
            answer = "This draft has the required submission answers. Open it to review the details and submit it for specialist review."
    elif status == "returned":
        answer = "This request was returned for more information. "
        if intake.get("review_note"):
            answer += "Recorded reviewer note: " + _brief(intake["review_note"], 220) + " "
        if missing:
            labels = ", ".join(rules.label(field) for field in missing[:5])
            extra = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            answer += f"Required answers still missing: {labels}{extra}. "
        answer += "Open the request to resolve the questions and resubmit."
    elif status == "submitted":
        answer = "This request has been submitted for specialist review. Open it to see its current details and any questions."
    elif status == "approved":
        answer = "A specialist accepted this request into the AI inventory. That does not itself approve the AI use for operation; check its separate decision record."
        if intake.get("application_id") and has_capability(user, "ai_use.view"):
            from modules.governance.entity_scope import describe_record
            application_id = intake["application_id"]
            if describe_record(db, service.APP, application_id, user):
                actions.append(_action("Open the AI decision", f"/ai-governance/systems/{application_id}#decisions"))
    elif status == "rejected":
        answer = "This request was rejected. "
        if intake.get("review_note"):
            answer += "Recorded reviewer note: " + _brief(intake["review_note"], 220) + " "
        answer += "Open the recorded review for the full reason; a new decision requires the governance workflow."
    else:
        answer = "Open this AI use request to inspect its current state and next authorized action."

    if status in ("draft", "returned", "submitted") and has_capability(user, "ai_use.view"):
        asked = questions.list_questions(db, user, request_id)
        if asked["open"]:
            answer += f" {asked['open']} question(s) are awaiting a recorded answer."

    # The duplicate service itself applies the caller's application scope. A
    # possible match is a lead to review, never an assertion of identity.
    if (status in ("draft", "returned", "submitted")
            and has_capability(user, "ai_use.intake_create") and has_capability(user, "ai_use.view")):
        duplicates = service.find_duplicates(db, user, answers.get("name"), answers.get("provider_name"), limit=2)
        if duplicates:
            answer += " I also found possible existing AI systems; compare them before creating another record."
            for match in duplicates[:2]:
                actions.append(_action("Compare: " + match["name"], match["url"]))
                sources.append(_source(match["name"] + " (" + match["reason"] + ")", match["url"]))

    return {"answer": answer, "source": "records", "actions": actions[:3], "sources": sources[:3],
            "reply_context": {"status": status, "missing": [rules.label(field) for field in missing[:5]]}}


def _system_answer(db, user, application_id):
    from modules.ai_governance import decisions, outstanding, service

    if not has_capability(user, "ai_use.view"):
        return _unavailable()
    state = decisions.get_decisions(db, user, application_id)
    if state is None:
        return _unavailable()
    path = f"/ai-governance/systems/{application_id}"
    label = state["state"]["label"]
    profile = service.get_profile(db, user, application_id)
    work = outstanding.get_outstanding(db, user, application_id)
    sources = [_source("AI use and decision record", path + "#decisions",
                       profile.get("updated_at") if profile else None,
                       profile.get("version") if profile else None)]
    actions = [_action("Open this AI use", path), _action("Review the decision", path + "#decisions")]
    if work is None:
        return _unavailable()
    open_lines = [line for line in work["lines"] if line["state"] not in ("complete", "not_applicable", "no_access")]
    unread = [line for line in work["lines"] if line["state"] in ("unavailable", "no_access")]
    blocking = [line for line in open_lines if line["blocks_decision"] and line["state"] != "unavailable"]
    priority = blocking or [line for line in open_lines if line["state"] != "unavailable"]
    answer = f"Recorded decision state: {label}. "
    reasons = state["state"].get("reasons") or []
    if reasons:
        answer += "Reason recorded by the decision rules: " + _brief(" ".join(str(reason) for reason in reasons[:2])) + " "
    if priority:
        details = [f"{line['title']} ({line['state_label']}): {_brief(line['reason']) or 'open the owning record'}"
                   for line in priority[:2]]
        answer += "Work to review: " + "; ".join(details) + ". "
        if len(priority) > 2:
            answer += f"There are {len(priority) - 2} more open item(s) in the connected work view. "
    elif not profile:
        answer += "The AI use has no profile yet. "
    elif not unread:
        answer += "The connected work view shows no unfinished item. "
    if unread:
        answer += "Some connected records could not be checked with your access or are temporarily unavailable. "
    answer += "Open the recorded decision and conditions before treating this use as approved for operation."
    sources.append(_source("Connected work", path + "#assessments",
                           profile.get("updated_at") if profile else None, work.get("rule_version")))
    for line in priority[:1]:
        resolution = line.get("resolution") or {}
        if resolution.get("url"):
            actions.append(_action(resolution.get("label") or "Open the work", resolution["url"]))
        for record in line.get("records") or []:
            if record.get("url") and len(sources) < 3:
                sources.append(_source(record["title"], record["url"], record.get("updated_at"), record.get("version")))
    return {"answer": answer, "source": "records", "actions": actions[:3], "sources": sources[:3]}


def _other_answer(db, user, selected):
    from modules.governance.entity_scope import describe_record, entity_scope_sql

    key, record_id = selected
    shown = describe_record(db, key, record_id, user)
    if shown is None:
        return _unavailable()
    table, columns, label = _OTHER[key]
    scope, params = entity_scope_sql(key, user, "t")
    row = db.execute(f"SELECT {columns} FROM {table} t WHERE t.id = %s AND {scope}",
                     [record_id, *params]).fetchone()
    if row is None:
        return _unavailable()
    status = _brief(row["status"] or "unrecorded", 60)
    path = f"/grid/controls?open=control:{record_id}" if key == ("grid", "control") else shown["url"]
    parts = [f"{label} recorded state: {status}."]
    next_step = "Open the source record and confirm the next action with its owner."
    if key == ("sentinel", "dpia"):
        risk = _brief(row["overall_risk"], 60) if row["overall_risk"] else "unrated"
        parts.append(f"Assessor-entered overall risk: {risk}.")
        if risk == "unrated":
            next_step = "Ask the assessor to record an overall risk; the legacy risk default is not an assessment."
    elif key == ("evidence", "item"):
        parts.append(f"Version: {row['version'] or 'unrecorded'}.")
        if row["expiry_date"]:
            parts.append(f"Recorded expiry date: {_brief(row['expiry_date'], 30)}.")
        next_step = "Check the file, version, expiry and its linked review outcome before treating it as accepted proof."
    else:
        if "severity" in row.keys() and row["severity"]:
            parts.append(f"Recorded severity: {_brief(row['severity'], 40)}.")
        if "due_date" in row.keys() and row["due_date"]:
            parts.append(f"Recorded due date: {_brief(row['due_date'], 30)}.")
        if "end_date" in row.keys() and row["end_date"]:
            parts.append(f"Planned audit end: {_brief(row['end_date'], 30)}.")
        if "review_date" in row.keys() and row["review_date"]:
            parts.append(f"Recorded review date: {_brief(row['review_date'], 30)}.")
    parts.append(next_step)
    return {"answer": " ".join(parts), "source": "records",
            "actions": [_action("Open source record", path)],
            "sources": [_source(label, path, row["updated_at"] if "updated_at" in row.keys() else None,
                                row["version"] if "version" in row.keys() else None)]}


def _related_answer(db, user, key, record_id, question):
    """Answer from one hop of live, visible connections; never infer unseen neighbours."""
    from modules.governance import change_signals, entity360, relationships
    from modules.governance.entity_scope import describe_record

    if key == ("governance", "application") and not has_capability(user, "ai_use.view"):
        return _unavailable()
    shown = describe_record(db, key, record_id, user)
    if shown is None:
        return _unavailable()
    root = _source(_brief(shown["title"], 100), shown["url"], record_id=record_id)
    sources = [root]
    connected = f"/governance/connected/{key[0]}/{key[1]}/{record_id}"
    actions = [_action("Open connected records", connected)]

    if _PROOF.search(question):
        proof = entity360.proof_of(db, user, key[0], key[1], record_id)
        if proof is None:
            return _unavailable()
        if proof["state"] == "unavailable":
            answer = "I can't verify this record's Vault proof right now. Open the source record and try again. [1]"
        elif not proof["items"]:
            answer = "I can't verify a Vault file linked to this record in your current scope. [1]"
        else:
            lines = []
            for item in proof["items"][:2]:
                sources.append(_source(_brief(item["title"], 100), item["url"],
                                       version=item.get("version"), record_id=item["id"]))
                lines.append(f"{_brief(item['title'], 100)}: {item['state']} [{len(sources)}]")
            answer = "Linked Vault artifact metadata I can verify for this record [1]: " + "; ".join(lines) + "."
            if len(proof["items"]) > 2:
                answer += " Open connected records for the remaining visible files."
            if len(proof["items"]) >= 50:
                answer += " The connected view is bounded; this is not a complete-file count."
    elif _CHANGES.search(question):
        signals = change_signals.for_entity(db, user, key, record_id, limit=10)
        if not has_capability(user, "ai_use.view"):
            signals = [s for s in signals if not any(
                (s.get(end) or {}).get("module") == "governance"
                and (s.get(end) or {}).get("entity_type") == "application"
                for end in ("source", "target"))]
        if not signals:
            answer = "I can't verify a recorded change signal for this record in your current scope. [1]"
        else:
            lines = []
            for signal in signals[:2]:
                origin = signal["source"]
                root_changed = (origin["module"], origin["entity_type"], origin["entity_id"]) == (
                    key[0], key[1], record_id)
                other = signal["target"] if root_changed else origin
                sources.append(_source(_brief(other["title"], 100), other["url"],
                                       updated_at=signal.get("changed_at"), record_id=other["entity_id"],
                                       signal_id=signal["signal_id"]))
                direction = "on this record, affecting" if root_changed else "in"
                lines.append(f"{_brief(signal['kind_label'], 80)} {direction} {_brief(other['title'], 100)} "
                             f"({signal['status']}) [{len(sources)}]")
            answer = "Recorded change signals for this record [1]: " + "; ".join(lines) + "."
            if len(signals) > 2:
                answer += " Open connected records for the remaining visible signals."
            if len(signals) >= 10:
                answer += " This is a bounded view, not a complete history."
    else:
        links = relationships.list_links(db, user, key, record_id, limit=10)
        if not has_capability(user, "ai_use.view"):
            links = [link for link in links if (link["module"], link["entity_type"]) !=
                     ("governance", "application")]
        if not links:
            answer = "I can't verify a confirmed related record I can open in your current scope. [1]"
        else:
            lines = []
            for link in links[:2]:
                sources.append(_source(_brief(link["title"], 100), link["url"],
                                       record_id=link["entity_id"], relationship_id=link["link_id"]))
                lines.append(f"{_brief(link['title'], 100)} ({_brief(link['label'], 70)}) [{len(sources)}]")
            answer = "Confirmed connections of this record [1]: " + "; ".join(lines) + "."
            if len(links) > 2:
                answer += " Open connected records for the remaining visible links."
            if len(links) >= 10:
                answer += " This is a bounded view, not a complete relationship count."
    return {"answer": answer, "source": "records", "actions": actions, "sources": sources}


def _request_related_answer(db, user, request_id, question):
    """A request is not a graph root until a specialist has linked an AI use."""
    from modules.ai_governance import service

    if not (has_capability(user, "ai_use.submit") or has_capability(user, "ai_use.review")):
        return _unavailable()
    try:
        intake = service.get_intake(db, user, request_id)
    except service.ServiceError as exc:
        if exc.status in (403, 404):
            return _unavailable()
        raise
    application_id = intake.get("application_id")
    if application_id and has_capability(user, "ai_use.view"):
        return _related_answer(db, user, ("governance", "application"), application_id, question)
    path = f"/ai-governance/requests/{request_id}"
    return {"answer": "I can't verify connected AI-system records from this request in your current scope. "
                      "Open the request to check its review state. [1]",
            "source": "records", "actions": [_action("Open this request", path)],
            "sources": [_source("AI use request", path, intake.get("updated_at"), intake.get("version"),
                                record_id=request_id)]}


def _draft_result(question, result, selected):
    """Deterministic private preview. The browser may copy it; no record or mail is written."""
    if result.get("source") != "records" or not result.get("sources"):
        return result
    source = result["sources"][0]
    path = source["path"]
    if _FOLLOW_UP.search(question):
        body = ("For this recorded position: " + result["answer"] + "\n\n"
                "1. Please confirm who owns the next action and its due or review date.\n"
                "2. What information or accepted evidence is still needed?\n"
                "3. Which source record and version supports the response?")
        kind = "Follow-up questions"
    elif _ASSESSMENT.search(question):
        body = ("Recorded position: " + result["answer"] + "\n\n"
                "Specialist review needed: verify the source, scope, outstanding evidence and decision authority. "
                "No conclusion or approval is recorded by this draft.")
        kind = "Assessment note"
    elif _REPLY.search(question):
        context = result.get("reply_context")
        if not context:
            return {"answer": "External replies are available for AI use requests after a specialist opens the request.",
                    "source": "guide", "actions": result["actions"], "sources": result["sources"]}
        state = context["status"]
        state_text = {
            "draft": "The request is still a draft and has not been submitted for specialist review.",
            "returned": "The request has been returned for more information.",
            "submitted": "The request is with the governance team for review.",
            "approved": "The request has been accepted into the AI inventory. A separate operational decision may still be required.",
            "rejected": "The request was not accepted into the AI inventory. Please contact the governance team for the recorded reasons.",
        }.get(state, "Please contact the governance team for a status update.")
        body = "Thank you for your AI use request. " + state_text
        if context["missing"]:
            body += " To continue, please provide: " + ", ".join(context["missing"]) + "."
        body += " Please respond through the agreed channel. This message is subject to specialist review before sending."
        kind = "External reply"
    else:
        return {"answer": "Choose a draft type: follow-up questions, assessment note, or external reply.",
                "source": "guide", "actions": result["actions"], "sources": result["sources"]}
    if kind != "External reply":
        body += f"\n\nInternal source for review: {path}"
    return {"answer": f"{kind} preview. Review and edit before using it. Nothing has been saved or sent.",
            "source": "draft", "draft": body, "actions": result["actions"], "sources": result["sources"]}


def maybe_answer(question, page, user, areas, db_factory):
    """Return a local work answer, or None for the existing platform guide.

    Only exact supported workspace paths are accepted as candidate records.
    The owning scope still authorizes each read. A source outage is never
    rewritten as a clean state.
    """
    if not isinstance(page, str) or len(page) > 200 or "\\" in page:
        return None
    try:
        parsed = urlsplit(page)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    system, intake = _SYSTEM.fullmatch(path), _REQUEST.fullmatch(path)
    other = _selected_other(page)
    drafting = bool(_DRAFT.search(question))
    related = bool(_RELATED.search(question))
    if not ((system or intake or other) and (_CASE.search(question) or related or drafting)):
        if _AI.search(question) and _ONBOARD.search(question) and _USE.search(question):
            return _onboard(user, areas)
        return None
    if (system or intake) and "ai_governance" not in areas:
        return _unavailable()
    db = None
    try:
        db = db_factory()
        if related and system:
            result = _related_answer(db, user, ("governance", "application"), int(system.group(1)), question)
        elif related and intake:
            result = _request_related_answer(db, user, int(intake.group(1)), question)
        elif related and other:
            result = _related_answer(db, user, other[0], other[1], question)
        elif system:
            result = _system_answer(db, user, int(system.group(1)))
        elif intake:
            result = _request_answer(db, user, int(intake.group(1)))
        else:
            result = _other_answer(db, user, other)
        return _draft_result(question, result, other) if drafting else result
    except Exception as exc:
        log.warning("Themis selected record read failed (%s)", type(exc).__name__)
        return {"answer": "The current record could not be checked. Please open it directly and try again later.",
                "source": "unavailable", "actions": [], "sources": []}
    finally:
        if db is not None:
            db.close()
