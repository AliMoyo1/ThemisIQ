"""
Material change signals (plans/2026-10-governance-rework/03 section 1 and 2).

When a record that others depend on changes (an application's criticality, hosting or provider, a process's recovery
targets, a vendor's risk level, a control's status, a finding's severity, a file replaced by a new version), the records
connected to it should be looked at again. This module publishes that fact once, finds the connected records, and lets each
one's owner confirm that it needs a second look or dismiss the signal with a reason:

* **One signal per change.** The same change published again the same day is the same signal (a unique key), so a retry or a
  double save never doubles the work. A change nothing is connected to is not recorded at all.
* **Nothing is changed in the affected record.** A signal never edits, closes, re-opens or re-scores anything. Its owner
  decides, and confirming only opens a task: an earlier decision, approval or assessment keeps the basis it was made on.
* **Scope is applied on reading, to both ends.** A person sees a signal only when they may open the record to look at and the
  record that changed, as with a link. Otherwise it answers like one that does not exist: a hidden record is never named,
  counted or hinted at, and no title is stored with the signal.
* **A failure here never costs the edit.** Publishing runs in a savepoint; if it fails the change is saved and the failure is
  logged.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from decimal import Decimal

from core.best_effort import attempt
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.governance.entity_scope import canonical_key, describe_record, describe_records, is_linkable, kind_table
from modules.governance.relationships import _row_ends, _side_sql

log = logging.getLogger("oneforall.change_signals")

REASON_MAX = 500
MAX_TARGETS = 200
BRIEF_MAX = 120

APPLICATION_FIELDS = {"criticality": "Criticality", "hosting": "Hosting", "vendor_id": "Provider", "application_type": "Type",
                      "business_unit_id": "Business unit", "owner_user_id": "Owner", "is_active": "In use"}
PROCESS_FIELDS = {"criticality": "Criticality", "rto_hours": "Recovery time objective (hours)",
                  "rpo_hours": "Recovery point objective (hours)", "business_unit_id": "Business unit",
                  "owner_user_id": "Owner", "is_active": "In use"}

# The records other records depend on: key -> (what it is called, {column: label of each field that matters to the records
# connected to it}). The table comes from the registry in entity_scope, which already names every linkable kind.
WATCHED = {
    ("governance", "application"): ("An application", APPLICATION_FIELDS),
    ("governance", "process"): ("A business process", PROCESS_FIELDS),
    ("governance", "data_asset"): ("A data asset", {
        "classification": "Classification", "contains_pii": "Holds personal data", "contains_phi": "Holds health data",
        "contains_financial": "Holds financial data", "contains_ip": "Holds intellectual property",
        "application_id": "System", "business_unit_id": "Business unit", "owner_user_id": "Owner", "is_active": "In use"}),
    ("sentinel", "vendor"): ("A vendor", {"risk_level": "Risk level", "dpa_status": "Data processing agreement"}),
    ("grid", "vendor"): ("A vendor", {"risk_level": "Risk level", "status": "Status"}),
    ("bcm", "vendor"): ("A vendor", {"criticality": "Criticality", "tier": "Tier", "risk_score": "Risk score", "status": "Status"}),
    ("sentinel", "ropa"): ("A processing record", {
        "legal_basis": "Legal basis", "special_categories": "Special categories",
        "intl_transfers": "International transfers", "risk_level": "Risk level", "status": "Status"}),
    ("sentinel", "dpia"): ("A privacy impact assessment", {
        "overall_risk": "Overall risk", "residual_risk": "Residual risk", "status": "Status"}),
    ("sentinel", "breach"): ("A breach", {
        "severity": "Severity", "status": "Status", "regulation": "Regulation", "discovery_date": "Discovery date",
        "notification_required": "Notification required"}),
    ("sentinel", "dsr"): ("A data subject request", {"status": "Status", "deadline_date": "Deadline"}),
    ("aria", "control"): ("A control", {"status": "Status", "owner": "Owner", "version": "Version"}),
    ("grid", "audit"): ("An audit", {"status": "Status"}),
    ("grid", "control"): ("An audit control", {"status": "Status", "risk_level": "Risk level"}),
    ("grid", "nc"): ("A finding", {"severity": "Severity", "status": "Status", "due_date": "Due date"}),
    ("bcm", "plan"): ("A continuity plan", {"status": "Status", "version": "Version", "next_review": "Next review"}),
    ("bcm", "bia"): ("A business impact analysis", {
        "rto_hours": "Recovery time objective (hours)", "rpo_hours": "Recovery point objective (hours)",
        "criticality": "Criticality"}),
    ("bcm", "incident"): ("An incident", {"severity": "Severity", "status": "Status"}),
    ("bcm", "exercise"): ("An exercise", {"status": "Status", "outcome": "Outcome"}),
    ("bcm", "risk"): ("A continuity risk", {"likelihood": "Likelihood", "impact": "Impact", "treatment": "Treatment",
                                             "status": "Status"}),
    ("erm", "risk"): ("An enterprise risk", {
        "likelihood": "Likelihood", "impact": "Impact", "residual_likelihood": "Residual likelihood",
        "residual_impact": "Residual impact", "treatment": "Treatment", "status": "Status"}),
    ("orm", "event"): ("An operational event", {"severity": "Severity", "status": "Status"}),
    ("orm", "kri"): ("A key risk indicator", {"status": "Status", "trend": "Trend"}),
}
VENDOR_KEYS = (("sentinel", "vendor"), ("grid", "vendor"), ("bcm", "vendor"))
_KIND_OF = {"application": "application_changed", "process": "process_changed", "vendor": "vendor_changed"}
# Signals that are not "a watched record changed in its own table".
KIND_LABELS = {
    "evidence_replaced": "A file was replaced by a new version",
    "policy_approved": "A policy version was approved",
    "ai_use_decided": "A decision was made on an AI use",
    "ai_use_revoked": "The approval of an AI use was revoked",
    "ai_use_changed": "An AI use changed in a way its approval covered",
}


class SignalError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _shown(value):
    """How a value is compared and displayed: an empty one is None, and 2.0 is the same as 2."""
    if value in (None, ""):
        return None
    if isinstance(value, (float, Decimal)):
        try:
            if value == int(value):
                value = int(value)
        except (ValueError, ArithmeticError):  # nan and infinity stay as they are
            pass
    return str(value)


def _brief(value):
    """What is stored and shown of a value: the start of it, so that a long text is not copied into another table."""
    text = _shown(value)
    return text if text is None or len(text) <= BRIEF_MAX else text[:BRIEF_MAX - 3] + "..."


def _kind_label(kind: str, source_key) -> str:
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    watched = WATCHED.get(source_key)
    return f"{watched[0]} changed" if watched else "A record changed"


def _affected(db, skey, source_id: int) -> list:
    """The confirmed connections of a record, in both directions, as [(key, id)]."""
    side_src, p_src = _side_sql("source", skey)
    side_dst, p_dst = _side_sql("target", skey)
    rows = db.execute(
        "SELECT source_module, source_type, source_id, target_module, target_type, target_id FROM cross_module_links "
        f"WHERE COALESCE(status, 'confirmed') = 'confirmed' AND (({side_src} AND source_id = %s) OR ({side_dst} AND target_id = %s)) "
        "ORDER BY id LIMIT %s", [*p_src, source_id, *p_dst, source_id, MAX_TARGETS]).fetchall()
    found = []
    for row in rows:
        (a_key, a_id), (b_key, b_id) = _row_ends(row)
        other = (b_key, b_id) if (a_key == skey and a_id == source_id) else (a_key, a_id)
        if is_linkable(other[0]) and other != (skey, source_id) and other not in found:
            found.append(other)
    return found


def publish(db, *, source: tuple, kind: str, before: dict, after: dict, fields: dict, actor_id=None, org_id=None,
            extra_targets=()) -> "int | None":
    """Record that `source` ((module, type, id)) changed in the `fields` ({column: label}) that matter, and open a target for
    each record connected to it. Returns the signal id, or None when nothing that matters changed, the same change was already
    published today, or publishing failed (logged; the caller's own change is unaffected)."""
    changes = [{"field": f, "label": label, "before": _brief(before.get(f)), "after": _brief(after.get(f))}
               for f, label in fields.items() if _shown(before.get(f)) != _shown(after.get(f))]
    if not changes:
        return None
    skey = canonical_key(source[0], source[1])
    source_id = int(source[2])
    day = utcnow().strftime("%Y-%m-%d")
    whole = json.dumps([[f, _shown(before.get(f)), _shown(after.get(f))] for f in fields
                        if _shown(before.get(f)) != _shown(after.get(f))], sort_keys=True)
    key = hashlib.sha256(f"{org_id}|{skey[0]}|{skey[1]}|{source_id}|{kind}|{whole}|{day}".encode()).hexdigest()
    result = {"id": None}
    with attempt(db, f"publishing a change signal for {skey[0]}/{skey[1]} {source_id}"):
        targets = _affected(db, skey, source_id)
        for extra in extra_targets:
            ek = canonical_key(extra[0], extra[1])
            if is_linkable(ek) and (ek, extra[2]) not in targets and (ek, extra[2]) != (skey, source_id):
                targets.append((ek, extra[2]))
        if not targets:
            return None  # nobody is connected to it: a row that no one would ever read is not written
        signal_id = insert_returning_id(
            db, "INSERT INTO change_signals (org_id, source_module, source_type, source_id, change_kind, changes, changed_by, "
                "created_at, dedup_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (org_id, skey[0], skey[1], source_id, kind, json.dumps(changes), actor_id, _now(), key))
        if signal_id is None:
            return None
        for (tkey, tid) in targets[:MAX_TARGETS]:
            db.execute(
                "INSERT INTO change_signal_targets (signal_id, org_id, target_module, target_type, target_id, status) "
                "VALUES (%s, %s, %s, %s, %s, 'open') ON CONFLICT DO NOTHING", (signal_id, org_id, tkey[0], tkey[1], tid))
        result["id"] = signal_id
    return result["id"]


# ── Reading ─────────────────────────────────────────────────────────────────

def _may_review(db, user, key, record_id, owners: dict) -> bool:
    if has_capability(user, "governance.change.review"):
        return True
    owner = owners.get((key, record_id))
    return owner is not None and owner == user.get("id")


def _owners(db, keys_ids: dict) -> dict:
    """Owners of applications and processes among the given records, which are the two kinds that name one."""
    out = {}
    tables = {("governance", "application"): "applications", ("governance", "process"): "business_processes"}
    for key, ids in keys_ids.items():
        table = tables.get(key)
        if not table or not ids:
            continue
        marks = ",".join(["%s"] * len(ids))
        for row in db.execute(f"SELECT id, owner_user_id FROM {table} WHERE id IN ({marks})", sorted(ids)).fetchall():
            out[(key, row["id"])] = row["owner_user_id"]
    return out


def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    marks = ",".join(["%s"] * len(wanted))
    return {r["id"]: r["full_name"] for r in db.execute(f"SELECT id, full_name FROM users WHERE id IN ({marks})", wanted).fetchall()}


def _present(db, user, rows, *, only_reviewable: bool) -> list:
    wanted, source_wanted = {}, {}
    for r in rows:
        wanted.setdefault(canonical_key(r["target_module"], r["target_type"]), set()).add(r["target_id"])
        source_wanted.setdefault(canonical_key(r["source_module"], r["source_type"]), set()).add(r["source_id"])
    seen = {k: describe_records(db, k, ids, user) for k, ids in wanted.items()}
    sources = {k: describe_records(db, k, ids, user) for k, ids in source_wanted.items()}
    owners = _owners(db, wanted)
    names = _names(db, [r["changed_by"] for r in rows] + [r["decided_by"] for r in rows])
    out = []
    for r in rows:
        tkey = canonical_key(r["target_module"], r["target_type"])
        skey = canonical_key(r["source_module"], r["source_type"])
        target = seen.get(tkey, {}).get(r["target_id"])
        if target is None:
            continue  # a record the viewer may not open is not named, counted or hinted at
        may = _may_review(db, user, tkey, r["target_id"], owners)
        if only_reviewable and not may:
            continue
        source = sources.get(skey, {}).get(r["source_id"])
        if source is None:
            continue  # like a link, a signal needs both ends to be openable: nothing says that a hidden record changed
        out.append({
            "id": r["id"], "signal_id": r["signal_id"], "status": r["status"], "kind": r["change_kind"],
            "kind_label": _kind_label(r["change_kind"], skey),
            "target": {"module": tkey[0], "entity_type": tkey[1], "entity_id": r["target_id"], **target},
            "source": {"module": skey[0], "entity_type": skey[1], "entity_id": r["source_id"], **source},
            "changes": json.loads(r["changes"] or "[]"), "changed_by": names.get(r["changed_by"]),
            "can_review": may and r["status"] == "open", "changed_at": str(r["created_at"] or "")[:19],
            "reason": r["reason"], "decided_by": names.get(r["decided_by"]),
            "decided_at": str(r["decided_at"] or "")[:19] or None,
        })
    return out


_SELECT = ("SELECT t.id, t.signal_id, t.target_module, t.target_type, t.target_id, t.status, t.decided_by, t.decided_at, t.reason, "
           "s.source_module, s.source_type, s.source_id, s.change_kind, s.changes, s.changed_by, s.created_at "
           "FROM change_signal_targets t JOIN change_signals s ON s.id = t.signal_id")


def _org_clause(user):
    if user.get("org_id") is None:
        return "(1 = 1)", []
    return "(s.org_id IS NULL OR s.org_id = %s)", [user["org_id"]]


def list_open(db, user: dict, *, limit: int = 100) -> list:
    """Open signals for records the caller may open and may review, newest first."""
    clause, params = _org_clause(user)
    rows = db.execute(f"{_SELECT} WHERE t.status = 'open' AND {clause} ORDER BY t.id DESC LIMIT 500", params).fetchall()
    return _present(db, user, rows, only_reviewable=True)[:max(1, min(int(limit), 200))]


def for_entity(db, user: dict, key, record_id: int, *, limit: int = 20) -> list:
    """Signals that name this record as the one to look at, or as the one that changed, that the caller may see."""
    key = canonical_key(*key)
    if not is_linkable(key) or not describe_record(db, key, record_id, user):
        return []
    clause, params = _org_clause(user)
    rows = db.execute(
        f"{_SELECT} WHERE ((t.target_module = %s AND t.target_type = %s AND t.target_id = %s) "
        f"OR (s.source_module = %s AND s.source_type = %s AND s.source_id = %s)) AND {clause} ORDER BY t.id DESC LIMIT %s",
        [key[0], key[1], record_id, key[0], key[1], record_id, *params, max(1, min(int(limit), 50))]).fetchall()
    return _present(db, user, rows, only_reviewable=False)


def decide(db, user: dict, target_id: int, decision, reason=None) -> dict:
    """Confirm that the record needs a second look (a task is opened for the person who decided) or dismiss the signal with a
    reason. Changes nothing in the record itself. Compare-and-set on `open`, so two people deciding cannot both succeed."""
    if decision not in ("confirmed", "dismissed"):
        raise SignalError(400, "Choose confirm or dismiss.")
    clause, params = _org_clause(user)
    row = db.execute(f"{_SELECT} WHERE t.id = %s AND {clause}", [target_id, *params]).fetchone()
    if row is None:
        raise SignalError(404, "Not found.")
    tkey = canonical_key(row["target_module"], row["target_type"])
    skey = canonical_key(row["source_module"], row["source_type"])
    # Both ends must be openable, as in the lists: a signal the person cannot see answers like one that does not exist.
    source = describe_record(db, skey, row["source_id"], user)
    if source is None or not describe_record(db, tkey, row["target_id"], user):
        raise SignalError(404, "Not found.")
    if not _may_review(db, user, tkey, row["target_id"], _owners(db, {tkey: {row["target_id"]}})):
        raise SignalError(403, "You do not have the right to decide this.")
    if row["status"] != "open":
        raise SignalError(409, "This was already decided.")
    if reason is not None and not isinstance(reason, str):
        raise SignalError(422, "The reason must be text.")
    reason = (reason or "").strip()
    if decision == "dismissed" and len(reason) < 3:
        raise SignalError(422, "Say why it needs no second look.")
    if len(reason) > REASON_MAX:
        raise SignalError(422, f"Keep the reason to {REASON_MAX} characters or fewer.")
    now = _now()
    moved = db.execute(
        "UPDATE change_signal_targets SET status = %s, decided_by = %s, decided_at = %s, reason = %s "
        "WHERE id = %s AND status = 'open'", (decision, user["id"], now, reason or None, target_id)).rowcount
    if moved != 1:
        raise SignalError(409, "This was already decided.")
    target = describe_record(db, tkey, row["target_id"], user)
    task_id = None
    if decision == "confirmed":
        task_id = insert_returning_id(
            db, "INSERT INTO task_board (title, description, module, entity_type, entity_id, assigned_to, status, created_by, "
                "created_at, updated_at) VALUES (%s, %s, 'governance', 'change_review', %s, %s, 'todo', %s, %s, %s)",
            (f"Reassess {target['title']} after a change to {source['title']}"[:200],
             reason or "A connected record changed and its owner confirmed that this one needs a second look.",
             target_id, user["id"], user["id"], now, now))
        db.execute("UPDATE change_signal_targets SET task_id = %s WHERE id = %s", (task_id, target_id))
    return {"id": target_id, "status": decision, "task_id": task_id,
            "audit": (f"Change signal {decision}", "change_signal", row["signal_id"],
                      f"{tkey[0]}/{tkey[1]} {row['target_id']}" + (f": {reason}" if reason else ""))}


# ── Publishers: where the changes come from ─────────────────────────────────

def _context():
    from database import get_current_org, get_current_user_id
    return get_current_user_id(), get_current_org()


def publish_record_change(db, key, record_id: int, before: dict, after: dict, *, extra_targets=(), kind=None) -> "int | None":
    """Publish what changed in a watched record, inside the caller's transaction. `before` and `after` are the record's
    columns as they were and as they are now."""
    watched = WATCHED.get(key)
    if watched is None:
        return None
    user_id, org_id = _context()
    return publish(db, source=(key[0], key[1], record_id), kind=kind or _KIND_OF.get(key[1], "record_changed"),
                   before=before, after=after, fields=watched[1], actor_id=user_id, org_id=org_id, extra_targets=extra_targets)


def publish_application_change(db, app_id: int, before: dict, after: dict) -> "int | None":
    """Called by the application update, inside its transaction, with the row as it was and as it is now."""
    return publish_record_change(db, ("governance", "application"), app_id, before, after)


def publish_process_change(db, process_id: int, before: dict, after: dict) -> "int | None":
    return publish_record_change(db, ("governance", "process"), process_id, before, after)


def _read(key, record_id):
    """The watched columns of one record (and the canonical id of a vendor), through a connection of its own."""
    from database import get_db
    columns = list(WATCHED[key][1]) + (["canonical_id"] if key in VENDOR_KEYS else [])
    db = get_db()
    try:
        row = db.execute(f"SELECT {', '.join(columns)} FROM {kind_table(key)} WHERE id = %s", (record_id,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _same_company(db, key, record_id: int, canonical_id) -> list:
    """The same company's records in the other two vendor modules, found by canonical id."""
    if key not in VENDOR_KEYS or not canonical_id:
        return []
    found = []
    for other in VENDOR_KEYS:
        for row in db.execute(f"SELECT id FROM {kind_table(other)} WHERE canonical_id = %s", (canonical_id,)).fetchall():
            if (other, row["id"]) != (key, record_id):
                found.append((other[0], other[1], row["id"]))
    return found


@contextmanager
def watching(module: str, entity_type: str, record_id):
    """Around an update of a watched record: read it before and after, and publish what changed that matters. It never
    raises into the update: a failure is logged and the record is saved either way."""
    key = canonical_key(module, entity_type)
    before = None
    if key in WATCHED:
        try:
            before = _read(key, record_id)
        except Exception:
            log.warning("Change signal: %s %s could not be read before the update", key, record_id, exc_info=True)
    yield
    if before is None:
        return
    try:
        after = _read(key, record_id)
        if after is None:
            return
        from database import get_db
        db = get_db()
        try:
            publish_record_change(db, key, record_id, before, after,
                                  extra_targets=_same_company(db, key, record_id, after.get("canonical_id")))
            db.commit()
        finally:
            db.close()
    except Exception:
        log.warning("Change signal: %s %s changed but the signal could not be published", key, record_id, exc_info=True)
