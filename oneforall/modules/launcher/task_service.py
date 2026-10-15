"""Task Board writes that must commit together."""

from core.best_effort import swallowed
from database import get_db, get_current_org, insert_returning_id


def validate_task_assignee(db, actor_id: int, assignee_id: int | None) -> None:
    """Keep task assignments and their notifications inside the actor's tenant."""
    if assignee_id is None:
        return
    actor = db.execute(
        "SELECT org_id,is_super_admin FROM users WHERE id=%s", (actor_id,)
    ).fetchone()
    assignee = db.execute(
        "SELECT org_id,is_active,deleted_at FROM users WHERE id=%s", (assignee_id,)
    ).fetchone()
    if (not actor or not assignee or not assignee["is_active"]
            or assignee["deleted_at"] is not None
            or (not actor["is_super_admin"]
                and (actor["org_id"] is None or assignee["org_id"] != actor["org_id"]))):
        raise ValueError("Assignee is not an active user in this organization")


def create_task_with_assignment_notification(
    *,
    title: str,
    description: str,
    module: str,
    entity_type: str,
    entity_id: int | None,
    assigned_to: int | None,
    priority: str,
    status: str,
    due_date: str | None,
    tags: str,
    created_by: int,
) -> int:
    """Create the task and assignment notification in one tenant transaction.

    The HTTP route owns input validation. This service owns the database
    connection and commits only after both writes succeed.
    """
    db = get_db()
    try:
        try:
            validate_task_assignee(db, created_by, assigned_to)
            task_id = insert_returning_id(
                db,
                "INSERT INTO task_board (title, description, module, entity_type, entity_id, "
                "assigned_to, priority, status, due_date, tags, created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (title, description, module, entity_type, entity_id,
                 assigned_to, priority, status, due_date, tags, created_by),
            )
            if task_id is None:
                raise RuntimeError("Task insert did not create a row")
            if assigned_to:
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, module) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (assigned_to, f"New Task: {title}", description[:100], "/tasks", "task"),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        # The task and its in-app notice are committed. The email is asked for after that and can never undo them.
        if assigned_to and assigned_to != created_by:
            _ask_assignment_email(db, task_id, assigned_to, due_date)
        return task_id
    finally:
        db.close()


def _ask_assignment_email(db, task_id: int, assigned_to: int, due_date) -> None:
    """Ask the email outbox to tell the assignee (template action.assigned: the kind of action, a reference and the due
    date, never the title). A mail problem is recorded and goes no further; the person has the in-app notice."""
    try:
        from core import email_outbox
        from core.email_templates import iso_or_none
        due = iso_or_none(due_date)
        email_outbox.enqueue_safely(
            db, "action.assigned", recipient_user_id=assigned_to, org_id=get_current_org(), route="/tasks",
            fields={"kind": "task", "reference": f"TK-{task_id}", "due": due},
            source=("platform", "task", task_id), purpose="assigned", threshold=f"{assigned_to}|{due or ''}")
        db.commit()
    except Exception:
        swallowed("task assignment email")
        try:
            db.rollback()
        except Exception:
            swallowed("task assignment email rollback")
