"""Complete, scoped register snapshots for the existing saved-report pipeline.

Rows are copied into the frozen report envelope. No UI pagination or PDF row
limit applies. The owning module's authorization rule determines visibility.
"""
from __future__ import annotations

import json

from core.rbac import has_capability
from core.timeutils import utcnow
from modules.evidence.scope import current_library_sql, evidence_scope_sql
from modules.governance.entity_scope import entity_scope_sql


class RegisterNotAvailable(LookupError):
    """Missing and inaccessible selections receive the same response."""


def _require(user, capability):
    if not has_capability(user, capability):
        raise RegisterNotAvailable("Register not found")


def _source(table: str, ids: list[int], label: str, module: str) -> tuple[dict, dict]:
    return ({"source": table, "label": label, "module": module, "state": "read", "records": len(ids)},
            {"ids": ids, "truncated": False, "revision_state": "not_recorded"})


def _pack(kind, sections, sources, inputs, *, limitations=()):
    from modules.launcher.report_builders import Built
    return Built(result={"register": kind, "sections": sections,
                         "counts": {key: len(rows) for key, rows in sections.items()},
                         "as_of": utcnow().isoformat()},
                 sources=sources, inputs=inputs, limitations=list(limitations),
                 exclusions=[], complete=True)


def _claims_rows(rows, reference_key):
    """Preserve unverified workbook facts as labelled claims, not live decisions."""
    details = []
    for row in rows:
        raw = row.get("source_claims_json")
        if not raw:
            continue
        try:
            claims = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(claims, dict):
            continue
        for field, value in claims.items():
            if value is not None and str(value).strip():
                details.append({"reference": row[reference_key], "field": field,
                                "source_value": str(value), "status": "Unverified workbook claim"})
    return details


def framework(db, user, framework_id: int, *, audit_id: int | None = None):
    _require(user, "module.aria.access")
    if type(framework_id) is not int or framework_id < 1:
        raise RegisterNotAvailable("Register not found")
    fw = db.execute("SELECT id,name,is_active,updated_at FROM frameworks WHERE id=%s", (framework_id,)).fetchone()
    if not fw:
        raise RegisterNotAvailable("Register not found")
    audit = None
    if audit_id is not None:
        _require(user, "module.grid.access")
        if type(audit_id) is not int or audit_id < 1:
            raise RegisterNotAvailable("Register not found")
        audit_scope, audit_params = entity_scope_sql(("grid", "audit"), user, "a")
        row = db.execute(
            "SELECT a.id,a.name,a.framework_id,a.framework_ids,a.is_integrated,a.status,"
            "a.business_unit_id,a.created_at,gf.name AS framework_name "
            "FROM grid_audits a LEFT JOIN grid_frameworks gf ON gf.id=a.framework_id "
            f"WHERE a.id=%s AND {audit_scope}", [audit_id, *audit_params]).fetchone()
        if not row:
            raise RegisterNotAvailable("Register not found")
        audit = dict(row)
        if audit["is_integrated"]:
            try:
                linked_ids = json.loads(audit["framework_ids"] or "[]")
            except (TypeError, ValueError):
                linked_ids = []
            if not isinstance(linked_ids, list) or framework_id not in linked_ids:
                raise RegisterNotAvailable("Register not found")
        else:
            # GRID and ARIA IDs are different namespaces. Legacy GRID audits
            # have only a framework name, so require a unique exact name.
            matches = db.execute("SELECT COUNT(*) FROM frameworks WHERE name=%s",
                                 (audit["framework_name"],)).fetchone()[0]
            if matches != 1 or audit["framework_name"] != fw["name"]:
                raise RegisterNotAvailable("Register not found")
    ctrl_scope, ctrl_params = entity_scope_sql(("aria", "control"), user, "c")
    controls = [dict(r) for r in db.execute(
        "SELECT c.id,c.ref,c.name,c.category,c.status,c.owner,c.priority,c.review_date,c.version,c.last_updated "
        f"FROM controls c WHERE c.framework_id=%s AND {ctrl_scope} ORDER BY c.ref,c.id",
        [framework_id, *ctrl_params]).fetchall()]
    doc_scope, doc_params = entity_scope_sql(("aria", "document"), user, "d")
    documents = [dict(r) for r in db.execute(
        "SELECT d.id,d.doc_id,d.title,d.doc_type,d.version,d.status,d.owner,d.approver,"
        "d.effective_date,d.review_date,d.current_policy_version_id "
        f"FROM aria_documents d WHERE d.framework=%s AND d.org_id=%s AND {doc_scope} ORDER BY d.doc_id,d.id",
        [fw["name"], user.get("org_id"), *doc_params]).fetchall()]
    docs_by_id = {r["id"]: r for r in documents}
    evidence_scope, evidence_params = evidence_scope_sql(user, "e")
    proof_rows = []
    crosswalk = []
    evidence_ids = set()
    from modules.aria.policy_references import resolve_policy_references
    from modules.evidence.proof import link_state_label
    mapped_controls = {r["control_id"] for r in db.execute(
        "SELECT DISTINCT control_id FROM aria_policy_clause_links WHERE org_id=%s AND state='confirmed'",
        (user.get("org_id"),)).fetchall()}
    for control in controls:
        policy_refs = (resolve_policy_references(db, user, ("aria", "control", control["id"]), limit=None)
                       if control["id"] in mapped_controls else [])
        for ref in policy_refs:
            if ref["document_id"] in docs_by_id:
                crosswalk.append({"control_id": control["id"], "control_ref": control["ref"],
                                  "document_id": ref["document_id"], "document_title": ref["title"],
                                  "version_id": ref["version_id"], "approval": ref["approval"],
                                  "meaning": "Design reference; not operating proof"})
        linked = db.execute(
            "SELECT l.id AS link_id,l.review_status,l.reviewed_by,l.reviewed_at,"
            "e.id AS evidence_id,e.title,e.version,e.file_hash,e.status,e.expiry_date,e.period_start,e.period_end "
            "FROM evidence_links l JOIN evidence_items e ON e.id=l.evidence_id "
            "WHERE l.module='aria' AND l.entity_type='control' AND l.entity_id=%s "
            f"AND l.deleted_at IS NULL AND {evidence_scope} ORDER BY e.id,l.id",
            [control["id"], *evidence_params]).fetchall()
        for entry in linked:
            row = dict(entry)
            evidence_ids.add(row["evidence_id"])
            row.update(control_id=control["id"], control_ref=control["ref"],
                       proof_state=link_state_label(row["status"], row["expiry_date"], row["review_status"]))
            row["accepted"] = (row["status"] == "current" and row["proof_state"] == "Accepted")
            proof_rows.append(row)
    control_rows = [{"id": r["id"], "ref": r["ref"], "name": r["name"], "status": r["status"],
                     "owner": r["owner"], "version": r["version"], "review_date": r["review_date"],
                     "document_links": sum(x["control_id"] == r["id"] for x in crosswalk),
                     "accepted_proof": sum(x["control_id"] == r["id"] and x["accepted"] for x in proof_rows)}
                    for r in controls]
    doc_rows = [{**r, "approval": "Approved" if r["status"] == "Approved" and
                 r["current_policy_version_id"] else "Not verified in this register"} for r in documents]
    sections = {"controls": control_rows, "documents": doc_rows,
                "document_links": crosswalk, "evidence": proof_rows,
                "gaps": ([{"control_ref": r["ref"], "control": r["name"],
                           "gap": gap} for r in control_rows for gap in
                          (["No reviewed policy mapping"] if not r["document_links"] else []) +
                          (["No accepted operating proof"] if not r["accepted_proof"] else [])]),
                "manifest": ([{"kind": "framework", "id": fw["id"], "revision": fw["updated_at"],
                               "hash": "not_recorded"}] +
                             [{"kind": "control", "id": r["id"], "revision": r["version"],
                               "hash": "not_recorded"} for r in controls] +
                             [{"kind": "controlled_document", "id": r["id"], "revision": r["version"],
                               "hash": "not_recorded"} for r in documents] +
                             [{"kind": "vault_artifact", "id": r["evidence_id"], "revision": r["version"],
                               "hash": r["file_hash"] or "not_recorded"} for r in proof_rows])}
    audit_controls, audit_findings, audit_proof = [], [], []
    if audit is not None:
        grid_control_scope, grid_control_params = entity_scope_sql(("grid", "control"), user, "c")
        audit_controls = [dict(r) for r in db.execute(
            "SELECT c.id,c.control_id,c.name,c.status,c.risk_level,c.due_date "
            f"FROM grid_controls c WHERE c.audit_id=%s AND {grid_control_scope} "
            "ORDER BY c.control_id,c.id", [audit_id, *grid_control_params]).fetchall()]
        finding_scope, finding_params = entity_scope_sql(("grid", "nc"), user, "n")
        audit_findings = [dict(r) for r in db.execute(
            "SELECT n.id,n.control_id,n.title,n.severity,n.status,n.due_date,n.closed_at "
            f"FROM grid_non_conformances n WHERE n.audit_id=%s AND {finding_scope} "
            "ORDER BY n.id", [audit_id, *finding_params]).fetchall()]
        control_ids = {r["id"] for r in audit_controls}
        finding_ids = {r["id"] for r in audit_findings}
        audit_proof = [dict(r) for r in db.execute(
            "SELECT l.id AS link_id,l.entity_type,l.entity_id,l.review_status,l.reviewed_at,"
            "e.id AS evidence_id,e.title,e.version,e.file_hash,e.status "
            "FROM evidence_links l JOIN evidence_items e ON e.id=l.evidence_id "
            "WHERE l.module='grid' AND l.deleted_at IS NULL AND "
            "((l.entity_type='audit' AND l.entity_id=%s) OR "
            "(l.entity_type='control' AND l.entity_id IN (SELECT id FROM grid_controls WHERE audit_id=%s)) OR "
            "(l.entity_type='nc' AND l.entity_id IN (SELECT id FROM grid_non_conformances WHERE audit_id=%s))) "
            f"AND {current_library_sql()} AND {evidence_scope} ORDER BY e.id,l.id",
            [audit_id, audit_id, audit_id, *evidence_params]).fetchall()]
        audit_proof = [r for r in audit_proof if
                       (r["entity_type"] == "audit" and r["entity_id"] == audit_id) or
                       (r["entity_type"] == "control" and r["entity_id"] in control_ids) or
                       (r["entity_type"] == "nc" and r["entity_id"] in finding_ids)]
        evidence_ids.update(r["evidence_id"] for r in audit_proof)
        sections.update(audit_controls=audit_controls, audit_findings=audit_findings,
                        audit_evidence=audit_proof)
        sections["manifest"].extend(
            [{"kind": "grid_audit", "id": audit_id, "revision": audit["created_at"],
              "hash": "not_recorded"}] +
            [{"kind": "grid_control", "id": r["id"], "revision": "not_recorded",
              "hash": "not_recorded"} for r in audit_controls] +
            [{"kind": "grid_finding", "id": r["id"], "revision": "not_recorded",
              "hash": "not_recorded"} for r in audit_findings] +
            [{"kind": "vault_artifact", "id": r["evidence_id"], "revision": r["version"],
              "hash": r["file_hash"] or "not_recorded"} for r in audit_proof])
    sources, inputs = [], {}
    source_specs = [
        ("frameworks", [framework_id], "Selected framework", "aria"),
        ("controls", [r["id"] for r in controls], "Controls", "aria"),
        ("aria_documents", [r["id"] for r in documents], "Controlled documents", "aria"),
    ]
    if audit is not None:
        source_specs.extend([
            ("grid_audits", [audit_id], "Selected GRID audit", "grid"),
            ("grid_controls", [r["id"] for r in audit_controls], "Audit controls", "grid"),
            ("grid_non_conformances", [r["id"] for r in audit_findings], "Audit findings", "grid"),
        ])
    source_specs.append(("evidence_items", sorted(evidence_ids), "Linked Vault artifacts", "evidence"))
    for table, ids, label, module in source_specs:
        src, inp = _source(table, ids, label, module)
        sources.append(src); inputs[table] = inp
    built = _pack("framework_auditor_register", sections, sources, inputs,
        limitations=["A policy mapping is design coverage. Only a current, independently accepted Vault link counts as operating proof.",
                     "Unadopted legacy documents without an organization owner are excluded until their ownership is reviewed."])
    built.result["framework"] = {"id": framework_id, "name": fw["name"], "updated_at": fw["updated_at"]}
    if audit is not None:
        built.result["audit"] = {"id": audit_id, "name": audit["name"], "status": audit["status"]}
        built.limitations.append("GRID audit status, findings and Vault links are separate from ARIA control acceptance. "
                                 "GRID control references are displayed as recorded, without inferring a control mapping.")
    return built


def ai_systems(db, user):
    _require(user, "ai_use.view")
    scope, params = entity_scope_sql(("governance", "application"), user, "a")
    rows = [dict(r) for r in db.execute(
        "SELECT a.id,a.name,a.description,a.is_active,a.business_unit_id,a.owner_user_id,a.updated_at,"
        "p.id AS profile_id,p.version,p.purpose,p.capability_type,p.deployment,p.provider_note,"
        "p.data_categories,p.affected_people,p.human_oversight,p.provisional_tier,p.adopted_tier,"
        "p.adopted_by,p.adopted_at,p.next_review_at,p.external_ref,p.import_review_state,"
        "p.import_claimed_status,p.source_claims_json,p.updated_at AS profile_updated_at "
        f"FROM applications a JOIN ai_use_profiles p ON p.application_id=a.id WHERE {scope} "
        "ORDER BY a.name,a.id", params).fetchall()]
    systems = [{**r, "status": ("Imported · review needed" if r["import_review_state"] == "pending"
                                else "Active" if r["is_active"] else "Retired"),
                "tier": r["adopted_tier"] or r["provisional_tier"] or "Not assessed",
                "decision": "Tier adopted" if r["adopted_by"] else "Not approved"} for r in rows]
    gaps = [{"system_id": r["id"], "system": r["name"],
             "missing": ", ".join(k for k, ok in (("Owner", r["owner_user_id"]),
                 ("Purpose", r["purpose"]), ("External reference", r["external_ref"]),
                 ("Tier decision", r["adopted_by"]), ("Review date", r["next_review_at"])) if not ok)}
            for r in rows]
    sections = {"systems": systems, "imported_claims": _claims_rows(rows, "external_ref"),
                "gaps": [g for g in gaps if g["missing"]],
                "manifest": [{"kind": "ai_profile", "id": r["profile_id"], "revision": r["version"],
                              "updated_at": r["profile_updated_at"]} for r in rows]}
    sources, inputs = [], {}
    for table, ids, label in (("applications", [r["id"] for r in rows], "AI applications"),
                              ("ai_use_profiles", [r["profile_id"] for r in rows], "AI use profiles")):
        src, inp = _source(table, ids, label, "ai_governance")
        sources.append(src); inputs[table] = inp
    return _pack("ai_systems_register", sections, sources, inputs)


def ai_risks(db, user):
    _require(user, "module.orm.access")
    scope, params = entity_scope_sql(("orm", "aims"), user, "a")
    assessments = [dict(r) for r in db.execute(
        "SELECT a.id,a.ref,a.title,a.status,a.application_id,a.business_unit_id,a.updated_at "
        f"FROM aims_assessments a WHERE {scope} ORDER BY a.id", params).fetchall()]
    risks, links, treatments = [], [], []
    app_scope, app_params = entity_scope_sql(("governance", "application"), user, "app")
    for assessment in assessments:
        for rr in db.execute("SELECT id,assessment_id,ref,strategic_objective,ai_objective,"
                             "risk_description,contributing_factors,impacted_pillar,likelihood,impact,"
                             "emv_inherent,risk_owner,rr_target,rr_appetite,rr_tolerance,in_scope,"
                             "implemented,scope_justification,status,created_at,updated_at,"
                             "source_claims_json,import_batch_id "
                             "FROM aims_risks WHERE assessment_id=%s ORDER BY id",
                             (assessment["id"],)).fetchall():
            risk = dict(rr)
            risks.append({**risk, "assessment_ref": assessment["ref"],
                          "inherent_score": (risk["likelihood"] or 0) * (risk["impact"] or 0),
                          "rubric": "ORM AIMS likelihood × impact (1–5 each)"})
            for action in db.execute("SELECT id,treatment,action_steps,responsible,due_date,control_detail,ice_score "
                                     "FROM aims_risk_controls WHERE risk_id=%s ORDER BY id", (risk["id"],)).fetchall():
                treatments.append({"risk_id": risk["id"], "risk_ref": risk["ref"], **dict(action)})
            if assessment["application_id"]:
                app = db.execute(f"SELECT app.id,app.name FROM applications app WHERE app.id=%s AND {app_scope}",
                                 [assessment["application_id"], *app_params]).fetchone()
                if app:
                    links.append({"risk_id": risk["id"], "system_id": app["id"],
                                  "system": app["name"], "basis": "Assessment"})
            for app in db.execute("SELECT app.id,app.name FROM aims_risk_applications ra "
                f"JOIN applications app ON app.id=ra.application_id WHERE ra.risk_id=%s AND {app_scope} ORDER BY app.id",
                [risk["id"], *app_params]).fetchall():
                if not any(x["risk_id"] == risk["id"] and x["system_id"] == app["id"] for x in links):
                    links.append({"risk_id": risk["id"], "system_id": app["id"],
                                  "system": app["name"], "basis": "Reviewed risk link"})
    sections = {"risks": risks, "treatments": treatments, "systems": links,
                "imported_claims": _claims_rows(risks, "ref"),
                "gaps": [{"risk_id": r["id"], "risk_ref": r["ref"], "gap": "No treatment action"}
                         for r in risks if not any(t["risk_id"] == r["id"] for t in treatments)],
                "manifest": [{"kind": "aims_assessment", "id": r["id"], "revision": r["updated_at"]}
                             for r in assessments] +
                            [{"kind": "aims_risk", "id": r["id"], "revision": r["updated_at"]}
                             for r in risks]}
    sources, inputs = [], {}
    for table, ids, label in (("aims_assessments", [r["id"] for r in assessments], "AIMS assessments"),
                              ("aims_risks", [r["id"] for r in risks], "AIMS risks"),
                              ("applications", sorted({r["system_id"] for r in links}), "Linked AI systems")):
        src, inp = _source(table, ids, label, "orm")
        sources.append(src); inputs[table] = inp
    return _pack("ai_risk_register", sections, sources, inputs,
                 limitations=["Risk scores use the live ORM AIMS rubric. Imported labels are not silently converted."])
