"""
PLAN-35 T01: dry-run legacy readiness report for the ARIA policy workflow.

Scope of this script (deliberately narrow):

  1. Report, read-only by default, whether every existing aria_documents row
     can be unambiguously mapped to an organization, an owner user, and a
     valid N.M version before it is eligible for adoption into the managed
     workflow. Never guesses; an ambiguous or unmatched row is reported, not
     resolved.
  2. Initialize aria_document_number_sequence from the highest existing
     numeric DOC-<digits> suffix, so the shared allocator starts one past
     legacy history instead of colliding with it.

What this script deliberately does NOT do: it does not create
aria_policy_versions "legacy baseline" rows. Per the plan (section 4.8,
item 9), that adoption happens lazily, per document, at the moment of its
first revision or submission under a document lock -- not as a bulk
migration here. Bulk-creating baselines here would race with that later,
service-owned adoption path.

Usage:
    python scripts/prepare_aria_policy_workflow.py
        Dry-run report only. No writes.

    python scripts/prepare_aria_policy_workflow.py --apply-org-id N
        After showing the same report, assign organization N to every
        aria_documents row whose org_id is currently NULL AND whose owner/
        version already resolve cleanly (no ambiguous rows are ever
        written to, regardless of this flag). Organization N must already
        exist. Refuses if more than one organization exists in this
        database, since which org a NULL-org legacy row belongs to is then
        genuinely ambiguous, not a single-tenant default.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db  # noqa: E402

_VERSION_RE = re.compile(r"^\d+\.\d+$")


def _find_owner_matches(db, org_id, owner_text: str) -> list[dict]:
    """Users in org_id whose username or full_name matches owner_text
    exactly (case-insensitive). Empty/blank owner_text matches nothing --
    an unset owner is a distinct anomaly from an unmatched one."""
    owner_text = (owner_text or "").strip()
    if not owner_text:
        return []
    where_org = "AND org_id=%s" if org_id is not None else "AND org_id IS NULL"
    params = [owner_text, owner_text] + ([org_id] if org_id is not None else [])
    rows = db.execute(
        f"SELECT id, username, full_name FROM users "
        f"WHERE (LOWER(username)=LOWER(%s) OR LOWER(full_name)=LOWER(%s)) {where_org}",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def build_report(db) -> dict:
    orgs = [dict(r) for r in db.execute(
        "SELECT id, slug, status FROM organizations ORDER BY id"
    ).fetchall()]

    docs = db.execute(
        "SELECT id, doc_id, title, org_id, owner, version, "
        "policy_workflow_managed FROM aria_documents ORDER BY id"
    ).fetchall()

    resolvable, unresolved = [], []
    for row in docs:
        doc = dict(row)
        if doc.get("policy_workflow_managed"):
            continue  # already adopted; not this report's concern

        problems = []

        owner_search_org_id = doc["org_id"]
        if doc["org_id"] is None:
            if len(orgs) == 0:
                problems.append("NO_ORGANIZATION_EXISTS")
            elif len(orgs) > 1:
                problems.append("ORG_AMBIGUOUS_MULTIPLE_EXIST")
            else:
                # Exactly one org: not an error here (resolvable via
                # --apply-org-id), and it's the only sensible scope to
                # search for the owner match below.
                owner_search_org_id = orgs[0]["id"]
        elif not any(o["id"] == doc["org_id"] for o in orgs):
            problems.append("ORG_ID_SET_BUT_NOT_FOUND")

        owner_matches = _find_owner_matches(db, owner_search_org_id, doc.get("owner"))
        if not (doc.get("owner") or "").strip():
            problems.append("OWNER_BLANK")
        elif len(owner_matches) == 0:
            problems.append("OWNER_NO_USER_MATCH")
        elif len(owner_matches) > 1:
            problems.append("OWNER_AMBIGUOUS_MULTIPLE_USERS_MATCH")

        if not _VERSION_RE.match(str(doc.get("version") or "")):
            problems.append("VERSION_NOT_N_DOT_M")

        entry = {
            "id": doc["id"], "doc_id": doc["doc_id"], "title": doc["title"],
            "current_org_id": doc["org_id"], "owner_text": doc.get("owner"),
            "version_text": doc.get("version"), "problems": problems,
        }
        (unresolved if problems else resolvable).append(entry)

    return {
        "organizations": orgs,
        "resolvable_count": len(resolvable),
        "unresolved_count": len(unresolved),
        "resolvable": resolvable,
        "unresolved": unresolved,
    }


def print_report(report: dict) -> None:
    orgs = report["organizations"]
    print(f"Organizations in this database: {len(orgs)}")
    for o in orgs:
        print(f"  id={o['id']} slug={o['slug']!r} status={o['status']!r}")
    print()
    print(f"aria_documents rows eligible for adoption review: "
          f"{report['resolvable_count']} resolvable, "
          f"{report['unresolved_count']} unresolved")
    if report["unresolved"]:
        print("\nUnresolved rows (no write action will ever be taken on these "
              "automatically):")
        for e in report["unresolved"]:
            print(f"  {e['doc_id']} (id={e['id']}) {e['title']!r}: "
                  f"org={e['current_org_id']} owner={e['owner_text']!r} "
                  f"version={e['version_text']!r} -- {', '.join(e['problems'])}")
    if report["resolvable"]:
        print("\nResolvable rows (org_id NULL, single org exists, owner/version "
              "already clean -- eligible for --apply-org-id):")
        for e in report["resolvable"]:
            print(f"  {e['doc_id']} (id={e['id']}) {e['title']!r}")


def apply_org_id(db, org_id: int, report: dict) -> int:
    """Assign org_id to every row this same report classified as resolvable
    and currently NULL-org. Refuses (raises) if org_id doesn't exist or if
    more than one organization exists, since a bulk default would then be a
    guess, not a resolution. Returns the number of rows updated."""
    orgs = report["organizations"]
    if not any(o["id"] == org_id for o in orgs):
        raise ValueError(f"Organization {org_id} does not exist in this database.")
    if len(orgs) > 1:
        raise ValueError(
            "Refusing to bulk-apply an organization id: more than one "
            "organization exists, so a NULL org_id on a legacy row is "
            "genuinely ambiguous, not a single-tenant default."
        )
    ids = [e["id"] for e in report["resolvable"] if e["current_org_id"] is None]
    if not ids:
        return 0
    placeholders = ",".join(["%s"] * len(ids))
    db.execute(
        f"UPDATE aria_documents SET org_id=%s WHERE id IN ({placeholders})",
        [org_id] + ids,
    )
    db.commit()
    return len(ids)


def ensure_document_number_sequence(db) -> int:
    """Idempotent: initialize aria_document_number_sequence to one past the
    highest existing numeric DOC-<digits> suffix. Never lowers an existing
    next_value (a second run must not rewind the allocator)."""
    # SUBSTR(str, start) rather than the SQL-standard SUBSTRING(str FROM n):
    # the latter is PostgreSQL-only and raises a syntax error on SQLite
    # (confirmed directly; some existing call sites elsewhere in this
    # codebase use SUBSTRING FROM and would hit the same failure on SQLite
    # if their new-document code path were ever actually exercised there).
    row = db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(doc_id, 5) AS INTEGER)), 0) "
        "FROM aria_documents WHERE doc_id LIKE 'DOC-%%'"
    ).fetchone()
    highest = (row[0] if row else 0) or 0
    next_value = highest + 1

    existing = db.execute(
        "SELECT next_value FROM aria_document_number_sequence WHERE id=1"
    ).fetchone()
    if existing is None:
        db.execute(
            "INSERT INTO aria_document_number_sequence (id, next_value) VALUES (1, %s)",
            (next_value,),
        )
        db.commit()
        return next_value
    if existing[0] < next_value:
        db.execute(
            "UPDATE aria_document_number_sequence SET next_value=%s WHERE id=1",
            (next_value,),
        )
        db.commit()
        return next_value
    return existing[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-org-id", type=int, default=None,
                         help="Assign this organization id to resolvable NULL-org rows.")
    args = parser.parse_args()

    db = get_db()
    try:
        report = build_report(db)
        print_report(report)

        seq_value = ensure_document_number_sequence(db)
        print(f"\naria_document_number_sequence.next_value = {seq_value}")

        if args.apply_org_id is not None:
            n = apply_org_id(db, args.apply_org_id, report)
            print(f"\nApplied org_id={args.apply_org_id} to {n} row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
