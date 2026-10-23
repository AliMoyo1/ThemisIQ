#!/usr/bin/env python3
"""Read-only release inventory for historical AIMS scope and unrated DPIAs.

Run with the production environment available to the app, for example from
/project/oneforall as the service operator. Output contains tenant and row IDs,
issue codes and field names only; it never prints risk notes or control text.
Review every reported row with a specialist before the unit-scoping release.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy import DEFAULT_ENV_FILE, parse_env_file

if DEFAULT_ENV_FILE.exists():
    private_env = parse_env_file(DEFAULT_ENV_FILE)
    for key in ("DATABASE_URL", "PGPASSWORD_FILE", "PGPASSWORD"):
        if private_env.get(key):
            os.environ.setdefault(key, private_env[key])

from database import get_db_background, list_active_tenants, tenant_context


TEXT_FIELDS = ("risk_description", "contributing_factors", "strategic_objective",
               "ai_objective", "scope_justification")
LINK_TEXT_FIELDS = ("control_detail", "evidence", "action_steps", "interdependency")


def _audit_tenant(db, org_id):
    assessments = [dict(row) for row in db.execute(
        "SELECT id, business_unit_id FROM aims_assessments ORDER BY id").fetchall()]
    owners = {row["id"]: row["business_unit_id"] for row in assessments}
    controls = [dict(row) for row in db.execute(
        "SELECT id, business_unit_id, ref, title FROM ai_control_catalogue WHERE business_unit_id IS NOT NULL"
    ).fetchall()]
    control_by_id = {row["id"]: row for row in controls}
    for row in assessments:
        if row["business_unit_id"] is None:
            print(f"{org_id}|{row['id']}|||organization_wide|")
    risks = [dict(row) for row in db.execute(
        "SELECT id, assessment_id, catalogue_control_id, " + ", ".join(TEXT_FIELDS) + " FROM aims_risks"
    ).fetchall()]
    links = [dict(row) for row in db.execute(
        "SELECT rc.risk_id, rc.catalogue_control_id, " + ", ".join(LINK_TEXT_FIELDS) +
        " FROM aims_risk_controls rc"
    ).fetchall()]
    linked = {}
    link_notes = {}
    for link in links:
        linked.setdefault(link["risk_id"], set()).add(link["catalogue_control_id"])
        link_notes.setdefault(link["risk_id"], []).append(link)
    for risk in risks:
        unit = owners.get(risk["assessment_id"])
        target_ids = linked.get(risk["id"], set()) | ({risk["catalogue_control_id"]} if risk["catalogue_control_id"] else set())
        for control_id in sorted(value for value in target_ids if value is not None):
            control = control_by_id.get(control_id)
            if control and control["business_unit_id"] != unit:
                print(f"{org_id}|{risk['assessment_id']}|{risk['id']}|{control_id}|cross_unit_link|")
        # A link can be masked while its title/reference was copied into a note.
        # This is a candidate search, not a finding of disclosure: human review
        # must decide whether a match is meaningful and who may see the note.
        for control in controls:
            if control["business_unit_id"] == unit:
                continue
            needles = [str(control.get(k) or "").strip().casefold() for k in ("ref", "title")]
            needles = [value for value in needles if len(value) >= 8]
            if not needles:
                continue
            for field in TEXT_FIELDS:
                haystack = str(risk.get(field) or "").casefold()
                if any(value in haystack for value in needles):
                    print(f"{org_id}|{risk['assessment_id']}|{risk['id']}|{control['id']}|possible_copied_text|{field}")
            for link in link_notes.get(risk["id"], ()):  # copied wording can also live in treatment notes
                for field in LINK_TEXT_FIELDS:
                    haystack = str(link.get(field) or "").casefold()
                    if any(value in haystack for value in needles):
                        print(f"{org_id}|{risk['assessment_id']}|{risk['id']}|{control['id']}|possible_copied_text|{field}")
    unrated = db.execute(
        "SELECT COUNT(*) FROM sentinel_dpias WHERE overall_risk IS NULL OR TRIM(overall_risk)=''"
    ).fetchone()[0]
    print(f"{org_id}||||unrated_dpia_count|{unrated}")
    for row in db.execute("SELECT id FROM bcm_plans WHERE business_unit_id IS NULL ORDER BY id").fetchall():
        print(f"{org_id}||||organization_wide_plan|{row['id']}")


def main():
    print("org_id|assessment_id|risk_id|control_id|issue|field_or_count")
    for org_id, slug in list_active_tenants():
        # Release inventory must include every unit in this tenant. A background
        # connection with no unit scope would otherwise miss unit-owned rows.
        with tenant_context(org_id, slug, is_super_admin=True):
            db = get_db_background()
            try:
                _audit_tenant(db, org_id)
            finally:
                db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
