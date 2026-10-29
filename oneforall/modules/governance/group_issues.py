"""The level-2 issue register a subsidiary may publish to its group (plan 21, slice 5).

Figures say how many; the register says which ones, by reference, so a group DPO can follow a breach or a request
without the subsidiary's text crossing. A row carries only the fields named in FIELDS, each checked against its own
pattern or fixed vocabulary. A value that does not fit is sent as nothing, never as the text it held, so a title,
a name, a description, a requester or a free-typed type cannot travel by being put in the wrong box.

What crosses, and to whom, is decided in four places that must all agree: the relationship's reviewed terms
(`issue_types`), a named unexpired `issue.view` grant for the reader, the reader's role (`group.issue.view`), and the
subsidiary being licensed for Sentinel. Each publish replaces the register as the reader sees it; earlier runs are kept
for a short time so a change can be explained, then pruned.
"""
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db, get_db_bypass_rls, insert_returning_id, tenant_context
from modules.governance import group_figures as gf

log = logging.getLogger("oneforall.group_issues")

ISSUE_TYPES = ("breach", "dsr", "dpia", "ropa", "consent")
LABELS = {"breach": "Data breaches", "dsr": "Data subject requests", "dpia": "DPIAs",
          "ropa": "Records of processing", "consent": "Consent records (counts)"}
MAX_ROWS = 2000              # per type per publish; a longer register is cut and says so
PAGE = 100
KEEP_RUNS = 30               # runs kept per organization and type
STALE_HOURS = gf.STALE_HOURS

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,39}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LEVEL = {"low", "medium", "high", "critical"}
_VOCAB = {
    "breach_status": {"open", "reported", "investigating", "contained", "resolved", "closed"},
    "breach_type": {"confidentiality", "integrity", "availability", "unauthorised access", "unauthorized access",
                    "loss", "theft", "ransomware", "phishing", "misdelivery", "human error", "other"},
    "dsr_status": {"open", "in_progress", "completed", "closed"},
    "dsr_type": {"Access Request", "Erasure Request", "Rectification", "Portability", "Objection", "Restriction"},
    "dpia_status": {"draft", "in_progress", "completed", "approved"},
    "dpia_level": {"low", "medium", "high"},
    "ropa_status": {"active", "draft", "archived"},
    "consent_status": {"active", "withdrawn", "expired", "revoked"},
}


def _regulations() -> "set[str]":
    from modules.sentinel.jurisdictions import JURISDICTION_RULES
    return set(JURISDICTION_RULES)


def _text(value, allowed) -> "str | None":
    """A value from a fixed vocabulary, matched without case or edge spaces, or nothing."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().lower()
    for item in allowed:
        if item.lower() == wanted:
            return item
    return "other" if "other" in allowed else None


def _day(value) -> "str | None":
    if not isinstance(value, str) or not _DATE.fullmatch(value.strip()[:10]):
        return None
    try:
        date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    return value.strip()[:10]


def _count(value) -> "int | None":
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100_000_000 else None


def _flag(value) -> "int | None":
    if isinstance(value, bool):
        return int(value)
    return {0: 0, 1: 1, "0": 0, "1": 1}.get(value)


# Each published field: the name it travels under, the column(s) it is read from and how it is validated.
# `ref` is special: an unusable reference becomes "<type>-<id>", which says nothing about the record.
FIELDS = {
    "breach": {"table": "sentinel_breaches", "fields": {
        "breach_type": ("breach_type", lambda v: _text(v, _VOCAB["breach_type"])),
        "severity": ("severity", lambda v: _text(v, _LEVEL)),
        "status": ("status", lambda v: _text(v, _VOCAB["breach_status"])),
        "discovery_date": ("COALESCE(NULLIF(discovery_date,''), discovered_date)", _day),
        "reported_date": ("reported_date", _day),
        "affected_count": ("affected_count", _count),
        "notification_required": ("notification_required", _flag),
        "authority_notified": ("authority_notified", _flag),
        "authority_notify_date": ("authority_notify_date", _day),
        "regulation": ("regulation", lambda v: v.strip() if isinstance(v, str) and v.strip() in _regulations() else None),
    }},
    "dsr": {"table": "sentinel_dsr", "fields": {
        "request_type": ("request_type", lambda v: _text(v, _VOCAB["dsr_type"])),
        "regulation": ("regulation", lambda v: v.strip() if isinstance(v, str) and v.strip() in _regulations() else None),
        "received_date": ("received_date", _day),
        "deadline_date": ("deadline_date", _day),
        "status": ("status", lambda v: _text(v, _VOCAB["dsr_status"])),
    }},
    "dpia": {"table": "sentinel_dpias", "fields": {
        "status": ("status", lambda v: _text(v, _VOCAB["dpia_status"])),
        "risk_level": ("risk_level", lambda v: _text(v, _VOCAB["dpia_level"])),
        "regulation": ("regulation", lambda v: v.strip() if isinstance(v, str) and v.strip() in _regulations() else None),
        "updated": ("updated_at", _day),
    }},
    "ropa": {"table": "sentinel_ropa", "fields": {
        "status": ("status", lambda v: _text(v, _VOCAB["ropa_status"])),
        "risk_level": ("risk_level", lambda v: _text(v, _VOCAB["dpia_level"])),
        "regulation": ("regulation", lambda v: v.strip() if isinstance(v, str) and v.strip() in _regulations() else None),
        "dpia_required": ("dpia_required", _flag),
        "updated": ("updated_at", _day),
    }},
}


def validate_types(raw) -> "list[str]":
    """The issue types a relationship's terms may approve."""
    if raw is None:
        return []
    if (not isinstance(raw, list) or len(raw) > len(ISSUE_TYPES) or len(raw) != len(set(raw))
            or not all(isinstance(k, str) and k in ISSUE_TYPES for k in raw)):
        raise HTTPException(422, "Choose issue types from the list")
    return sorted(raw)


def _table(name: str) -> str:
    return f"public.{name}" if settings.is_postgres() else name


def _approved(terms_json) -> "set[str]":
    try:
        listed = json.loads(terms_json or "{}").get("issue_types")
    except ValueError:
        return set()
    return {k for k in listed if k in ISSUE_TYPES} if isinstance(listed, list) else set()


def approved_for_child(db, org_id: int) -> "set[str]":
    """What the parents of this organization approved it to publish as issues. Nobody's child publishes nothing."""
    rows = db.execute(f"SELECT terms_json FROM {_table('org_relationships')} WHERE child_org_id=%s AND status='active'",
                      (org_id,)).fetchall()
    allowed = set()
    for row in rows:
        allowed |= _approved(row["terms_json"])
    return allowed


def sanitize(issue_type: str, record: dict) -> dict:
    """The publishable form of one record: its reference and each allowed field, or nothing for a field that fails."""
    ref = record.get("ref_number")
    ref = ref.strip() if isinstance(ref, str) and _REF.fullmatch(ref.strip()) else f"{issue_type}-{record.get('id')}"
    fields = {}
    for name, (_, check) in FIELDS[issue_type]["fields"].items():
        try:
            fields[name] = check(record.get(name))
        except Exception:
            fields[name] = None
    return {"ref": ref, "fields": fields}


def _consent_summary(db) -> "list[dict]":
    """Counts of consent records by status. Nothing about any one record leaves, so there is one row, with counts."""
    counts = {}
    for row in db.execute("SELECT status, COUNT(*) AS n FROM sentinel_consent GROUP BY status").fetchall():
        status = _text(row["status"], _VOCAB["consent_status"]) or "other"
        counts[status] = counts.get(status, 0) + (_count(row["n"]) or 0)
    return [{"ref": "consent-summary", "fields": dict(sorted(counts.items()))}]


def _read_tenant(org_id: int, slug: str, types: "set[str]") -> "dict[str, tuple[list[dict], bool]]":
    from core.auth import licensed_modules_for
    out = {}
    with tenant_context(org_id, slug, is_super_admin=True):
        db = get_db()
        try:
            licensed = licensed_modules_for(db, org_id)
            if licensed is not None and "sentinel" not in licensed:
                return {}
            for issue_type in sorted(types):
                if issue_type == "consent":
                    out[issue_type] = (_consent_summary(db), False)
                    continue
                spec = FIELDS[issue_type]
                columns = ", ".join(["id", "ref_number"] + [f"{expr} AS {name}" for name, (expr, _) in spec["fields"].items()])
                rows = db.execute(f"SELECT {columns} FROM {spec['table']} ORDER BY id DESC LIMIT {MAX_ROWS + 1}").fetchall()
                out[issue_type] = ([sanitize(issue_type, dict(r)) for r in rows[:MAX_ROWS]], len(rows) > MAX_ROWS)
        finally:
            db.close()
    return out


def publish_tenant(org_id: int, slug: str) -> int:
    """Publish the approved issue types of one subsidiary. Returns how many rows were written."""
    db = get_db_bypass_rls()
    try:
        types = approved_for_child(db, org_id)
    finally:
        db.close()
    if not types:
        return 0
    built = _read_tenant(org_id, slug, types)
    now = utcnow().isoformat()
    db = get_db_bypass_rls()
    try:
        written = 0
        for issue_type, (rows, truncated) in built.items():
            payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
            run = insert_returning_id(
                db, f"INSERT INTO {_table('group_issue_runs')} (source_org_id,issue_type,published_at,row_count,truncated,"
                "content_hash) VALUES (%s,%s,%s,%s,%s,%s)",
                (org_id, issue_type, now, len(rows), 1 if truncated else 0,
                 hashlib.sha256(f"{org_id}:{issue_type}:{payload}".encode()).hexdigest()))
            for row in rows:
                db.execute(
                    f"INSERT INTO {_table('group_issue_rows')} (run_id,source_org_id,issue_type,ref_number,fields_json) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (run, org_id, issue_type, row["ref"], json.dumps(row["fields"], sort_keys=True)))
                written += 1
            old = [r["id"] for r in db.execute(
                f"SELECT id FROM {_table('group_issue_runs')} WHERE source_org_id=%s AND issue_type=%s "
                "ORDER BY id DESC", (org_id, issue_type)).fetchall()][KEEP_RUNS:]
            for run_id in old:
                db.execute(f"DELETE FROM {_table('group_issue_rows')} WHERE run_id=%s", (run_id,))
                db.execute(f"DELETE FROM {_table('group_issue_runs')} WHERE id=%s", (run_id,))
        db.commit()
        return written
    finally:
        db.close()


def publish_all(org_ids: "set[int] | None" = None) -> dict:
    from database import list_active_tenants
    done = {}
    for org_id, slug in list_active_tenants():
        if org_ids is not None and org_id not in org_ids:
            continue
        try:
            done[org_id] = publish_tenant(org_id, slug)
        except Exception:
            log.warning("Group issues: publishing failed for organization %s", org_id, exc_info=True)
    return done


# ── reading ────────────────────────────────────────────────────────────────

def _children(db, actor: dict) -> "list[dict]":
    """Subsidiaries whose register this person may read: the figure rules, with an issue.view grant and an approved type."""
    rows = gf._children(db, actor, capability="issue.view")
    return [{**c, "types": sorted(_approved(c["terms_json"]))} for c in rows if _approved(c["terms_json"])]


def views(db, actor: dict) -> dict:
    if not actor.get("org_id") or not has_capability(actor, "group.issue.view"):
        raise HTTPException(403, "Group issue access required")
    return {"subsidiaries": [{"org_id": c["org_id"], "name": c["name"],
                              "types": [{"key": t, "label": LABELS[t]} for t in c["types"]]} for c in _children(db, actor)]}


def view(db, actor: dict, org_id: int, issue_type: str, page: int = 1) -> dict:
    if not actor.get("org_id") or not has_capability(actor, "group.issue.view"):
        raise HTTPException(403, "Group issue access required")
    child = next((c for c in _children(db, actor) if c["org_id"] == org_id), None)
    if child is None or issue_type not in child["types"]:
        raise HTTPException(404, "Company not found")  # an unknown, ungranted or unapproved type look alike
    page = max(1, min(int(page or 1), 100_000))
    run = db.execute(
        f"SELECT id, published_at, row_count, truncated FROM {_table('group_issue_runs')} "
        "WHERE source_org_id=%s AND issue_type=%s ORDER BY id DESC LIMIT 1", (org_id, issue_type)).fetchone()
    gf._log(db, actor, child["relationship_id"], org_id, "issues_view")
    base = {"org_id": org_id, "name": child["name"], "issue_type": issue_type, "label": LABELS[issue_type]}
    if not run:
        return {**base, "state": "not_reporting", "as_of": None, "rows": [], "total": 0, "page": page, "page_size": PAGE}
    try:
        fresh = datetime.fromisoformat(run["published_at"]) >= utcnow() - timedelta(hours=STALE_HOURS)
    except ValueError:
        fresh = False
    if not fresh:
        return {**base, "state": "not_reporting", "as_of": run["published_at"], "rows": [], "total": 0,
                "page": page, "page_size": PAGE}
    rows = db.execute(
        f"SELECT ref_number, fields_json FROM {_table('group_issue_rows')} WHERE run_id=%s AND source_org_id=%s "
        "ORDER BY id LIMIT %s OFFSET %s", (run["id"], org_id, PAGE, (page - 1) * PAGE)).fetchall()
    return {**base, "state": "reporting", "as_of": run["published_at"], "total": run["row_count"],
            "truncated": bool(run["truncated"]), "page": page, "page_size": PAGE,
            "rows": [{"ref": r["ref_number"], "fields": json.loads(r["fields_json"] or "{}")} for r in rows]}
