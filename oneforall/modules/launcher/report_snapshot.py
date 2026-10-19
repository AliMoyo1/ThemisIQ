"""
A saved report run is the document that was generated, not a question asked again
(plans/2026-10-governance-rework/04 section 5).

`result_json` of a run holds one envelope: who generated it, for which scope, when, the figures, which sources were read
(and which were not), the identifiers of the rows read, what the report leaves out, and the change since the earlier run.
The envelope is encoded once (canonical JSON), hashed, and never recomputed on read. Opening a run decodes it, checks the
hash and checks that the person is still the recipient with the access they had when it was generated.

This module is pure: no request, no database. The routes call it.
"""
import hashlib
import hmac
import json

FORMAT = 1
RECORD_CAP = 2000  # identifiers kept per source; the count is always exact and `truncated` says when the list is not

DECISION_STATUS = {
    "state": "not_reviewed",
    "text": "No review or approval has been recorded for this report. The figures are what the platform held when it was "
            "generated, not a signed-off position.",
}


def encode(envelope: dict) -> tuple:
    """(canonical text, sha256 hex). The hash is of the exact text that is stored."""
    text = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def intact(text, digest) -> bool:
    if not text or not digest:
        return False
    return hmac.compare_digest(hashlib.sha256(text.encode("utf-8")).hexdigest(), str(digest))


def actor_id(triggered_by) -> "int | None":
    """The person a run was generated for: `triggered_by` is `user:<id>:<digest of their access>` (see run_scope_key)."""
    parts = str(triggered_by or "").split(":")
    if len(parts) == 3 and parts[0] == "user" and parts[1].isdecimal():
        return int(parts[1])
    return None


ALLOW, NOT_FOUND, ACCESS_CHANGED = "allow", "not_found", "access_changed"


def decide(user: dict, triggered_by, current_key: str) -> str:
    """May this person open a saved run?

    * a super administrator may open any run in the organization's schema;
    * everyone else may open only the run generated for them, and only while their access is what it was then
      (`current_key` is `run_scope_key(user)`): a change to units, modules or capabilities hides the saved output;
    * a run generated for somebody else answers exactly like one that does not exist.
    """
    if user.get("is_super_admin"):
        return ALLOW
    if actor_id(triggered_by) != user.get("id"):
        return NOT_FOUND
    return ALLOW if triggered_by == current_key else ACCESS_CHANGED


def flatten(value, prefix="") -> dict:
    """Every number in a result, by a dotted path. Lists of rows that have a name or title are keyed by it, so a figure
    in `by_framework` is compared with the same framework in the earlier run."""
    out = {}
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out[prefix] = value
    elif isinstance(value, dict):
        for k, v in value.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("label") or item.get("id") or i
                out.update(flatten({k: v for k, v in item.items() if k not in ("name", "title", "label", "id")},
                                   f"{prefix}.{name}" if prefix else str(name)))
    return out


def _label(path: str) -> str:
    return path.replace("_", " ").replace(".", " > ")


def change_summary(previous: dict, previous_id: int, current: dict, scope_now: dict, version_now: str) -> dict:
    """What moved between two runs of the same definition. Neither run is edited: this is stored with the new one."""
    before = flatten(previous.get("result"))
    after = flatten(current)
    changes, same = [], 0
    for path in sorted(set(before) | set(after)):
        was, now = before.get(path), after.get(path)
        if was == now:
            same += 1
            continue
        delta = round(now - was, 2) if was is not None and now is not None else None
        changes.append({"path": path, "label": _label(path), "was": was, "now": now, "delta": delta})
    changes.sort(key=lambda c: -abs(c["delta"]) if c["delta"] is not None else 0)
    run = previous.get("run") or {}
    return {
        "previous_run_id": previous_id, "previous_generated_at": run.get("generated_at"),
        "changed": len(changes), "unchanged": same, "changes": changes[:100],
        "scope_changed": (previous.get("scope") or {}).get("fingerprint") != scope_now.get("fingerprint"),
        "definition_changed": run.get("definition_version") != version_now,
    }


def scope_fingerprint(scope: dict) -> str:
    keys = {k: scope.get(k) for k in ("org_id", "whole_organization", "business_unit_ids", "organization_wide_only")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _cell(value):
    """A text cell that a spreadsheet would read as a formula is written as text (CSV injection)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", chr(9), chr(13)):
        return "'" + value
    return value


def csv_rows(envelope: dict) -> list:
    """The frozen figures as rows a spreadsheet can read: a header block, then one row per number or per listed record."""
    run, scope = envelope.get("run") or {}, envelope.get("scope") or {}
    rows = [
        ["Report", run.get("type_label") or run.get("report_type"), ""],
        ["Definition", run.get("definition_name"), ""],
        ["Definition version", run.get("definition_version"), ""],
        ["Generated at (UTC)", run.get("generated_at"), ""],
        ["Generated by", (run.get("generated_by") or {}).get("name"), ""],
        ["Scope", scope.get("label"), ""],
        ["Complete", "yes" if envelope.get("complete") else "no", ""],
        ["Decision status at generation", (envelope.get("decision_status") or {}).get("text"), ""],
    ]
    for src in envelope.get("sources") or []:
        rows.append(["Source", f"{src.get('label')}: {src.get('state')}", src.get("records") if src.get("records") is not None else ""])
    for source, captured in (envelope.get("inputs") or {}).items():
        rows.append(["Input source", source, captured.get("revision_state") or "not_recorded"])
        revisions = {item["id"]: item for item in captured.get("revisions") or []}
        for record_id in captured.get("ids") or []:
            revision = revisions.get(record_id) or {}
            detail = ", ".join(part for part in (
                "version " + str(revision["version"]) if revision.get("version") is not None else "",
                "last recorded change " + str(revision["last_recorded_change"])
                if revision.get("last_recorded_change") is not None else "",
            ) if part)
            rows.append(["Input record", f"{source} #{record_id}", detail or "revision not recorded"])
        if captured.get("truncated"):
            rows.append(["Input limit", source, "Identifier list capped; see exact source count above"])
    for text in envelope.get("limitations") or []:
        rows.append(["Limitation", text, ""])
    rows.append(["", "", ""])
    rows.append(["Figure", "Value", "Note"])

    def walk(value, path):
        if isinstance(value, bool):
            rows.append([path, "yes" if value else "no", ""])
        elif isinstance(value, (int, float)) or value is None or isinstance(value, str):
            rows.append([path, "" if value is None else value, "not available" if value is None else ""])
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i + 1}]")
    walk(envelope.get("result"), "")
    return [[_cell(c) for c in row] for row in rows]
