"""
Launcher sub-router: Workflows, SLA engine, Communication templates.
Process automation routes.
"""
import html
import json as json_lib
from datetime import timedelta

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from core.timeutils import utcnow
from database import insert_returning_id, sql_now_offset

from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, log_audit,
    shell_ctx, shell_templates, get_db,
)

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# WORKFLOW TEMPLATES (pre-built)
# ═════════════════════════════════════════════════════════════════════════════

_WORKFLOW_TEMPLATES = [
    {
        "id": "policy_approval",
        "name": "Policy Approval",
        "description": "Route new or updated policies through review and sign-off",
        "trigger_module": "aria",
        "trigger_action": "policy.created",
        "category": "Governance",
        "steps": [
            {"step": 1, "name": "Author Review", "type": "approval", "role": "policy_author",
             "description": "Author confirms policy is ready for review"},
            {"step": 2, "name": "Compliance Review", "type": "approval", "role": "compliance_mgr",
             "description": "Compliance manager reviews policy for regulatory alignment"},
            {"step": 3, "name": "Final Approval", "type": "approval", "role": "policy_approver",
             "description": "Approver signs off and publishes the policy"},
        ],
    },
    {
        "id": "risk_assessment",
        "name": "Risk Assessment Review",
        "description": "Escalated risks require multi-level sign-off before mitigation",
        "trigger_module": "platform",
        "trigger_action": "risk.escalated",
        "category": "Risk",
        "steps": [
            {"step": 1, "name": "Risk Owner Assessment", "type": "approval", "role": "risk_owner",
             "description": "Risk owner confirms severity and proposed treatment"},
            {"step": 2, "name": "Compliance Sign-off", "type": "approval", "role": "compliance_mgr",
             "description": "Compliance validates risk is within tolerance or requires action"},
        ],
    },
    {
        "id": "audit_closure",
        "name": "Audit Closure",
        "description": "Close an audit after findings are resolved and evidence collected",
        "trigger_module": "grid",
        "trigger_action": "audit.findings_resolved",
        "category": "Audit",
        "steps": [
            {"step": 1, "name": "Auditor Final Check", "type": "approval", "role": "auditor",
             "description": "Auditor confirms all findings addressed"},
            {"step": 2, "name": "Audit Lead Sign-off", "type": "approval", "role": "audit_lead",
             "description": "Lead auditor approves closure"},
            {"step": 3, "name": "Executive Acknowledgement", "type": "notification", "role": "compliance_mgr",
             "description": "Compliance manager notified of audit completion"},
        ],
    },
    {
        "id": "incident_response",
        "name": "Incident Response",
        "description": "Coordinate BCM incident from declaration through resolution",
        "trigger_module": "bcm",
        "trigger_action": "incident.declared",
        "category": "BCM",
        "steps": [
            {"step": 1, "name": "Incident Commander Assigns", "type": "approval", "role": "incident_commander",
             "description": "Commander confirms incident severity and assigns response team"},
            {"step": 2, "name": "Response Execution", "type": "task", "role": "bcm_responder",
             "description": "Response team executes continuity plan"},
            {"step": 3, "name": "Resolution Confirmation", "type": "approval", "role": "bcm_manager",
             "description": "BCM manager confirms incident resolved and initiates lessons learned"},
        ],
    },
    {
        "id": "data_breach_72hr",
        "name": "Data Breach 72h Notification",
        "description": "GDPR Article 33 — notify supervisory authority within 72 hours",
        "trigger_module": "sentinel",
        "trigger_action": "breach.confirmed",
        "category": "Privacy",
        "steps": [
            {"step": 1, "name": "DPO Assessment", "type": "approval", "role": "dpo",
             "description": "DPO assesses if breach is notifiable"},
            {"step": 2, "name": "Notification Draft", "type": "task", "role": "privacy_analyst",
             "description": "Draft notification to supervisory authority"},
            {"step": 3, "name": "DPO Submission", "type": "approval", "role": "dpo",
             "description": "DPO approves and submits notification"},
        ],
    },
    {
        "id": "vendor_onboarding",
        "name": "Vendor Due Diligence",
        "description": "Assess new third-party vendor before granting data access",
        "trigger_module": "platform",
        "trigger_action": "vendor.created",
        "category": "Third Party",
        "steps": [
            {"step": 1, "name": "Security Questionnaire", "type": "task", "role": "compliance_mgr",
             "description": "Send and review vendor security questionnaire"},
            {"step": 2, "name": "Privacy Impact Check", "type": "approval", "role": "dpo",
             "description": "DPO confirms data processing agreement is adequate"},
            {"step": 3, "name": "Approval to Onboard", "type": "approval", "role": "compliance_mgr",
             "description": "Final sign-off to proceed with vendor engagement"},
        ],
    },
    {
        "id": "change_management",
        "name": "Change Management",
        "description": "Review and approve system or process changes before implementation",
        "trigger_module": "platform",
        "trigger_action": "change.requested",
        "category": "Operations",
        "steps": [
            {"step": 1, "name": "Impact Assessment", "type": "task", "role": "compliance_mgr",
             "description": "Assess impact on compliance controls and frameworks"},
            {"step": 2, "name": "Technical Review", "type": "approval", "role": "audit_lead",
             "description": "Technical lead reviews implementation plan"},
            {"step": 3, "name": "Approve & Schedule", "type": "approval", "role": "compliance_mgr",
             "description": "Final approval and deployment window scheduling"},
        ],
    },
]


@router.get("/api/workflows/templates")
@require_auth
async def api_workflow_templates(request: Request):
    """List available pre-built workflow templates."""
    return _JSONResp(_WORKFLOW_TEMPLATES)


@router.post("/api/workflows/templates/{template_id}/install")
@require_auth
async def api_workflow_template_install(request: Request, template_id: str):
    """Install a workflow template as a new definition."""
    template = next((t for t in _WORKFLOW_TEMPLATES if t["id"] == template_id), None)
    if not template:
        raise HTTPException(404, "Template not found")
    db = get_db()
    try:
        # Check if already installed
        existing = db.execute(
            "SELECT id FROM workflow_definitions WHERE name = %s", (template["name"],)
        ).fetchone()
        if existing:
            return _JSONResp({"id": existing[0], "already_exists": True})
        wid = insert_returning_id(
            db,
            "INSERT INTO workflow_definitions (name, description, trigger_module, trigger_action, steps_json, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                template["name"],
                template["description"],
                template["trigger_module"],
                template["trigger_action"],
                json_lib.dumps(template["steps"]),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "workflow_template_install",
              details=f"Installed template: {template['name']}")
    return _JSONResp({"id": wid, "installed": True}, status_code=201)


# ═════════════════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/workflows", response_class=HTMLResponse)
@require_auth
async def workflows_page(request: Request):
    """Workflow management page."""
    ctx = shell_ctx(request, active_module="platform", active_section="workflows")
    return shell_templates.TemplateResponse(request, "workflows.html", ctx)


@router.get("/api/workflows/definitions")
@require_auth
async def api_workflow_definitions(request: Request):
    """List all workflow definitions."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT wd.*, u.full_name as creator_name "
            "FROM workflow_definitions wd LEFT JOIN users u ON wd.created_by = u.id "
            "ORDER BY wd.created_at DESC"
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/workflows/definitions", status_code=201)
@require_auth
async def api_workflow_definition_create(request: Request):
    """Create a workflow definition."""
    data = await request.json()
    db = get_db()
    try:
        steps = data.get("steps", [])
        wid = insert_returning_id(
            db,
            "INSERT INTO workflow_definitions (name, description, trigger_module, trigger_action, steps_json, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", "Untitled Workflow"),
                data.get("description", ""),
                data.get("trigger_module", ""),
                data.get("trigger_action", ""),
                json_lib.dumps(steps),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "workflow_create", details=f"Created workflow: {data.get('name')}")
    return _JSONResp({"id": wid}, status_code=201)


@router.put("/api/workflows/definitions/{wid}")
@require_auth
async def api_workflow_definition_update(request: Request, wid: int):
    """Update a workflow definition."""
    data = await request.json()
    db = get_db()
    try:
        fields = []
        params = []
        if "name" in data:
            fields.append("name = %s")
            params.append(data["name"])
        if "description" in data:
            fields.append("description = %s")
            params.append(data["description"])
        if "trigger_module" in data:
            fields.append("trigger_module = %s")
            params.append(data["trigger_module"])
        if "trigger_action" in data:
            fields.append("trigger_action = %s")
            params.append(data["trigger_action"])
        if "steps" in data:
            fields.append("steps_json = %s")
            params.append(json_lib.dumps(data["steps"]))
        if "is_active" in data:
            fields.append("is_active = %s")
            params.append(1 if data["is_active"] else 0)
        if fields:
            params.append(wid)
            db.execute(f"UPDATE workflow_definitions SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/workflows/definitions/{wid}")
@require_auth
async def api_workflow_definition_delete(request: Request, wid: int):
    """Soft-disable a workflow definition."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        db.execute("UPDATE workflow_definitions SET is_active = 0 WHERE id = %s", (wid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.get("/api/workflows/instances")
@require_auth
async def api_workflow_instances(request: Request):
    """List workflow instances with optional filters."""
    db = get_db()
    try:
        status = request.query_params.get("status", "")
        module = request.query_params.get("module", "")
        where = ["1=1"]
        params = []
        if status:
            where.append("wi.status = %s")
            params.append(status)
        if module:
            where.append("wi.entity_module = %s")
            params.append(module)
        rows = db.execute(
            f"SELECT wi.*, wd.name as workflow_name, u.full_name as started_by_name "
            f"FROM workflow_instances wi "
            f"LEFT JOIN workflow_definitions wd ON wi.definition_id = wd.id "
            f"LEFT JOIN users u ON wi.started_by = u.id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY wi.started_at DESC LIMIT 100",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/workflows/instances", status_code=201)
@require_auth
async def api_workflow_instance_start(request: Request):
    """Start a new workflow instance."""
    data = await request.json()
    db = get_db()
    try:
        defn = db.execute("SELECT * FROM workflow_definitions WHERE id = %s AND is_active = 1",
                          (data.get("definition_id"),)).fetchone()
        if not defn:
            return _JSONResp({"error": "Workflow definition not found or inactive"}, status_code=404)

        iid = insert_returning_id(
            db,
            "INSERT INTO workflow_instances (definition_id, entity_module, entity_type, entity_id, started_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (defn["id"], data.get("entity_module", ""), data.get("entity_type", ""),
             data.get("entity_id"), request.state.user["id"])
        )
        db.commit()

        # Create first step action
        steps = json_lib.loads(defn["steps_json"]) if defn["steps_json"] else []
        if steps:
            first_step = steps[0]
            db.execute(
                "INSERT INTO workflow_actions (instance_id, step_index, action_type, assigned_to) VALUES (%s,%s,%s,%s)",
                (iid, 0, first_step.get("action_type", "approve"), first_step.get("assigned_to"))
            )
            db.commit()
            # Notify assignee
            if first_step.get("assigned_to"):
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                    (first_step["assigned_to"], f"Action Required: {defn['name']}",
                     f"Step 1: {first_step.get('label', 'Review & Approve')}",
                     f"/workflows?instance={iid}", "workflow")
                )
                db.commit()
    finally:
        db.close()
    return _JSONResp({"id": iid}, status_code=201)


@router.get("/api/workflows/instances/{iid}")
@require_auth
async def api_workflow_instance_get(request: Request, iid: int):
    """Get a workflow instance with its actions."""
    db = get_db()
    try:
        inst = db.execute(
            "SELECT wi.*, wd.name as workflow_name, wd.steps_json, u.full_name as started_by_name "
            "FROM workflow_instances wi "
            "LEFT JOIN workflow_definitions wd ON wi.definition_id = wd.id "
            "LEFT JOIN users u ON wi.started_by = u.id "
            "WHERE wi.id = %s", (iid,)
        ).fetchone()
        if not inst:
            return _JSONResp({"error": "Not found"}, status_code=404)
        actions = db.execute(
            "SELECT wa.*, u.full_name as assigned_name "
            "FROM workflow_actions wa LEFT JOIN users u ON wa.assigned_to = u.id "
            "WHERE wa.instance_id = %s ORDER BY wa.step_index",
            (iid,)
        ).fetchall()
    finally:
        db.close()
    result = dict(inst)
    result["steps"] = json_lib.loads(result.pop("steps_json", "[]") or "[]")
    result["actions"] = [dict(a) for a in actions]
    return _JSONResp(result)


@router.post("/api/workflows/actions/{aid}/decide")
@require_auth
async def api_workflow_action_decide(request: Request, aid: int):
    """Approve or reject a workflow action step."""
    data = await request.json()
    decision = data.get("decision", "approve")  # approve | reject | return
    comment = data.get("comment", "")
    db = get_db()
    try:
        action = db.execute("SELECT * FROM workflow_actions WHERE id = %s", (aid,)).fetchone()
        if not action:
            return _JSONResp({"error": "Action not found"}, status_code=404)
        if action["status"] != "pending":
            return _JSONResp({"error": "Action already processed"}, status_code=400)

        # Update action
        db.execute(
            "UPDATE workflow_actions SET status = %s, comment = %s, acted_at = CURRENT_TIMESTAMP WHERE id = %s",
            (decision + "d", comment, aid)  # approved, rejected, returned
        )
        db.commit()

        iid = action["instance_id"]
        inst = db.execute("SELECT * FROM workflow_instances WHERE id = %s", (iid,)).fetchone()
        defn = db.execute("SELECT * FROM workflow_definitions WHERE id = %s", (inst["definition_id"],)).fetchone()
        steps = json_lib.loads(defn["steps_json"]) if defn["steps_json"] else []

        if decision == "approve":
            next_step = action["step_index"] + 1
            if next_step < len(steps):
                # Advance to next step
                db.execute("UPDATE workflow_instances SET current_step = %s WHERE id = %s", (next_step, iid))
                next_s = steps[next_step]
                db.execute(
                    "INSERT INTO workflow_actions (instance_id, step_index, action_type, assigned_to) VALUES (%s,%s,%s,%s)",
                    (iid, next_step, next_s.get("action_type", "approve"), next_s.get("assigned_to"))
                )
                db.commit()
                if next_s.get("assigned_to"):
                    db.execute(
                        "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                        (next_s["assigned_to"], f"Action Required: {defn['name']}",
                         f"Step {next_step + 1}: {next_s.get('label', 'Review')}",
                         f"/workflows?instance={iid}", "workflow")
                    )
                    db.commit()
            else:
                # Workflow complete
                db.execute(
                    "UPDATE workflow_instances SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (iid,)
                )
                db.commit()
                # Notify starter
                if inst["started_by"]:
                    db.execute(
                        "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                        (inst["started_by"], f"Workflow Completed: {defn['name']}",
                         "All approval steps have been completed.",
                         f"/workflows?instance={iid}", "workflow")
                    )
                    db.commit()
        elif decision == "reject":
            db.execute(
                "UPDATE workflow_instances SET status = 'rejected', completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                (iid,)
            )
            db.commit()
            if inst["started_by"]:
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                    (inst["started_by"], f"Workflow Rejected: {defn['name']}",
                     f"Rejected at step {action['step_index'] + 1}: {comment}",
                     f"/workflows?instance={iid}", "workflow")
                )
                db.commit()
        elif decision == "return":
            # Restart from step 0 so the submitter can revise and resubmit
            db.execute(
                "UPDATE workflow_instances SET current_step = 0, status = 'active' WHERE id = %s",
                (iid,)
            )
            first_step = steps[0] if steps else {}
            db.execute(
                "INSERT INTO workflow_actions (instance_id, step_index, action_type, assigned_to) "
                "VALUES (%s, 0, %s, %s)",
                (iid, first_step.get("action_type", "approve"), first_step.get("assigned_to"))
            )
            db.commit()
            if inst["started_by"]:
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                    (inst["started_by"], f"Workflow Returned for Revision: {defn['name']}",
                     f"Returned at step {action['step_index'] + 1}: {comment or 'Please review and resubmit.'}",
                     f"/workflows?instance={iid}", "workflow")
                )
                db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True, "decision": decision})


@router.get("/api/workflows/my-actions")
@require_auth
async def api_my_workflow_actions(request: Request):
    """Get pending workflow actions assigned to current user."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        rows = db.execute(
            "SELECT wa.*, wi.entity_module, wi.entity_type, wi.entity_id, wd.name as workflow_name "
            "FROM workflow_actions wa "
            "JOIN workflow_instances wi ON wa.instance_id = wi.id "
            "JOIN workflow_definitions wd ON wi.definition_id = wd.id "
            "WHERE wa.assigned_to = %s AND wa.status = 'pending' "
            "ORDER BY wa.created_at DESC",
            (uid,)
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


# ═════════════════════════════════════════════════════════════════════════════
# SLA ENGINE
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/sla/definitions")
@require_auth
async def api_sla_definitions(request: Request):
    """List SLA definitions."""
    db = get_db()
    try:
        module = request.query_params.get("module", "")
        if module:
            rows = db.execute("SELECT * FROM sla_definitions WHERE module = %s ORDER BY name", (module,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM sla_definitions ORDER BY module, name").fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/sla/definitions", status_code=201)
@require_auth
async def api_sla_definition_create(request: Request):
    """Create an SLA definition."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    name = str(data.get("name", "")).strip()
    if not name:
        return _JSONResp({"error": "Name is required"}, status_code=400)
    module = str(data.get("module", "")).strip()
    entity_type = str(data.get("entity_type", "")).strip()
    priority = str(data.get("priority", "normal")).strip()
    if priority not in ("low", "normal", "high", "critical"):
        priority = "normal"
    # Validate hours — must be positive integers or None
    def _safe_hours(val):
        if val is None or val == "" or val == "null":
            return None
        h = int(val)
        if h < 1 or h > 8760:  # max 1 year
            raise ValueError
        return h
    try:
        response_hours = _safe_hours(data.get("response_hours"))
        resolution_hours = _safe_hours(data.get("resolution_hours"))
        escalation_hours = _safe_hours(data.get("escalation_hours"))
    except (ValueError, TypeError):
        return _JSONResp({"error": "Hours must be positive integers (1-8760)"}, status_code=400)
    db = get_db()
    try:
        sid = insert_returning_id(
            db,
            "INSERT INTO sla_definitions (name, module, entity_type, response_hours, resolution_hours, escalation_hours, priority) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (name, module, entity_type, response_hours, resolution_hours, escalation_hours, priority)
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "sla_create", details=f"Created SLA: {name}")
    return _JSONResp({"id": sid}, status_code=201)


@router.put("/api/sla/definitions/{sid}")
@require_auth
async def api_sla_definition_update(request: Request, sid: int):
    """Update an SLA definition."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    db = get_db()
    try:
        fields, params = [], []
        for key in ("name", "module", "entity_type", "response_hours", "resolution_hours", "escalation_hours", "priority", "is_active"):
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])
        if fields:
            params.append(sid)
            db.execute(f"UPDATE sla_definitions SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/sla/instances", status_code=201)
@require_auth
async def api_sla_instance_start(request: Request):
    """Start tracking an SLA for a specific entity."""
    data = await request.json()
    def_id = data.get("definition_id")
    if not def_id:
        return _JSONResp({"error": "definition_id is required"}, status_code=400)
    entity_module = str(data.get("entity_module", "")).strip()
    entity_type = str(data.get("entity_type", "")).strip()
    entity_id = data.get("entity_id")
    db = get_db()
    try:
        defn = db.execute("SELECT * FROM sla_definitions WHERE id = %s AND is_active = 1",
                          (int(def_id),)).fetchone()
        if not defn:
            return _JSONResp({"error": "SLA definition not found or inactive"}, status_code=404)

        now_dt = utcnow()
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        response_due = (now_dt + timedelta(hours=int(defn["response_hours"]))).strftime("%Y-%m-%d %H:%M:%S") if defn["response_hours"] else None
        resolution_due = (now_dt + timedelta(hours=int(defn["resolution_hours"]))).strftime("%Y-%m-%d %H:%M:%S") if defn["resolution_hours"] else None
        escalation_due = (now_dt + timedelta(hours=int(defn["escalation_hours"]))).strftime("%Y-%m-%d %H:%M:%S") if defn["escalation_hours"] else None

        iid = insert_returning_id(
            db,
            "INSERT INTO sla_instances (definition_id, entity_module, entity_type, entity_id, "
            "started_at, response_due, resolution_due, escalation_due) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (defn["id"], entity_module, entity_type, entity_id,
             now, response_due, resolution_due, escalation_due)
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"id": iid}, status_code=201)


@router.get("/api/sla/instances")
@require_auth
async def api_sla_instances(request: Request):
    """List SLA instances with optional filters."""
    db = get_db()
    try:
        status = request.query_params.get("status", "")
        breached = request.query_params.get("breached", "")
        module = request.query_params.get("module", "")
        where = ["1=1"]
        params = []
        if status:
            where.append("si.status = %s")
            params.append(status)
        if breached:
            where.append("si.breached = %s")
            params.append(int(breached))
        if module:
            where.append("si.entity_module = %s")
            params.append(module)
        rows = db.execute(
            f"SELECT si.*, sd.name as sla_name, sd.priority, "
            f"sd.response_hours, sd.resolution_hours, sd.escalation_hours "
            f"FROM sla_instances si "
            f"LEFT JOIN sla_definitions sd ON si.definition_id = sd.id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY CASE WHEN si.breached = 1 AND si.status = 'active' THEN 0 "
            f"WHEN si.status = 'active' THEN 1 ELSE 2 END, si.started_at DESC LIMIT 200",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/sla/instances/{iid}/respond")
@require_auth
async def api_sla_respond(request: Request, iid: int):
    """Record SLA response time."""
    db = get_db()
    try:
        inst = db.execute("SELECT * FROM sla_instances WHERE id = %s", (iid,)).fetchone()
        if not inst:
            return _JSONResp({"error": "Instance not found"}, status_code=404)
        if inst["responded_at"]:
            return _JSONResp({"error": "Already responded"}, status_code=400)
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        breached = 0
        breach_type = inst.get("breach_type") or None
        if inst["response_due"] and now > inst["response_due"]:
            breached = 1
            breach_type = "response"
        db.execute(
            "UPDATE sla_instances SET responded_at = %s, breached = MAX(breached, %s), breach_type = COALESCE(breach_type, %s) WHERE id = %s",
            (now, breached, breach_type, iid)
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "sla_respond", details=f"SLA #{iid} responded")
    return _JSONResp({"success": True, "breached": bool(breached)})


@router.post("/api/sla/instances/{iid}/resolve")
@require_auth
async def api_sla_resolve(request: Request, iid: int):
    """Record SLA resolution time."""
    db = get_db()
    try:
        inst = db.execute("SELECT * FROM sla_instances WHERE id = %s", (iid,)).fetchone()
        if not inst:
            return _JSONResp({"error": "Instance not found"}, status_code=404)
        if inst["resolved_at"]:
            return _JSONResp({"error": "Already resolved"}, status_code=400)
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        breached = 0
        breach_type = inst.get("breach_type") or None
        if inst["resolution_due"] and now > inst["resolution_due"]:
            breached = 1
            breach_type = breach_type or "resolution"
        db.execute(
            "UPDATE sla_instances SET resolved_at = %s, status = 'resolved', "
            "breached = MAX(breached, %s), breach_type = COALESCE(breach_type, %s) WHERE id = %s",
            (now, breached, breach_type, iid)
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "sla_resolve", details=f"SLA #{iid} resolved")
    return _JSONResp({"success": True, "breached": bool(breached)})


@router.post("/api/sla/instances/{iid}/escalate")
@require_auth
async def api_sla_escalate(request: Request, iid: int):
    """Record SLA escalation."""
    db = get_db()
    try:
        inst = db.execute("SELECT * FROM sla_instances WHERE id = %s", (iid,)).fetchone()
        if not inst:
            return _JSONResp({"error": "Instance not found"}, status_code=404)
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "UPDATE sla_instances SET escalated_at = %s WHERE id = %s AND escalated_at IS NULL",
            (now, iid)
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "sla_escalate", details=f"SLA #{iid} escalated")
    return _JSONResp({"success": True})


@router.post("/api/sla/check-breaches")
@require_auth
async def api_sla_check_breaches(request: Request):
    """Scan all active SLA instances and flag any that have breached their deadlines."""
    db = get_db()
    try:
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # Response breaches
        resp_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'response') "
            "WHERE status = 'active' AND breached = 0 AND response_due IS NOT NULL "
            "AND responded_at IS NULL AND response_due < %s", (now,)
        ).rowcount
        # Resolution breaches
        res_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'resolution') "
            "WHERE status = 'active' AND breached = 0 AND resolution_due IS NOT NULL "
            "AND resolved_at IS NULL AND resolution_due < %s", (now,)
        ).rowcount
        # Escalation breaches (mark escalation_due passed but don't double-flag breached)
        esc_due = db.execute(
            "UPDATE sla_instances SET breach_type = CASE WHEN breach_type IS NULL THEN 'escalation' ELSE breach_type END "
            "WHERE status = 'active' AND escalation_due IS NOT NULL "
            "AND escalated_at IS NULL AND escalation_due < %s AND resolved_at IS NULL", (now,)
        ).rowcount
        db.commit()
    finally:
        db.close()
    return _JSONResp({
        "checked_at": now,
        "response_breaches": resp_breached,
        "resolution_breaches": res_breached,
        "escalation_due": esc_due,
    })


@router.get("/api/sla/stats")
@require_auth
async def api_sla_stats(request: Request):
    """SLA dashboard statistics."""
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM sla_instances").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM sla_instances WHERE status = 'active'").fetchone()[0]
        breached = db.execute("SELECT COUNT(*) FROM sla_instances WHERE breached = 1").fetchone()[0]
        resolved = db.execute("SELECT COUNT(*) FROM sla_instances WHERE status = 'resolved'").fetchone()[0]
        # Active breaches (still open)
        active_breached = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE status = 'active' AND breached = 1"
        ).fetchone()[0]
        # At risk — due within 2 hours, not yet responded/resolved
        # Use Python-formatted string for comparison against TEXT columns
        _due_cutoff = (utcnow() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        at_risk = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE status = 'active' AND breached = 0 "
            "AND ((response_due IS NOT NULL AND responded_at IS NULL AND response_due <= %s) "
            " OR (resolution_due IS NOT NULL AND resolved_at IS NULL AND resolution_due <= %s))",
            (_due_cutoff, _due_cutoff)
        ).fetchone()[0]
        # Compliance rate
        compliance_pct = round(((total - breached) / total * 100) if total > 0 else 100, 1)
        by_module = db.execute(
            "SELECT entity_module, COUNT(*) as c, SUM(breached) as breaches, "
            "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active_count "
            "FROM sla_instances GROUP BY entity_module"
        ).fetchall()
        definitions = db.execute("SELECT COUNT(*) FROM sla_definitions").fetchone()[0]
    finally:
        db.close()
    return _JSONResp({
        "total": total,
        "active": active,
        "breached": breached,
        "active_breached": active_breached,
        "at_risk": at_risk,
        "resolved": resolved,
        "compliance_pct": compliance_pct,
        "definitions": definitions,
        "by_module": [dict(r) for r in by_module],
    })


# ═════════════════════════════════════════════════════════════════════════════
# COMMUNICATION TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/comm-templates")
@require_auth
async def api_comm_templates_list(request: Request):
    """List communication templates."""
    db = get_db()
    try:
        category = request.query_params.get("category", "")
        module = request.query_params.get("module", "")
        where = ["is_active = 1"]
        params = []
        if category:
            where.append("category = %s")
            params.append(category)
        if module:
            where.append("(module = %s OR module IS NULL OR module = '')")
            params.append(module)
        rows = db.execute(
            f"SELECT * FROM comm_templates WHERE {' AND '.join(where)} ORDER BY category, name",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/comm-templates", status_code=201)
@require_auth
async def api_comm_template_create(request: Request):
    """Create a communication template."""
    data = await request.json()
    db = get_db()
    try:
        tid = insert_returning_id(
            db,
            "INSERT INTO comm_templates (name, category, module, subject_template, body_template, variables_json, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", ""),
                data.get("category", "general"),
                data.get("module", ""),
                data.get("subject_template", ""),
                data.get("body_template", ""),
                json_lib.dumps(data.get("variables", [])),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"id": tid}, status_code=201)


@router.put("/api/comm-templates/{tid}")
@require_auth
async def api_comm_template_update(request: Request, tid: int):
    """Update a communication template."""
    data = await request.json()
    db = get_db()
    try:
        fields, params = [], []
        for key in ("name", "category", "module", "subject_template", "body_template"):
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])
        if "variables" in data:
            fields.append("variables_json = %s")
            params.append(json_lib.dumps(data["variables"]))
        if fields:
            fields.append("version = version + 1")
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(tid)
            db.execute(f"UPDATE comm_templates SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/comm-templates/{tid}")
@require_auth
async def api_comm_template_delete(request: Request, tid: int):
    """Soft-delete a communication template."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        db.execute("UPDATE comm_templates SET is_active = 0 WHERE id = %s", (tid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/comm-templates/{tid}/render")
@require_auth
async def api_comm_template_render(request: Request, tid: int):
    """Render a template with provided variables."""
    data = await request.json()
    db = get_db()
    try:
        tmpl = db.execute("SELECT * FROM comm_templates WHERE id = %s AND is_active = 1", (tid,)).fetchone()
        if not tmpl:
            return _JSONResp({"error": "Template not found"}, status_code=404)
    finally:
        db.close()

    variables = data.get("variables", {})
    subject = tmpl["subject_template"] or ""
    body = tmpl["body_template"] or ""
    for key, val in variables.items():
        escaped = html.escape(str(val))
        subject = subject.replace("{{" + key + "}}", escaped)
        body = body.replace("{{" + key + "}}", escaped)
    return _JSONResp({"subject": subject, "body": body})
