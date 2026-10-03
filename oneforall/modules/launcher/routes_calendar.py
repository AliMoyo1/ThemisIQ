"""PLAN-36 T10: isolated, tenant-scoped calendar routes and BCM projections."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from database import insert_returning_id
from core.security import sanitize_text, sanitize_short, validate_int, validate_choice, validate_date
from modules.governance.data_service import bu_scope_ids
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, shell_ctx, shell_templates, get_db, _json_body, has_capability,
)

router = APIRouter()


@router.get("/calendar", response_class=HTMLResponse)
@require_auth
async def calendar_page(request: Request):
    """Compliance calendar page."""
    ctx = shell_ctx(request, active_module="platform", active_section="calendar")
    return shell_templates.TemplateResponse(request, "calendar.html", ctx)


def _calendar_scope(user):
    """Explicit scope for shared SQLite and tenant PostgreSQL calendar rows."""
    org_id = user.get("org_id")
    if not org_id:
        return ["1=0"], []
    where = [
        "(ce.org_id=%s OR (ce.org_id IS NULL AND EXISTS "
        "(SELECT 1 FROM users creator WHERE creator.id=ce.created_by AND creator.org_id=%s)))"
    ]
    params = [org_id, org_id]
    scope = bu_scope_ids(user)
    if scope is not None:
        marks = ",".join(["%s"] * len(scope)) if scope else "NULL"
        where.append(f"(ce.business_unit_id IS NULL OR ce.business_unit_id IN ({marks}))")
        params.extend(scope)
    return where, params


def _calendar_assignee_ok(db, org_id, business_unit_id, assignee):
    if not assignee:
        return True
    row = db.execute(
        "SELECT business_unit_id,is_super_admin FROM users "
        "WHERE id=%s AND org_id=%s AND is_active=1 AND deleted_at IS NULL",
        (assignee, org_id),
    ).fetchone()
    return bool(row and (business_unit_id is None or row["is_super_admin"]
                         or row["business_unit_id"] == business_unit_id))


def _calendar_event(db, user, event_id):
    where, params = _calendar_scope(user)
    row = db.execute(
        "SELECT ce.* FROM calendar_events ce WHERE ce.id=%s AND " + " AND ".join(where),
        [event_id] + params,
    ).fetchone()
    return dict(row) if row else None


@router.get("/api/calendar/events")
@require_auth
async def api_calendar_events(request: Request):
    """List only events visible to this organization's business-unit scope."""
    where, params = _calendar_scope(request.state.user)
    db = get_db()
    try:
        start = request.query_params.get("start", "")
        end = request.query_params.get("end", "")
        module = request.query_params.get("module", "")
        event_type = request.query_params.get("type", "")
        if start:
            where.append("ce.start_date >= %s"); params.append(start)
        if end:
            where.append("ce.start_date <= %s"); params.append(end)
        if module:
            where.append("ce.module = %s"); params.append(module)
        if event_type:
            where.append("ce.event_type = %s"); params.append(event_type)
        rows = db.execute(
            "SELECT ce.*, u.full_name as assigned_name "
            "FROM calendar_events ce LEFT JOIN users u ON ce.assigned_to = u.id "
            f"WHERE {' AND '.join(where)} ORDER BY ce.start_date LIMIT 500",
            params,
        ).fetchall()
        return _JSONResp([dict(r) for r in rows])
    finally:
        db.close()


@router.post("/api/calendar/events", status_code=201)
@require_auth
async def api_calendar_event_create(request: Request):
    data = await _json_body(request)
    user = request.state.user
    title = sanitize_short(data.get("title"), 255)
    start_date = validate_date(data.get("start_date"))
    if not title or not start_date or not user.get("org_id"):
        return _JSONResp({"error": "Title, start date, and organization are required."}, 400)
    module = sanitize_short(data.get("module"), 50)
    entity_type = sanitize_short(data.get("entity_type"), 50)
    if module == "bcm" and entity_type == "exercise":
        return _JSONResp({"error": "Exercise calendar events are managed from BCM."}, 400)
    assigned = validate_int(data.get("assigned_to"))
    db = get_db()
    try:
        if not _calendar_assignee_ok(db, user["org_id"], user.get("business_unit_id"), assigned):
            return _JSONResp({"error": "Assignee is outside this event's scope."}, 400)
        eid = insert_returning_id(
            db,
            "INSERT INTO calendar_events (title,description,event_type,module,entity_type,"
            "entity_id,start_date,end_date,all_day,recurrence,assigned_to,created_by,org_id,business_unit_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, sanitize_text(data.get("description"), 2000),
             validate_choice(data.get("event_type"),
                             {"audit","review","deadline","meeting","training","other"}, "other"),
             module, entity_type, validate_int(data.get("entity_id")), start_date,
             validate_date(data.get("end_date")), 1 if data.get("all_day", True) else 0,
             validate_choice(data.get("recurrence"), {"","daily","weekly","monthly","yearly"}, ""),
             assigned, user["id"], user["org_id"], user.get("business_unit_id")),
        )
        db.commit()
        return _JSONResp({"id": eid}, status_code=201)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.put("/api/calendar/events/{eid}")
@require_auth
async def api_calendar_event_update(request: Request, eid: int):
    data = await _json_body(request)
    user = request.state.user
    db = get_db()
    try:
        row = _calendar_event(db, user, eid)
        if not row:
            return _JSONResp({"error": "Event not found."}, 404)
        if row["module"] == "bcm" and row["entity_type"] == "exercise":
            return _JSONResp({"error": "Exercise calendar events are managed from BCM."}, 403)
        if data.get("module", row["module"]) == "bcm" and row["entity_type"] == "exercise":
            return _JSONResp({"error": "Exercise calendar events are managed from BCM."}, 403)
        if row["created_by"] != user["id"] and not has_capability(user, "platform.manage_users"):
            return _JSONResp({"error": "Access denied."}, 403)
        _SANITIZERS = {
            "title": lambda v: sanitize_short(v, 255),
            "description": lambda v: sanitize_text(v, 2000),
            "event_type": lambda v: validate_choice(v, {"audit", "review", "deadline", "meeting", "training", "other"}),
            "module": lambda v: sanitize_short(v, 50),
            "start_date": lambda v: validate_date(v),
            "end_date": lambda v: validate_date(v),
            "all_day": lambda v: 1 if v else 0,
            "recurrence": lambda v: validate_choice(v, {"", "daily", "weekly", "monthly", "yearly"}),
            "assigned_to": lambda v: validate_int(v),
            "status": lambda v: validate_choice(v, {"scheduled", "in_progress", "completed", "cancelled"}),
        }
        if "assigned_to" in data and not _calendar_assignee_ok(
            db, user["org_id"], row["business_unit_id"], validate_int(data["assigned_to"])
        ):
            return _JSONResp({"error": "Assignee is outside this event's scope."}, 400)
        fields, params = [], []
        for key, sanitizer in _SANITIZERS.items():
            if key in data:
                val = sanitizer(data[key])
                if val is not None:
                    fields.append(f"{key} = %s")
                    params.append(val)
        if fields:
            params.append(eid)
            db.execute(f"UPDATE calendar_events SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
        return _JSONResp({"success": True})
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.delete("/api/calendar/events/{eid}")
@require_auth
async def api_calendar_event_delete(request: Request, eid: int):
    user = request.state.user
    db = get_db()
    try:
        row = _calendar_event(db, user, eid)
        if not row:
            return _JSONResp({"error": "Event not found."}, 404)
        if row["module"] == "bcm" and row["entity_type"] == "exercise":
            return _JSONResp({"error": "Exercise calendar events are managed from BCM."}, 403)
        if row["created_by"] != user["id"] and not has_capability(user, "platform.manage_users"):
            return _JSONResp({"error": "Access denied."}, 403)
        db.execute("DELETE FROM calendar_events WHERE id=%s", (eid,))
        db.commit()
        return _JSONResp({"success": True})
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
