"""PLAN-36 P08: scoped BCM exercise lifecycle and retained after-action record."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from core.rbac import CAPABILITIES
from core.timeutils import utcnow
from database import get_db, insert_returning_id
from modules.governance.data_service import bu_scope_ids

STATES = ("planned", "ready", "running", "completed_awaiting_review", "closed", "cancelled")
TRANSITIONS = {
    "planned": {"ready", "cancelled"},
    "ready": {"running", "cancelled"},
    "running": {"completed_awaiting_review", "cancelled"},
    "completed_awaiting_review": {"closed"},
}
CHECKLIST = (
    "Objectives and scope agreed",
    "Participants confirmed",
    "Injects and materials prepared",
)
MUTABLE_FIELDS = ("title", "type", "description", "scenario", "scheduled_date",
                  "duration_minutes", "facilitator", "participants", "objectives", "plan_id", "owner_id", "reviewer_id")


class ExerciseError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ExerciseError(400, "Date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value[:10]).isoformat() if len(value) == 10 else date.fromisoformat(value).isoformat()
    except ValueError:
        raise ExerciseError(400, "Date must be YYYY-MM-DD") from None


def _text(value, limit=5000, required=False):
    result = str(value or "").strip()
    if len(result) > limit or (required and not result):
        raise ExerciseError(400, "Required text is missing or too long")
    return result


def _int(value, field, required=False):
    if value in (None, "") and not required:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ExerciseError(400, f"Invalid {field}") from None
    if parsed <= 0:
        raise ExerciseError(400, f"Invalid {field}")
    return parsed


def _write(fn):
    db = get_db()
    try:
        result = fn(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _visible(db, actor, ex_id, scope):
    row = db.execute("SELECT * FROM bcm_exercises WHERE id=%s", (ex_id,)).fetchone()
    if not row:
        raise ExerciseError(404, "Exercise not found")
    ex = dict(row)
    if not actor.get("is_super_admin"):
        if not actor.get("org_id") or ex.get("org_id") != actor.get("org_id"):
            raise ExerciseError(404, "Exercise not found")
        if scope is not None and ex.get("business_unit_id") is not None and ex["business_unit_id"] not in scope:
            raise ExerciseError(404, "Exercise not found")
    return ex


def _state(ex):
    return {"in_progress": "running", "completed": "completed_awaiting_review"}.get(ex["status"], ex["status"])


def _can_open(db, user, ex):
    """A user can see an exercise in their BU or a descendant BU."""
    unit_id = ex.get("business_unit_id")
    if unit_id is None or user["is_super_admin"]:
        return True
    own_unit = user["business_unit_id"]
    visited = set()
    while unit_id and unit_id not in visited:
        if unit_id == own_unit:
            return True
        visited.add(unit_id)
        parent = db.execute("SELECT parent_id FROM business_units WHERE id=%s", (unit_id,)).fetchone()
        unit_id = parent["parent_id"] if parent else None
    return False


def _user(db, actor, raw_id, ex=None):
    user_id = _int(raw_id, "user", required=True)
    row = db.execute(
        "SELECT id,business_unit_id,is_super_admin FROM users "
        "WHERE id=%s AND org_id=%s AND is_active=1 AND deleted_at IS NULL",
        (user_id, actor.get("org_id")),
    ).fetchone()
    if not row:
        raise ExerciseError(400, "User is not active in this organization")
    if ex is not None and not _can_open(db, row, ex):
        raise ExerciseError(400, "User cannot access this exercise's business unit")
    return user_id


def _participant_user(db, actor, raw_id, ex):
    user_id = _user(db, actor, raw_id, ex)
    roles = sorted(CAPABILITIES["module.bcm.access"])
    marks = ",".join(["%s"] * len(roles))
    row = db.execute(
        f"SELECT id FROM user_roles WHERE user_id=%s AND role_key IN ({marks}) LIMIT 1",
        [user_id] + roles,
    ).fetchone()
    if not row:
        raise ExerciseError(400, "Participant needs BCM module access to confirm")
    return user_id


def eligible_participants(actor, ex_id):
    scope = bu_scope_ids(actor)
    db = get_db()
    try:
        ex = _visible(db, actor, ex_id, scope)
        roles = sorted(CAPABILITIES["module.bcm.access"])
        marks = ",".join(["%s"] * len(roles))
        rows = db.execute(
            "SELECT DISTINCT u.id,u.full_name,u.business_unit_id,u.is_super_admin "
            "FROM users u JOIN user_roles r ON r.user_id=u.id "
            f"WHERE u.org_id=%s AND u.is_active=1 AND u.deleted_at IS NULL AND r.role_key IN ({marks}) "
            "ORDER BY u.full_name,u.id LIMIT 500",
            [ex["org_id"]] + roles,
        ).fetchall()
        result = []
        manager_roles = sorted(CAPABILITIES["bcm.exercise.manage"])
        manager_marks = ",".join(["%s"] * len(manager_roles))
        for row in rows:
            if not _can_open(db, row, ex):
                continue
            manages = db.execute(
                f"SELECT 1 FROM user_roles WHERE user_id=%s AND role_key IN ({manager_marks}) LIMIT 1",
                [row["id"]] + manager_roles,
            ).fetchone()
            result.append({"id": row["id"], "full_name": row["full_name"],
                           "can_manage": bool(manages)})
        return result
    finally:
        db.close()


def _manager_user(db, actor, raw_id, ex=None):
    user_id = _user(db, actor, raw_id, ex)
    roles = sorted(CAPABILITIES["bcm.exercise.manage"])
    marks = ",".join(["%s"] * len(roles))
    row = db.execute(
        f"SELECT id FROM user_roles WHERE user_id=%s AND role_key IN ({marks}) LIMIT 1",
        [user_id] + roles,
    ).fetchone()
    if not row:
        raise ExerciseError(400, "Exercise owner and reviewer need BCM exercise management access")
    return user_id

def _event(db, ex_id, actor_id, kind, note):
    db.execute(
        "INSERT INTO bcm_exercise_events (exercise_id,event_type,note,occurred_at,logged_by) VALUES (%s,%s,%s,%s,%s)",
        (ex_id, kind, _text(note, 5000, required=True), _now(), actor_id),
    )


def _calendar(db, ex_id, title, scheduled_date, owner_id, actor_id, org_id, business_unit_id):
    row = db.execute(
        "SELECT id FROM calendar_events WHERE module='bcm' AND entity_type='exercise' AND entity_id=%s AND org_id=%s",
        (ex_id, org_id),
    ).fetchone()
    if not scheduled_date:
        if row:
            db.execute("DELETE FROM calendar_events WHERE id=%s", (row["id"],))
        return
    if row:
        db.execute(
            "UPDATE calendar_events SET title=%s,start_date=%s,assigned_to=%s,business_unit_id=%s WHERE id=%s",
            (title, scheduled_date, owner_id, business_unit_id, row["id"]),
        )
    else:
        db.execute(
            "INSERT INTO calendar_events "
            "(title,event_type,module,entity_type,entity_id,start_date,assigned_to,created_by,org_id,business_unit_id) "
            "VALUES (%s,'exercise','bcm','exercise',%s,%s,%s,%s,%s,%s)",
            (title, ex_id, scheduled_date, owner_id, actor_id, org_id, business_unit_id),
        )


def list_exercises(actor, limit=200):
    scope = bu_scope_ids(actor)
    db = get_db()
    try:
        where, params = "1=1", []
        if not actor.get("is_super_admin"):
            where = "org_id=%s"
            params.append(actor.get("org_id"))
            if scope is not None:
                where += " AND (business_unit_id IS NULL OR business_unit_id IN (" + ",".join(["%s"] * len(scope)) + "))"
                params.extend(scope)
        rows = db.execute(
            f"SELECT * FROM bcm_exercises WHERE {where} ORDER BY scheduled_date DESC,id DESC LIMIT %s",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_workspace(actor, ex_id):
    scope = bu_scope_ids(actor)
    db = get_db()
    try:
        ex = _visible(db, actor, ex_id, scope)
        def rows(sql):
            return [dict(r) for r in db.execute(sql, (ex_id,)).fetchall()]
        readiness = rows("SELECT * FROM bcm_exercise_readiness WHERE exercise_id=%s ORDER BY id")
        participants = rows(
            "SELECT p.id,p.user_id,p.role,p.confirmed_at,u.full_name "
            "FROM bcm_exercise_participants p JOIN users u ON u.id=p.user_id "
            "WHERE p.exercise_id=%s ORDER BY p.id"
        )
        events = rows("SELECT * FROM bcm_exercise_events WHERE exercise_id=%s ORDER BY occurred_at,id")
        actions = rows(
            "SELECT a.*,t.title,t.status,t.due_date,t.assigned_to "
            "FROM bcm_exercise_actions a LEFT JOIN task_board t ON t.id=a.task_id "
            "WHERE a.exercise_id=%s ORDER BY a.id"
        )
        prior = None
        if ex.get("scenario_id"):
            r = db.execute(
                "SELECT id,effectiveness_score,closed_at FROM bcm_exercises "
                "WHERE scenario_id=%s AND org_id=%s AND "
                "((business_unit_id=%s) OR (business_unit_id IS NULL AND %s IS NULL)) "
                "AND status='closed' AND id<>%s "
                "ORDER BY closed_at DESC,id DESC LIMIT 1",
                (ex["scenario_id"], ex["org_id"], ex["business_unit_id"], ex["business_unit_id"], ex_id),
            ).fetchone()
            prior = dict(r) if r else None
        return {"exercise": ex, "readiness": readiness, "participants": participants,
                "events": events, "actions": actions, "prior_exercise": prior}
    finally:
        db.close()


def create_exercise(actor, data):
    title = _text(data.get("title"), 255, required=True)
    scheduled = _date(data.get("scheduled_date"))
    org_id = actor.get("org_id")
    if not org_id:
        raise ExerciseError(400, "Organization is required")
    def op(db):
        owner = _manager_user(db, actor, data.get("owner_id") or actor["id"], {"business_unit_id": actor.get("business_unit_id")})
        reviewer = _manager_user(db, actor, data.get("reviewer_id") or actor["id"], {"business_unit_id": actor.get("business_unit_id")})
        scenario_id = _int(data.get("scenario_id"), "scenario")
        if scenario_id and not db.execute("SELECT id FROM bcm_scenario_library WHERE id=%s", (scenario_id,)).fetchone():
            raise ExerciseError(400, "Scenario not found")
        plan_id = _int(data.get("plan_id"), "plan")
        if plan_id and not db.execute("SELECT id FROM bcm_plans WHERE id=%s", (plan_id,)).fetchone():
            raise ExerciseError(400, "Plan not found")
        ex_id = insert_returning_id(
            db, "INSERT INTO bcm_exercises "
            "(title,type,description,scenario,scenario_id,plan_id,scheduled_date,duration_minutes,"
            "facilitator,participants,objectives,status,org_id,business_unit_id,created_by_id,owner_id,reviewer_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'planned',%s,%s,%s,%s,%s)",
            (title, _text(data.get("type"), 100), _text(data.get("description")),
             _text(data.get("scenario")), scenario_id, plan_id, scheduled,
             _int(data.get("duration_minutes"), "duration"),
             _text(data.get("facilitator"), 255), _text(data.get("participants"), 1000),
             _text(data.get("objectives")), org_id, actor.get("business_unit_id"),
             actor["id"], owner, reviewer),
        )
        if ex_id is None:
            raise ExerciseError(500, "Exercise was not created")
        for label in CHECKLIST:
            db.execute("INSERT INTO bcm_exercise_readiness (exercise_id,label) VALUES (%s,%s)", (ex_id, label))
        _event(db, ex_id, actor["id"], "transition", "Exercise planned")
        _calendar(db, ex_id, title, scheduled, owner, actor["id"], org_id, actor.get("business_unit_id"))
        return ex_id
    return _write(op)


def update_exercise(actor, ex_id, data):
    scope = bu_scope_ids(actor)
    forbidden = set(data) - set(MUTABLE_FIELDS)
    if forbidden:
        raise ExerciseError(400, "Lifecycle and review fields require their dedicated actions")
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "planned":
            raise ExerciseError(409, "Exercise metadata is locked after it starts")
        fields, values = [], []
        for key in MUTABLE_FIELDS:
            if key not in data:
                continue
            if key in ("owner_id", "reviewer_id"):
                value = _manager_user(db, actor, data[key], ex)
            elif key == "scheduled_date":
                value = _date(data[key])
            elif key in ("plan_id", "duration_minutes"):
                value = _int(data[key], key)
                if key == "plan_id" and value and not db.execute(
                    "SELECT id FROM bcm_plans WHERE id=%s", (value,)
                ).fetchone():
                    raise ExerciseError(400, "Plan not found")
            else:
                value = _text(data[key], 255 if key in ("title", "facilitator") else 5000,
                              required=key == "title")
            fields.append(f"{key}=%s")
            values.append(value)
        if fields:
            fields.append("updated_at=%s")
            values.extend([_now(), ex_id])
            db.execute("UPDATE bcm_exercises SET " + ",".join(fields) + " WHERE id=%s", values)
        calendar_owner = _manager_user(db, actor, data["owner_id"], ex) if "owner_id" in data else ex["owner_id"]
        _calendar(db, ex_id, data.get("title", ex["title"]),
                  _date(data["scheduled_date"]) if "scheduled_date" in data else ex["scheduled_date"],
                  calendar_owner, actor["id"], ex["org_id"], ex["business_unit_id"])
    _write(op)


def delete_exercise(actor, ex_id):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "planned":
            raise ExerciseError(409, "Only an unstarted planned exercise can be deleted")
        if db.execute("SELECT id FROM bcm_exercise_actions WHERE exercise_id=%s LIMIT 1", (ex_id,)).fetchone():
            raise ExerciseError(409, "Exercise has corrective actions")
        db.execute(
            "DELETE FROM calendar_events WHERE module='bcm' AND entity_type='exercise' AND entity_id=%s", (ex_id,)
        )
        db.execute("DELETE FROM bcm_exercises WHERE id=%s", (ex_id,))
    _write(op)


def set_readiness(actor, ex_id, item_id, done):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "planned":
            raise ExerciseError(409, "Readiness is locked")
        row = db.execute("SELECT id FROM bcm_exercise_readiness WHERE id=%s AND exercise_id=%s",
                         (item_id, ex_id)).fetchone()
        if not row:
            raise ExerciseError(404, "Checklist item not found")
        db.execute(
            "UPDATE bcm_exercise_readiness SET is_done=%s,confirmed_by=%s,confirmed_at=%s WHERE id=%s",
            (1 if done else 0, actor["id"] if done else None, _now() if done else None, item_id),
        )
    _write(op)


def add_participant(actor, ex_id, user_id, role):
    scope = bu_scope_ids(actor)
    role = _text(role, 100, required=True)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "planned":
            raise ExerciseError(409, "Participants are locked")
        participant = _participant_user(db, actor, user_id, ex)
        if db.execute("SELECT id FROM bcm_exercise_participants WHERE exercise_id=%s AND user_id=%s",
                      (ex_id, participant)).fetchone():
            raise ExerciseError(409, "Participant already added")
        db.execute(
            "INSERT INTO bcm_exercise_participants (exercise_id,user_id,role) VALUES (%s,%s,%s)",
            (ex_id, participant, role),
        )
    _write(op)


def confirm_participation(actor, ex_id):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "planned":
            raise ExerciseError(409, "Participant confirmation is locked")
        cur = db.execute(
            "UPDATE bcm_exercise_participants SET confirmed_at=%s "
            "WHERE exercise_id=%s AND user_id=%s AND confirmed_at IS NULL",
            (_now(), ex_id, actor["id"]),
        )
        if not cur.rowcount:
            raise ExerciseError(404, "Participant assignment not found or already confirmed")
    _write(op)


def transition(actor, ex_id, target, reason=""):
    scope = bu_scope_ids(actor)
    if target not in STATES:
        raise ExerciseError(400, "Invalid exercise state")
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        source = _state(ex)
        if target not in TRANSITIONS.get(source, set()):
            raise ExerciseError(409, "Exercise transition is not allowed")
        if target == "ready":
            missing = db.execute(
                "SELECT COUNT(*) FROM bcm_exercise_readiness WHERE exercise_id=%s AND is_done=0",
                (ex_id,),
            ).fetchone()[0]
            participants = db.execute(
                "SELECT COUNT(*),SUM(CASE WHEN confirmed_at IS NULL THEN 1 ELSE 0 END) "
                "FROM bcm_exercise_participants WHERE exercise_id=%s",
                (ex_id,),
            ).fetchone()
            if missing or not participants[0] or participants[1]:
                raise ExerciseError(409, "Complete readiness and participant confirmations first")
        if target == "closed":
            if not ex.get("aar_signed_off_at"):
                raise ExerciseError(409, "After-action review must be signed off")
            open_actions = db.execute(
                "SELECT COUNT(*) FROM bcm_exercise_actions a LEFT JOIN task_board t ON t.id=a.task_id "
                "WHERE a.exercise_id=%s AND (t.id IS NULL OR t.status!='done' OR a.verified_at IS NULL)",
                (ex_id,),
            ).fetchone()[0]
            if open_actions:
                raise ExerciseError(409, "Corrective actions must be completed and verified")
        if target == "cancelled" and not _text(reason, 500):
            raise ExerciseError(400, "Cancellation reason is required")
        stamps = {
            "running": "started_at", "completed_awaiting_review": "completed_at",
            "closed": "closed_at", "cancelled": "cancelled_at",
        }
        stamp = stamps.get(target)
        sql = "UPDATE bcm_exercises SET status=%s,updated_at=%s"
        params = [target, _now()]
        if stamp:
            sql += f",{stamp}=%s"
            params.append(_now())
        sql += " WHERE id=%s AND status=%s"
        params.extend([ex_id, ex["status"]])
        if db.execute(sql, params).rowcount != 1:
            raise ExerciseError(409, "Exercise changed; refresh and retry")
        _event(db, ex_id, actor["id"], "transition", f"{source} to {target}" +
               (f": {_text(reason, 500)}" if reason else ""))
        if target in ("ready", "cancelled"):
            db.execute(
                "UPDATE task_board SET status=%s,updated_at=%s WHERE reminder_key=%s "
                "AND status NOT IN ('done','cancelled')",
                ("done" if target == "ready" else "cancelled", _now(),
                 f"bcm:exercise:{ex['org_id']}:{ex_id}"),
            )
        if target in ("running", "completed_awaiting_review", "closed", "cancelled"):
            db.execute(
                "UPDATE calendar_events SET status=%s WHERE module='bcm' "
                "AND entity_type='exercise' AND entity_id=%s AND org_id=%s",
                ({"running": "in_progress", "completed_awaiting_review": "completed",
                  "closed": "completed", "cancelled": "cancelled"}[target],
                 ex_id, ex["org_id"]),
            )
        if target == "closed":
            report = _report_data(db, ex_id, actor, scope)
            encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
            db.execute(
                "UPDATE bcm_exercises SET report_json=%s,report_hash=%s WHERE id=%s",
                (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), ex_id),
            )
    _write(op)


def log_event(actor, ex_id, kind, note):
    scope = bu_scope_ids(actor)
    if kind not in ("inject", "observation", "decision"):
        raise ExerciseError(400, "Invalid event type")
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "running":
            raise ExerciseError(409, "Exercise is not running")
        _event(db, ex_id, actor["id"], kind, note)
    _write(op)


def save_review(actor, ex_id, data):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "completed_awaiting_review" or ex.get("aar_signed_off_at"):
            raise ExerciseError(409, "Review is not editable")
        if actor["id"] not in (ex["owner_id"], ex["reviewer_id"]):
            raise ExerciseError(403, "Only the exercise owner or reviewer can edit the review")
        total = _int(data.get("objectives_total"), "objectives_total", required=True)
        met = data.get("objectives_met")
        try:
            met = int(met)
        except (TypeError, ValueError):
            raise ExerciseError(400, "Invalid objectives_met") from None
        if met < 0 or met > total:
            raise ExerciseError(400, "Objectives met must be between zero and total")
        values = (
            _text(data.get("aar_results"), required=True),
            _text(data.get("aar_strengths")), _text(data.get("aar_gaps")),
            _text(data.get("aar_lessons"), required=True),
            met, total, round(100 * met / total), _now(), ex_id,
        )
        db.execute(
            "UPDATE bcm_exercises SET aar_results=%s,aar_strengths=%s,aar_gaps=%s,"
            "aar_lessons=%s,objectives_met=%s,objectives_total=%s,effectiveness_score=%s,"
            "updated_at=%s WHERE id=%s",
            values,
        )
    _write(op)


def sign_review(actor, ex_id):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "completed_awaiting_review" or ex.get("aar_signed_off_at"):
            raise ExerciseError(409, "Review cannot be signed off")
        if actor["id"] != ex.get("reviewer_id"):
            raise ExerciseError(403, "Only the assigned reviewer can sign off")
        open_actions = db.execute(
            "SELECT COUNT(*) FROM bcm_exercise_actions a LEFT JOIN task_board t ON t.id=a.task_id "
            "WHERE a.exercise_id=%s AND (t.id IS NULL OR t.status!='done' OR a.verified_at IS NULL)",
            (ex_id,),
        ).fetchone()[0]
        if open_actions:
            raise ExerciseError(409, "Corrective actions must be completed and verified before sign-off")
        if not ex.get("aar_results") or not ex.get("aar_lessons") or ex.get("effectiveness_score") is None:
            raise ExerciseError(409, "Complete the review before sign-off")
        db.execute(
            "UPDATE bcm_exercises SET aar_signed_off_by=%s,aar_signed_off_at=%s,updated_at=%s WHERE id=%s",
            (actor["id"], _now(), _now(), ex_id),
        )
        _event(db, ex_id, actor["id"], "review", "After-action review signed off")
    _write(op)


def add_action(actor, ex_id, data):
    scope = bu_scope_ids(actor)
    title = _text(data.get("title"), 255, required=True)
    due = _date(data.get("due_date"))
    if not due:
        raise ExerciseError(400, "Corrective action due date is required")
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) not in ("running", "completed_awaiting_review") or ex.get("aar_signed_off_at"):
            raise ExerciseError(409, "Corrective actions cannot be added now")
        owner = _user(db, actor, data.get("owner_id"), ex)
        task_id = insert_returning_id(
            db, "INSERT INTO task_board "
            "(title,description,module,entity_type,entity_id,assigned_to,priority,status,due_date,created_by,business_unit_id) "
            "VALUES (%s,%s,'bcm','exercise',%s,%s,%s,'todo',%s,%s,%s)",
            (title, _text(data.get("description")), ex_id, owner,
             data.get("priority") if data.get("priority") in ("low", "medium", "high", "critical") else "medium",
             due, actor["id"], ex["business_unit_id"]),
        )
        if task_id is None:
            raise ExerciseError(500, "Corrective task was not created")
        action_id = insert_returning_id(
            db, "INSERT INTO bcm_exercise_actions (exercise_id,task_id) VALUES (%s,%s)",
            (ex_id, task_id),
        )
        db.execute(
            "INSERT INTO notifications (user_id,module,title,message,link) VALUES (%s,'bcm',%s,%s,%s)",
            (owner, "BCM corrective action", title, f"/tasks?open={task_id}"),
        )
        _event(db, ex_id, actor["id"], "action", f"Corrective action #{action_id} created")
        return action_id
    return _write(op)


def verify_action(actor, ex_id, action_id, evidence_id):
    scope = bu_scope_ids(actor)
    def op(db):
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "completed_awaiting_review" or ex.get("aar_signed_off_at"):
            raise ExerciseError(409, "Action verification is closed")
        if actor["id"] != ex.get("reviewer_id"):
            raise ExerciseError(403, "Only the assigned reviewer can verify an action")
        row = db.execute(
            "SELECT a.id,t.status FROM bcm_exercise_actions a "
            "LEFT JOIN task_board t ON t.id=a.task_id "
            "WHERE a.id=%s AND a.exercise_id=%s AND a.verified_at IS NULL",
            (action_id, ex_id),
        ).fetchone()
        if not row:
            raise ExerciseError(404, "Action not found or already verified")
        if row["status"] != "done":
            raise ExerciseError(409, "Complete the Task Board item first")
        evidence = _int(evidence_id, "evidence", required=True)
        item = db.execute(
            "SELECT id FROM evidence_items WHERE id=%s AND org_id=%s AND status='current' "
            "AND (business_unit_id IS NULL OR business_unit_id=%s)",
            (evidence, ex["org_id"], ex["business_unit_id"]),
        ).fetchone()
        if not item:
            raise ExerciseError(404, "Evidence not found in this organization")
        db.execute(
            "UPDATE bcm_exercise_actions SET evidence_id=%s,verified_by=%s,verified_at=%s WHERE id=%s",
            (evidence, actor["id"], _now(), action_id),
        )
        _event(db, ex_id, actor["id"], "action", f"Corrective action #{action_id} verified")
    _write(op)


def _report_data(db, ex_id, actor, scope):
    ex = _visible(db, actor, ex_id, scope)
    def rows(sql):
        return [dict(r) for r in db.execute(sql, (ex_id,)).fetchall()]
    prior = None
    if ex.get("scenario_id"):
        row = db.execute(
            "SELECT id,effectiveness_score,closed_at FROM bcm_exercises "
            "WHERE scenario_id=%s AND org_id=%s AND "
                "((business_unit_id=%s) OR (business_unit_id IS NULL AND %s IS NULL)) "
                "AND status='closed' AND id<>%s "
            "ORDER BY closed_at DESC,id DESC LIMIT 1",
            (ex["scenario_id"], ex["org_id"], ex["business_unit_id"], ex["business_unit_id"], ex_id),
        ).fetchone()
        prior = dict(row) if row else None
    return {
        "exercise": {k: v for k, v in ex.items() if k not in ("report_json", "report_hash")},
        "readiness": rows("SELECT label,is_done,confirmed_at FROM bcm_exercise_readiness WHERE exercise_id=%s ORDER BY id"),
        "participants": rows("SELECT user_id,role,confirmed_at FROM bcm_exercise_participants WHERE exercise_id=%s ORDER BY id"),
        "events": rows("SELECT event_type,note,occurred_at,logged_by FROM bcm_exercise_events WHERE exercise_id=%s ORDER BY occurred_at,id"),
        "actions": rows(
            "SELECT a.task_id,a.evidence_id,a.verified_by,a.verified_at,t.title,t.status,t.due_date,t.assigned_to "
            "FROM bcm_exercise_actions a LEFT JOIN task_board t ON t.id=a.task_id "
            "WHERE a.exercise_id=%s ORDER BY a.id"
        ),
        "recurrence": {
            "prior_exercise": prior,
            "score_delta": ex["effectiveness_score"] - prior["effectiveness_score"]
            if prior and prior["effectiveness_score"] is not None and ex["effectiveness_score"] is not None else None,
        },
    }


def get_report(actor, ex_id):
    scope = bu_scope_ids(actor)
    db = get_db()
    try:
        ex = _visible(db, actor, ex_id, scope)
        if _state(ex) != "closed" or not ex.get("report_json"):
            raise ExerciseError(409, "After-action report is available when the exercise closes")
        digest = hashlib.sha256(ex["report_json"].encode("utf-8")).hexdigest()
        if digest != ex["report_hash"]:
            raise ExerciseError(409, "Stored report integrity check failed")
        return ex["report_json"]
    finally:
        db.close()