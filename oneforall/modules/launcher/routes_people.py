"""
Launcher sub-router: People Directory.

Provides a cross-module people registry - staff, their roles, departments,
and which compliance items (risks, controls, tasks) they own or are assigned to.
Supports manual entry and Excel bulk import.
"""
import io
import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from modules.launcher._route_helpers import (
    require_auth, shell_ctx, shell_templates, get_db,
    _json_body,)

router = APIRouter()


@router.get("/people", response_class=HTMLResponse)
@require_auth
async def people_directory_page(request: Request):
    ctx = shell_ctx(request, active_module="platform", active_section="people")
    return shell_templates.TemplateResponse(request, "people_directory.html", ctx)


@router.get("/api/people")
@require_auth
async def api_people_list(request: Request):
    db = get_db()
    try:
        rows = db.execute("""
            SELECT p.*, u.username, u.email AS user_email
            FROM people_directory p
            LEFT JOIN users u ON u.id = p.user_id
            ORDER BY p.department, p.full_name
        """).fetchall()
        people = [dict(r) for r in rows]
        departments = sorted(set(p["department"] for p in people if p["department"]))
        return JSONResponse({"items": people, "departments": departments, "total": len(people)})
    finally:
        db.close()


@router.get("/api/people/departments")
@require_auth
async def api_people_departments(request: Request):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT DISTINCT department FROM people_directory WHERE department IS NOT NULL AND department != '' ORDER BY department"
        ).fetchall()
        return JSONResponse({"departments": [r["department"] for r in rows]})
    finally:
        db.close()


@router.get("/api/people/{pid}/profile")
@require_auth
async def api_person_profile(request: Request, pid: int):
    db = get_db()
    try:
        person = db.execute(
            "SELECT p.*, u.username FROM people_directory p LEFT JOIN users u ON u.id = p.user_id WHERE p.id = %s",
            (pid,)
        ).fetchone()
        if not person:
            return JSONResponse({"error": "Not found"}, status_code=404)
        result = dict(person)

        result["tasks"] = [dict(r) for r in db.execute(
            "SELECT id, title, status, due_date FROM task_board WHERE assigned_to = %s ORDER BY due_date",
            (pid,)
        ).fetchall()]

        result["risks"] = [dict(r) for r in db.execute(
            "SELECT id, title, category, status FROM risk_register WHERE owner_id = %s ORDER BY created_at DESC",
            (pid,)
        ).fetchall()]

        return JSONResponse(result)
    finally:
        db.close()


@router.post("/api/people")
@require_auth
async def api_people_create(request: Request):
    data = await _json_body(request)
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return JSONResponse({"error": "full_name is required"}, status_code=400)
    db = get_db()
    try:
        from database import insert_returning_id
        pid = insert_returning_id(
            db,
            "INSERT INTO people_directory (full_name, email, phone, job_title, department, manager_id, user_id, notes, is_active) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                full_name,
                data.get("email") or None,
                data.get("phone") or None,
                data.get("job_title") or None,
                data.get("department") or None,
                data.get("manager_id") or None,
                data.get("user_id") or None,
                data.get("notes") or None,
                1,
            )
        )
        db.commit()
        person = db.execute("SELECT * FROM people_directory WHERE id = %s", (pid,)).fetchone()
        return JSONResponse({"ok": True, "person": dict(person)})
    finally:
        db.close()


@router.patch("/api/people/{pid}")
@require_auth
async def api_people_update(request: Request, pid: int):
    data = await _json_body(request)
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM people_directory WHERE id = %s", (pid,)).fetchone()
        if not existing:
            return JSONResponse({"error": "Not found"}, status_code=404)
        fields = ["full_name", "email", "phone", "job_title", "department", "manager_id", "user_id", "notes", "is_active"]
        updates, values = [], []
        for f in fields:
            if f in data:
                updates.append(f"{f} = %s")
                values.append(data[f] or None if f not in ("is_active", "manager_id", "user_id") else data[f])
        if not updates:
            return JSONResponse({"error": "No fields to update"}, status_code=400)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(pid)
        db.execute(f"UPDATE people_directory SET {', '.join(updates)} WHERE id = %s", values)
        db.commit()
        person = db.execute("SELECT * FROM people_directory WHERE id = %s", (pid,)).fetchone()
        return JSONResponse({"ok": True, "person": dict(person)})
    finally:
        db.close()


@router.delete("/api/people/{pid}")
@require_auth
async def api_people_delete(request: Request, pid: int):
    db = get_db()
    try:
        db.execute("DELETE FROM people_directory WHERE id = %s", (pid,))
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


@router.post("/api/people/import")
@require_auth
async def api_people_import(request: Request):
    """Bulk import from Excel. Expected columns: Full Name, Email, Phone, Job Title, Department, Notes."""
    try:
        import openpyxl
    except ImportError:
        return JSONResponse({"error": "openpyxl not installed on this server"}, status_code=500)

    body = await request.body()
    if len(body) > 5 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 5 MB)"}, status_code=413)

    try:
        wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as exc:
        return JSONResponse({"error": f"Could not parse Excel file: {exc}"}, status_code=400)

    if not rows:
        return JSONResponse({"error": "Empty file"}, status_code=400)

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]

    def _col(name):
        aliases = {
            "full_name": ["full name", "name", "full_name", "employee name", "staff name"],
            "email":     ["email", "e-mail", "email address"],
            "phone":     ["phone", "telephone", "mobile", "contact"],
            "job_title": ["job title", "title", "position", "role"],
            "department":["department", "dept", "team", "division"],
            "notes":     ["notes", "comments", "remarks"],
        }
        for idx, h in enumerate(headers):
            if h in aliases.get(name, [name]):
                return idx
        return None

    col_map = {f: _col(f) for f in ["full_name", "email", "phone", "job_title", "department", "notes"]}

    if col_map["full_name"] is None:
        return JSONResponse({"error": "Could not find a 'Full Name' or 'Name' column"}, status_code=400)

    db = get_db()
    try:
        from database import insert_returning_id
        imported, skipped = 0, 0
        for row in rows[1:]:
            def _val(field):
                idx = col_map.get(field)
                if idx is None or idx >= len(row):
                    return None
                v = row[idx]
                return str(v).strip() if v is not None else None

            full_name = _val("full_name")
            if not full_name:
                skipped += 1
                continue

            existing = db.execute(
                "SELECT id FROM people_directory WHERE lower(trim(full_name)) = lower(trim(%s))",
                (full_name,)
            ).fetchone()
            if existing:
                skipped += 1
                continue

            insert_returning_id(
                db,
                "INSERT INTO people_directory (full_name, email, phone, job_title, department, notes, is_active) "
                "VALUES (%s,%s,%s,%s,%s,%s,1)",
                (_val("full_name"), _val("email"), _val("phone"), _val("job_title"), _val("department"), _val("notes"))
            )
            imported += 1
        db.commit()
        return JSONResponse({"ok": True, "imported": imported, "skipped": skipped})
    finally:
        db.close()
