"""
What a record document links to, so it is never read alone (no silos): the supporting documents in the Evidence Vault, and the records
the record is connected to.

Both come from the read the Connected page and the Case report already use, `entity360.get_connected`, so a document lists exactly what
the same person sees there: the Vault files linked to the record (each row opening the file in the Vault, with what it shows today:
the reviewer's verdict, an expiry, a replaced version) and the relationship service's connections, a proposed or disputed one marked as
such. Around it a document adds two things, each read through the registry's `describe_records`: the records this record points at, or
that point at it, by a plain reference (a DPIA's RoPA entry, the assessments that cite a DPIA, the exercises of a plan), and the files of
the records it rests on (`entity360.proof_of`), with the other records each file also supports, so records are linked to each other
through the repository.

A document is a copy that leaves the application, so it lists what the reader could already open there and no more. A record or a file
the reader may not open is left out with no count and no hint, so a document never confirms that one exists. Addresses are built from the
configured `APP_URL` (never from the request, whose Host header is the caller's), and the kit draws only an https address as a link.
A row of the records table reads from this record, as the Connected page does: "assesses" means this record assesses the record named in
the row.
"""
from core.email import app_origin
from core.report_kit import identity
from core.report_kit.helpers import ROWS_IN_DOCUMENT, label
from core.report_kit.model import Col, Heading, Table
from modules.governance import entity360
from modules.governance.entity_scope import canonical_key, describe_record, describe_records

TARGETS_LIMIT = 15            # records whose files are read for one document, besides the record itself
ALSO_SHOWN = 4                # other records named beside a file; the rest are counted
OWNER = {("sentinel", "aiia"): "ai_governance", ("governance", "application"): "ai_governance"}    # the module whose navigation name a kind goes under
MARKED = {"suggested": " (proposed, not confirmed)", "disputed": " (disputed: somebody declined this connection)"}


def kind_label(key) -> str:
    """What a kind of record is called, as the Connected page calls it."""
    return entity360.KIND_LABELS.get(key, key[1].replace("_", " ").capitalize())


def where(key) -> str:
    """`Privacy: Processing record`: the module as the navigation names it, then what the record is (once, when the kind already starts with it)."""
    module, kind = identity.module_name(OWNER.get(key, key[0])), kind_label(key)
    return kind if kind.lower().startswith(module.lower()) else f"{module}: {kind}"


def _sentence(text) -> str:
    return text[:1].upper() + text[1:]


def _address(origin, path) -> str:
    """An in-app address (one slash first, not `//host`, no backslash or control character) made absolute with the configured origin."""
    local = (isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "\\" not in path
             and not any(ord(c) < 32 for c in path))
    return identity.safe_link(origin + path) if origin and local else ""


# ── The documents in the Evidence Vault ─────────────────────────────────────

def _state(item) -> str:
    """What a file shows for the record today (the Vault's wording), with its expiry date while that still means something."""
    expires = item["expiry_date"] and item["state"] not in ("Expired", "Replaced by a newer version")
    return item["state"] + (f", expires {identity.format_day(item['expiry_date'])}" if expires else "")


def _kind(item) -> str:
    return ", ".join(part for part in (label(item["category"]) if item.get("category") else "",
                                       f"version {item['version']}" if item.get("version") else "") if part)


def _also(db, user, ids, own) -> dict:
    """{file id: text} naming the other records each file supports that the reader may open: the files link the records to each other.
    `own` are the records this document is about, which are not "other"."""
    if not ids:
        return {}
    links = db.execute(
        "SELECT evidence_id, module, entity_type, entity_id FROM evidence_links "
        f"WHERE evidence_id IN ({','.join(['%s'] * len(ids))}) AND deleted_at IS NULL ORDER BY id", list(ids)).fetchall()
    wanted = {}
    for r in links:
        ident = canonical_key(r["module"], r["entity_type"]) + (r["entity_id"],)
        if ident not in own:
            wanted.setdefault(ident[:2], set()).add(r["entity_id"])
    shown = {k: describe_records(db, k, sorted(v), user) for k, v in wanted.items()}
    named = {}
    for r in links:
        key = canonical_key(r["module"], r["entity_type"])
        record = shown.get(key, {}).get(r["entity_id"])
        text = f"{record['title']} ({where(key)})" if record else None
        if text and text not in named.setdefault(r["evidence_id"], []):
            named[r["evidence_id"]].append(text)
    return {i: "; ".join(names[:ALSO_SHOWN]) + (f"; and {len(names) - ALSO_SHOWN} more" if len(names) > ALSO_SHOWN else "")
            for i, names in named.items() if names}


def _documents(db, user, view, key, record_id, rests_on):
    """(rows, could not be read) of the Vault files linked to the record and to each record it rests on, as `{id, title, path, kind, on,
    state, also}`. A file linked to several of them is one row that names all of them."""
    rows, own, unreadable = {}, {key + (record_id,)}, False
    for index, (target, target_id) in enumerate([(key, record_id), *list(rests_on)[:TARGETS_LIMIT]]):
        target = canonical_key(*target)
        proof = view["proof"] if index == 0 else entity360.proof_of(db, user, target[0], target[1], target_id)
        if proof is None:
            continue
        unreadable = unreadable or proof["state"] == "unavailable"
        own.add(target + (target_id,))
        if index == 0:
            on = "This record"
        else:
            visible = describe_record(db, target, target_id, user)
            if visible is None:
                continue
            on = f"{visible['title']} ({where(target)})"
        for item in proof["items"]:
            row = rows.setdefault(item["id"], {"id": item["id"], "title": item["title"], "path": item["url"], "kind": _kind(item), "on": [],
                                               "state": _state(item)})
            if on not in row["on"]:
                row["on"].append(on)
    also = _also(db, user, list(rows), own)
    return [{**row, "on": "; ".join(row["on"]), "also": also.get(row["id"]) or "No other record"} for row in rows.values()], unreadable


# ── The records ─────────────────────────────────────────────────────────────

def _records(db, user, view, key, record_id, direct, cited_by, skip) -> list:
    """The connections of the Connected page, then the records this one points at and the records that point at it by a plain reference
    (`(key, id, how)`, read through the registry), one row per record with every way it is connected. `skip` is `(key, id)` pairs the
    document already shows elsewhere."""
    rows, hidden = {}, {canonical_key(*k) + (i,) for k, i in skip} | {key + (record_id,)}

    def add(k, record, title, path, how):
        ident = k + (record,)
        if ident in hidden:
            return
        row = rows.setdefault(ident, {"title": title, "path": path, "where": where(k), "how": []})
        if _sentence(how) not in row["how"]:
            row["how"].append(_sentence(how))

    for section in view["connections"]:
        for c in section["items"]:
            add(canonical_key(section["key"], c["entity_type"]), c["entity_id"], c["title"], c["url"], c["relationship"] + MARKED.get(c["state"], ""))
    for refs in (direct, cited_by):
        by_kind = {}
        for ref_key, ref_id, how in refs:
            by_kind.setdefault(canonical_key(*ref_key), []).append((ref_id, how))
        for ref_key, wanted in by_kind.items():
            shown = describe_records(db, ref_key, [i for i, _ in wanted], user)
            for ref_id, how in wanted:
                if ref_id in shown:
                    add(ref_key, ref_id, shown[ref_id]["title"], shown[ref_id]["url"], how)
    return [{**row, "how": "; ".join(row["how"])} for row in rows.values()]


# ── The closing section of a record document ────────────────────────────────

def section(db, user, key, record_id, *, evidence=(), direct=(), cited_by=(), skip=()) -> list:
    """The blocks that end a record document: the supporting documents in the Evidence Vault (the record's own files, then those of each
    `(key, id)` in `evidence`, the records it rests on), then this record's live address and everything connected to it. `direct` and
    `cited_by` are `(key, id, how)` plain references, read from this record: "assesses", "is cited by"."""
    key = canonical_key(*key)
    view = entity360.get_connected(db, user, key[0], key[1], record_id)
    if view is None:                  # the caller has already let this person open the record; nothing is added for one they may not
        return []
    origin = app_origin()
    files, unreadable = _documents(db, user, view, key, record_id, evidence)
    policy_view = view.get("policy_references")
    policies = []
    if isinstance(policy_view, dict) and policy_view.get("state") == "ok":
        for item in policy_view.get("items", []):
            policies.append({"title": item["title"], "version": item["version"],
                             "version_id": item["version_id"], "anchor": item.get("anchor") or "Document",
                             "approval": "External approval verified" if item["approval"] == "external_verified" else "ThemisIQ approved",
                             "path": item["url"]})
    own = view["entity"]
    rows = [{"title": own["title"], "path": own["url"], "where": where(key), "how": "The live record this document was made from"},
            *_records(db, user, view, key, record_id, direct, cited_by, skip)]
    for row in files + rows + policies:
        row["url"] = _address(origin, row["path"])
    links = ("Links open the file or the record in ThemisIQ and work for people who have access to it." if origin else
             "No application address (APP_URL) is configured, so these are listed without links.")
    return [
        Heading("Supporting documents and connected records", "Other documentation is linked through the Evidence Vault, and the records "
                                                              "this one is connected to follow, so it is read with them and not alone."),
        Table("Documents in the Evidence Vault",
              [Col("Document", "title", weight=2.2, link="url"), Col("Type", "kind", weight=1.45), Col("Attached to", "on", weight=1.7),
               Col("Shows today", "state", weight=1.5), Col("Also supports", "also", weight=1.9)],
              files, max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Evidence",
              note=f"{links} A file or record you may not open is not listed. A file is not proof until a reviewer has accepted it for the "
                   "record." + (" The files of some record could not be read just now, which is not the same as none." if unreadable else ""),
              empty_text=("The documents in the Evidence Vault could not be read just now, which is not the same as none." if unreadable else
                          "No document in the Evidence Vault is linked to this record, or none that you may open.")),
        Table("Current policy references",
              [Col("Policy", "title", weight=2.2, link="url"), Col("Version", "version", weight=.8),
               Col("Exact version ID", "version_id", weight=1), Col("Source clause", "anchor", weight=1.2),
               Col("Approval provenance", "approval", weight=1.5)],
              policies, max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Policy References",
              note="Only an authorized, current, approved policy version with a confirmed relationship is listed. "
                   "A policy reference is context, not proof that a control operates effectively.",
              empty_text="No current, confirmed policy reference is visible for this record."),
        Table("Records connected to this one",
              [Col("Record", "title", weight=2.6, link="url"), Col("Where it lives", "where", weight=1.9), Col("Connection", "how", weight=2.3)],
              rows, max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Connected",
              note="Each connection is read from this record: 'Assesses' means this record assesses the record named in the row. A "
                   "connection nobody confirmed is marked as proposed." + (" The connections could not be read just now, which is not the "
                                                                          "same as none." if view["unavailable"] else ""),
              empty_text="No connected record is recorded, or none that you may open.")]
