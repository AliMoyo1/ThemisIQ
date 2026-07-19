"""
One For All — Cross-module event handlers.

Handlers are registered via the @on decorator from core.events.
When a module emits an event, relevant handlers in other modules fire
to keep data synchronized and trigger cross-cutting workflows.

Import this module at app startup to ensure handlers are registered.
"""
import logging
from datetime import datetime, timedelta
from core.timeutils import utcnow

from core.events import (
    on, emit,
    ARIA_POLICY_PUBLISHED,
    GRID_AUDIT_COMPLETED,
    BCM_INCIDENT_DECLARED, BCM_PLAN_DEACTIVATED,
    SENTINEL_BREACH_CONFIRMED, SENTINEL_BREACH_RESOLVED,
    ERM_RISK_IDENTIFIED, ERM_RISK_ESCALATED, ERM_RISK_CLOSED, ERM_APPETITE_BREACHED,
    ORM_EVENT_ELEVATED, ORM_EVENT_LOGGED,
)
from core.links import create_cross_module_link
from core.notifications import notify_connectors
from database import get_db_background as get_db  # handlers must fail-fast, never queue behind user writes
from database import insert_returning_id
from config import settings

log = logging.getLogger("oneforall.handlers")


# ── helpers ───────────────────────────────────────────────────────────────────

def _notify(db, user_id, module, title, message, link=None):
    """Insert a notification row. Logs failures but never raises — handlers
    must not crash on notification delivery problems."""
    if not user_id:
        return
    try:
        db.execute(
            "INSERT INTO notifications (user_id, module, title, message, link) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, module, title, message, link),
        )
    except Exception as exc:
        log.warning(
            "Failed to insert notification (user=%s, module=%s, title=%r): %s",
            user_id, module, title, exc,
        )


def _notify_admins(db, module, title, message, link=None):
    """Send a notification to every admin/super_admin user. Logs failures."""
    try:
        rows = db.execute(
            "SELECT DISTINCT u.id FROM users u "
            "JOIN user_roles ur ON u.id = ur.user_id "
            "WHERE ur.role_key IN ('super_admin', 'admin') AND u.is_active = 1"
        ).fetchall()
        for r in rows:
            _notify(db, r[0], module, title, message, link)
    except Exception as exc:
        log.warning(
            "Failed to dispatch admin notification (module=%s, title=%r): %s",
            module, title, exc,
        )


def _insert_risk(db, title, description, source_module, entity_type,
                 entity_id, category, likelihood, impact, risk_level,
                 user_id):
    """Insert into risk_register.  Returns lastrowid or None."""
    try:
        cur = insert_returning_id(db,
            "INSERT INTO risk_register (title, description, source_module, "
            "source_entity_type, source_entity_id, category, likelihood, impact, "
            "risk_level, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (title, description, source_module, entity_type, entity_id,
             category, likelihood, impact, risk_level, "open", user_id),
        )
        return cur
    except Exception as exc:
        log.warning("_insert_risk failed: %s", exc)
        return None


def _insert_task(db, title, description, module, entity_type, entity_id,
                 priority, user_id):
    """Insert into task_board.  Returns lastrowid or None."""
    try:
        cur = insert_returning_id(db,
            "INSERT INTO task_board (title, description, module, entity_type, "
            "entity_id, priority, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (title, description, module, entity_type, entity_id,
             priority, "todo", user_id),
        )
        return cur
    except Exception as exc:
        log.warning("_insert_task failed: %s", exc)
        return None


def _insert_evidence(db, title, description, category, module, entity_type,
                     entity_id, user_id, tags=""):
    """
    Auto-create an evidence record in the Evidence Vault and link it to
    the originating entity via evidence_links.

    Returns the new evidence_items.id or None.
    """
    try:
        ev_id = insert_returning_id(db,
            "INSERT INTO evidence_items "
            "(title, description, category, tags, status, uploaded_by) "
            "VALUES (%s, %s, %s, %s, 'current', %s)",
            (title, description, category, tags, user_id),
        )

        # Link evidence → source entity
        db.execute(
            "INSERT INTO evidence_links "
            "(evidence_id, module, entity_type, entity_id, linked_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (ev_id, module, entity_type, entity_id, user_id),
        )
        log.info(
            "Auto-evidence #%d created: %s → %s/%s/%d",
            ev_id, title[:50], module, entity_type, entity_id,
        )
        return ev_id
    except Exception as exc:
        log.warning("_insert_evidence failed: %s", exc)
        return None


def _check_and_emit_appetite_breach(db, category, user_id=None):
    """
    Check if current open ERM risks in `category` exceed the appetite threshold.
    Emits ERM_APPETITE_BREACHED immediately if breached — used after any risk INSERT
    so appetite violations are detected in real-time, not only when the UI polls.
    """
    try:
        row = db.execute(
            "SELECT MAX(COALESCE(rrr, likelihood * impact)) AS max_score FROM erm_enterprise_risks "
            "WHERE category=%s AND status NOT IN ('closed','accepted')",
            (category,)
        ).fetchone()
        current_score = row["max_score"] if row and row["max_score"] else 0

        appetite = db.execute(
            "SELECT max_score FROM erm_risk_appetite WHERE category=%s", (category,)
        ).fetchone()
        if not appetite:
            return  # No appetite defined for this category — nothing to check

        max_score = appetite["max_score"]
        if current_score > max_score:
            emit(
                ERM_APPETITE_BREACHED,
                source_module="erm",
                entity_type="appetite",
                entity_id=0,
                payload={
                    "category": category,
                    "current_score": current_score,
                    "max_score": max_score,
                },
                user_id=user_id,
            )
            log.info(
                "Appetite breach detected in '%s': score %s > threshold %s",
                category, current_score, max_score,
            )
    except Exception as exc:
        log.warning("_check_and_emit_appetite_breach failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# FRAMEWORK EVENTS → MODULE SYNC
# ═══════════════════════════════════════════════════════════════════════════════

@on("framework.activated")
def auto_populate_controls_on_activate(event_type, source_module, entity_type,
                                       entity_id, payload, user_id, **kw):
    """When a framework is activated, auto-populate controls from seed data if empty."""
    from core.framework_service import list_controls, bulk_create_controls
    existing = list_controls(entity_id)
    if existing:
        return  # Already has controls
    name = payload.get("name", "")
    try:
        from seeds.framework_controls import FRAMEWORK_CONTROLS
        controls_data = FRAMEWORK_CONTROLS.get(name)
        if controls_data:
            count = bulk_create_controls(entity_id, controls_data, user_id)
            log.info("Auto-populated %d seed controls for '%s' on activation", count, name)
        else:
            log.info("No seed controls for '%s' - user can AI-generate via API", name)
    except Exception as e:
        log.warning("Failed to auto-populate controls for '%s': %s", name, e)


@on("framework.activated")
def sync_framework_to_aria(event_type, source_module, entity_type,
                           entity_id, payload, user_id, **kw):
    """When a framework is activated, ensure it exists in aria_frameworks."""
    db = get_db()
    try:
        name = payload.get("name", "")
        modules = payload.get("modules", "")
        if "aria" not in modules:
            return
        existing = db.execute(
            "SELECT id FROM aria_frameworks WHERE name = %s", (name,)
        ).fetchone()
        if not existing:
            fw = db.execute(
                "SELECT description, color FROM frameworks WHERE id = %s",
                (entity_id,)
            ).fetchone()
            if fw:
                db.execute(
                    "INSERT INTO aria_frameworks (name, description, color, relevant_modules, is_active) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (name, fw[0], fw[1], modules),
                )
                db.commit()
                log.info("Synced framework '%s' to aria_frameworks", name)
        else:
            db.execute(
                "UPDATE aria_frameworks SET is_active = 1 WHERE name = %s", (name,)
            )
            db.commit()
    finally:
        db.close()


@on("framework.activated")
def sync_framework_to_grid(event_type, source_module, entity_type,
                           entity_id, payload, user_id, **kw):
    """When a framework is activated, ensure it exists in grid_frameworks."""
    db = get_db()
    try:
        name = payload.get("name", "")
        modules = payload.get("modules", "")
        if "grid" not in modules:
            return
        existing = db.execute(
            "SELECT id FROM grid_frameworks WHERE name = %s", (name,)
        ).fetchone()
        if not existing:
            fw = db.execute(
                "SELECT description, color FROM frameworks WHERE id = %s",
                (entity_id,)
            ).fetchone()
            if fw:
                db.execute(
                    "INSERT INTO grid_frameworks (name, description, color, active) "
                    "VALUES (%s, %s, %s, 1)",
                    (name, fw[0], fw[1]),
                )
                db.commit()
                log.info("Synced framework '%s' to grid_frameworks", name)
        else:
            db.execute(
                "UPDATE grid_frameworks SET active = 1 WHERE name = %s", (name,)
            )
            db.commit()
    finally:
        db.close()


@on("framework.deactivated")
def deactivate_in_aria(event_type, source_module, entity_type,
                       entity_id, payload, user_id, **kw):
    """Deactivate framework in aria when deactivated globally."""
    db = get_db()
    try:
        name = payload.get("name", "")
        db.execute("UPDATE aria_frameworks SET is_active = 0 WHERE name = %s", (name,))
        db.commit()
    finally:
        db.close()


@on("framework.deactivated")
def deactivate_in_grid(event_type, source_module, entity_type,
                       entity_id, payload, user_id, **kw):
    """Deactivate framework in grid when deactivated globally."""
    db = get_db()
    try:
        name = payload.get("name", "")
        db.execute("UPDATE grid_frameworks SET active = 0 WHERE name = %s", (name,))
        db.commit()
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROL STATUS → RISK REGISTER SYNC
# ═══════════════════════════════════════════════════════════════════════════════

@on("control.status_changed")
def flag_risk_on_control_failure(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    """When a control status changes to Failed/Non-Compliant, create a risk entry."""
    status = payload.get("new_status", "")
    if status.lower() not in ("failed", "non-compliant", "non compliant"):
        return
    db = get_db()
    try:
        ctrl_name = payload.get("name", "Unknown Control")
        ctrl_ref = payload.get("ref", "")
        existing = db.execute(
            "SELECT id FROM risk_register WHERE title LIKE %s AND status != 'closed'",
            (f"%{ctrl_ref}%",)
        ).fetchone()
        if existing:
            return
        risk_id = _insert_risk(
            db,
            title=f"Control Failure: {ctrl_ref} - {ctrl_name}",
            description=(
                f"Control {ctrl_ref} ({ctrl_name}) has been marked as {status}. "
                f"This requires investigation and remediation."
            ),
            source_module="aria", entity_type="control", entity_id=entity_id,
            category="compliance", likelihood=4, impact=4,
            risk_level="high", user_id=user_id,
        )
        if risk_id:
            _notify_admins(
                db, "aria",
                f"Control Failure: {ctrl_ref}",
                f"{ctrl_name} marked {status} — risk #{risk_id} created.",
                "/platform/risk-register",
            )
        db.commit()
        log.info("Created risk entry for failed control %s", ctrl_ref)
    except Exception as e:
        log.warning("Could not create risk for control failure: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ARIA EVENTS → OTHER MODULES
# ═══════════════════════════════════════════════════════════════════════════════

@on("aria.policy.published")
def policy_published_handler(event_type, source_module, entity_type,
                             entity_id, payload, user_id, **kw):
    """
    When ARIA publishes a policy:
    - Create a task to review evidence alignment
    - Link the policy to its framework via cross_module_links
    - Notify admins
    """
    db = get_db()
    try:
        title = payload.get("title", f"Policy #{entity_id}")
        framework = payload.get("framework", "")
        control_ref = payload.get("control_ref", "")

        # Task: review evidence alignment for the new policy
        _insert_task(
            db,
            title=f"Review evidence for: {title}",
            description=(
                f"Policy '{title}' has been approved. "
                f"Verify that supporting evidence is linked and up to date."
            ),
            module="aria", entity_type="document", entity_id=entity_id,
            priority="high", user_id=user_id,
        )

        # Cross-module link: policy → evidence vault (available for linking)
        if control_ref:
            refs = [r.strip() for r in control_ref.split(",") if r.strip()]
            for ref in refs:
                ctrl_row = db.execute(
                    "SELECT id FROM grid_controls WHERE control_id = %s LIMIT 1",
                    (ref,)
                ).fetchone()
                if ctrl_row:
                    create_cross_module_link(
                        "aria", "document", entity_id,
                        "grid", "control", ctrl_row[0],
                        relationship="implements", user_id=user_id, db=db,
                    )

        # ── Sync full policy document to Evidence Vault ─────────────
        doc_row = db.execute(
            "SELECT doc_id, title, doc_type, version, "
            "       file_path, branded_file_path, file_name "
            "FROM aria_documents WHERE id=%s",
            (entity_id,),
        ).fetchone()

        try:
            import hashlib as _hashlib
            import shutil as _shutil
            from pathlib import Path as _Path
            import uuid as _uuid

            aria_dir = _Path(os.environ.get("ARIA_UPLOAD_DIR", "data/aria_uploads"))
            ev_dir = _Path(os.environ.get("EVIDENCE_DIR", "data/evidence"))
            ev_dir.mkdir(parents=True, exist_ok=True)

            src_rel = None
            if doc_row:
                src_rel = doc_row["branded_file_path"] or doc_row["file_path"]

            ev_stored = ""
            ev_filename = ""
            ev_size = 0
            ev_hash = ""
            ev_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            if src_rel:
                src_abs = (aria_dir / src_rel).resolve()
                if src_abs.exists() and str(src_abs).startswith(str(aria_dir.resolve())):
                    ext = src_abs.suffix or ".docx"
                    ev_stored = f"{_uuid.uuid4().hex}{ext}"
                    _shutil.copy2(str(src_abs), str(ev_dir / ev_stored))
                    ev_size = (ev_dir / ev_stored).stat().st_size
                    h = _hashlib.sha256()
                    with open(ev_dir / ev_stored, "rb") as _f:
                        while True:
                            chunk = _f.read(65536)
                            if not chunk:
                                break
                            h.update(chunk)
                    ev_hash = h.hexdigest()
                    ev_filename = (
                        doc_row["file_name"]
                        or f"{doc_row['doc_id'] or 'policy'}_{doc_row['version'] or '1.0'}.docx"
                    )

            tag = f"aria_doc_id={entity_id}"
            existing_vault = db.execute(
                "SELECT id FROM evidence_items WHERE tags LIKE %s AND status != 'archived'",
                (f"%{tag}%",),
            ).fetchone()

            if existing_vault:
                vault_id = existing_vault["id"]
                db.execute(
                    "UPDATE evidence_items SET title=%s, file_path=%s, file_name=%s, "
                    "file_size=%s, file_hash=%s, tags=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=%s",
                    (title, ev_stored, ev_filename, ev_size, ev_hash,
                     f"aria,policy,approved,{framework},{control_ref},{tag}",
                     vault_id),
                )
            else:
                vault_id = insert_returning_id(db,
                    "INSERT INTO evidence_items "
                    "(title, description, file_path, file_name, file_size, "
                    " file_hash, mime_type, category, tags, status, uploaded_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        title,
                        f"ARIA policy document (framework: {framework}, "
                        f"control: {control_ref}, type: {doc_row['doc_type'] if doc_row else 'Policy'}, "
                        f"version: {doc_row['version'] if doc_row else '1.0'}). "
                        f"Published on {datetime.now():%Y-%m-%d %H:%M}.",
                        ev_stored,
                        ev_filename,
                        ev_size,
                        ev_hash,
                        ev_mime if ev_stored else "",
                        "policy",
                        f"aria,policy,approved,{framework},{control_ref},{tag}",
                        "current",
                        user_id,
                    ),
                )
                db.execute(
                    "INSERT INTO evidence_links "
                    "(evidence_id, module, entity_type, entity_id, linked_by) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (vault_id, "aria", "document", entity_id, user_id),
                )
            if framework:
                fw_row = db.execute(
                    "SELECT id FROM aria_frameworks WHERE name=%s", (framework,)
                ).fetchone()
                if fw_row:
                    db.execute(
                        "INSERT INTO evidence_links "
                        "(evidence_id, module, entity_type, entity_id, linked_by) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (vault_id, "aria", "framework", fw_row[0], user_id),
                    )

            log.info("Synced ARIA policy '%s' → vault #%d (%s bytes)", title, vault_id, ev_size)
        except Exception as ev_exc:
            log.warning("Failed to sync ARIA policy to vault: %s", ev_exc)

        _notify_admins(
            db, "aria",
            f"Policy Published: {title}",
            f"ARIA policy '{title}' approved — added to Evidence Vault.",
            "/aria/#documents",
        )
        db.commit()
        log.info("Handled policy published for '%s' (id=%d)", title, entity_id)
    except Exception as e:
        log.warning("policy_published_handler error: %s", e)
    finally:
        db.close()


@on("aria.policy.updated")
def policy_updated_handler(event_type, source_module, entity_type,
                           entity_id, payload, user_id, **kw):
    """When an ARIA policy is updated, create a task if it reverted from Approved."""
    db = get_db()
    try:
        title = payload.get("title", f"Policy #{entity_id}")
        old_status = payload.get("old_status", "")
        new_status = payload.get("new_status", "")

        if old_status.lower() == "approved" and new_status.lower() != "approved":
            _insert_task(
                db,
                title=f"Re-review policy: {title}",
                description=(
                    f"Policy '{title}' status changed from '{old_status}' to "
                    f"'{new_status}'. Re-review and re-approve required."
                ),
                module="aria", entity_type="document", entity_id=entity_id,
                priority="high", user_id=user_id,
            )
            _notify_admins(
                db, "aria",
                f"Policy Reverted: {title}",
                f"Status changed from {old_status} to {new_status}.",
                "/aria/#documents",
            )

        db.commit()
        log.info("Handled policy update for '%s' (id=%d)", title, entity_id)
    except Exception as e:
        log.warning("policy_updated_handler error: %s", e)
    finally:
        db.close()


@on("aria.risk.created")
def aria_risk_created_handler(event_type, source_module, entity_type,
                              entity_id, payload, user_id, **kw):
    """
    When ARIA creates a risk:
    - Mirror it into the cross-module risk register
    - Link the ARIA risk to the platform risk entry
    """
    db = get_db()
    try:
        desc = payload.get("description", "")
        category = payload.get("category", "compliance")
        likelihood = int(payload.get("likelihood", 3))
        impact = int(payload.get("impact", 3))
        score = likelihood * impact
        risk_level = (
            "critical" if score >= 20 else
            "high" if score >= 12 else
            "medium" if score >= 6 else "low"
        )

        risk_id = _insert_risk(
            db,
            title=f"ARIA Risk #{entity_id}: {desc[:80]}",
            description=desc,
            source_module="aria", entity_type="risk", entity_id=entity_id,
            category=category, likelihood=likelihood, impact=impact,
            risk_level=risk_level, user_id=user_id,
        )
        if risk_id:
            create_cross_module_link(
                "aria", "risk", entity_id,
                "platform", "risk_register", risk_id,
                relationship="derived_from", user_id=user_id, db=db,
        )

        # Auto-evidence: risk identification record
        _insert_evidence(
            db,
            title=f"Risk Identified: ARIA #{entity_id}",
            description=(
                f"Risk identified in ARIA module (level: {risk_level}). "
                f"Category: {category}. L={likelihood} × I={impact} = {score}. "
                f"Mirrored to platform risk register."
            ),
            category="risk_assessment",
            module="aria", entity_type="risk", entity_id=entity_id,
            user_id=user_id, tags="auto,risk,assessment,aria",
        )

        db.commit()
        log.info("Mirrored ARIA risk %d to platform risk register", entity_id)
    except Exception as e:
        log.warning("aria_risk_created_handler error: %s", e)
    finally:
        db.close()


@on("aria.risk.escalated")
def aria_risk_escalated_handler(event_type, source_module, entity_type,
                                entity_id, payload, user_id, **kw):
    """
    When ARIA escalates a risk:
    - Create a BCM risk entry for continuity assessment
    - Create a cross-module link ARIA risk → BCM risk
    - Create a high-priority task
    - Notify admins
    """
    db = get_db()
    try:
        desc = payload.get("description", f"Escalated ARIA risk #{entity_id}")
        likelihood = int(payload.get("likelihood", 4))
        impact = int(payload.get("impact", 4))

        # BCM risk entry
        risk_id = _insert_risk(
            db,
            title=f"Escalated from ARIA: Risk #{entity_id}",
            description=(
                f"Risk escalated from ARIA for business continuity assessment. "
                f"Original: {desc}"
            ),
            source_module="aria", entity_type="risk", entity_id=entity_id,
            category="business_continuity", likelihood=likelihood, impact=impact,
            risk_level="high", user_id=user_id,
        )

        if risk_id:
            create_cross_module_link(
                "aria", "risk", entity_id,
                "bcm", "risk", risk_id,
                relationship="escalated_to", user_id=user_id, db=db,
        )

        _insert_task(
            db,
            title=f"BCM Assessment: Escalated ARIA Risk #{entity_id}",
            description="Evaluate business continuity impact of escalated risk.",
            module="bcm", entity_type="risk", entity_id=entity_id,
            priority="critical", user_id=user_id,
        )

        # Auto-evidence: risk escalation record
        _insert_evidence(
            db,
            title=f"Risk Escalation: ARIA #{entity_id} → BCM",
            description=(
                f"ARIA risk #{entity_id} escalated to BCM for business continuity "
                f"assessment on {datetime.now():%Y-%m-%d %H:%M}. "
                f"Original: {desc[:150]}"
            ),
            category="risk_escalation",
            module="aria", entity_type="risk", entity_id=entity_id,
            user_id=user_id, tags="auto,risk,escalation,aria,bcm",
        )

        _notify_admins(
            db, "bcm",
            "Risk Escalated from ARIA",
            f"ARIA risk #{entity_id} escalated for continuity assessment.",
            "/platform/risk-register",
        )
        db.commit()
        log.info("Escalated ARIA risk %d to BCM", entity_id)
    except Exception as e:
        log.warning("aria_risk_escalated_handler error: %s", e)
    finally:
        db.close()


@on("aria.control.updated")
def aria_control_updated_handler(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    """
    When an ARIA control status changes:
    - Link to corresponding GRID control if it exists
    - If status is now non-compliant, create a task to investigate
    """
    db = get_db()
    try:
        ref = payload.get("ref", "")
        name = payload.get("name", "")
        new_status = payload.get("new_status", "")
        old_status = payload.get("old_status", "")

        # Cross-link to GRID control with same ref
        if ref:
            grid_ctrl = db.execute(
                "SELECT id FROM grid_controls WHERE control_id = %s LIMIT 1",
                (ref,)
            ).fetchone()
            if grid_ctrl:
                create_cross_module_link(
                    "aria", "control", entity_id,
                    "grid", "control", grid_ctrl[0],
                    relationship="related", user_id=user_id, db=db,
        )

        # If moved to a failing state, create investigation task
        if new_status.lower() in ("failed", "non-compliant", "non compliant"):
            _insert_task(
                db,
                title=f"Investigate control failure: {ref} - {name}",
                description=(
                    f"Control {ref} ({name}) changed from '{old_status}' to "
                    f"'{new_status}'. Investigate root cause and plan remediation."
                ),
                module="aria", entity_type="control", entity_id=entity_id,
                priority="high", user_id=user_id,
            )

        # Auto-evidence: control assessment record
        _insert_evidence(
            db,
            title=f"Control Assessment: {ref} — {new_status}",
            description=(
                f"Control {ref} ({name}) status changed from '{old_status}' to "
                f"'{new_status}' on {datetime.now():%Y-%m-%d %H:%M}."
            ),
            category="control_assessment",
            module="aria", entity_type="control", entity_id=entity_id,
            user_id=user_id, tags="auto,control,assessment,aria",
        )

        db.commit()
        log.info("Handled ARIA control update: %s (%s → %s)", ref, old_status, new_status)
    except Exception as e:
        log.warning("aria_control_updated_handler error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# GRID EVENTS → OTHER MODULES
# ═══════════════════════════════════════════════════════════════════════════════

@on("grid.audit.completed")
def audit_completed_handler(event_type, source_module, entity_type,
                            entity_id, payload, user_id, **kw):
    """
    When GRID completes an audit:
    - Create a task to compile the audit report
    - Link audit to its framework in cross_module_links
    - Notify admins
    """
    db = get_db()
    try:
        name = payload.get("name", f"Audit #{entity_id}")
        framework_id = payload.get("framework_id")

        _insert_task(
            db,
            title=f"Compile audit report: {name}",
            description=(
                f"Audit '{name}' has been completed. "
                f"Compile findings, generate report, and schedule follow-up."
            ),
            module="grid", entity_type="audit", entity_id=entity_id,
            priority="high", user_id=user_id,
        )

        # Link to framework if known
        if framework_id:
            create_cross_module_link(
                "grid", "audit", entity_id,
                "platform", "framework", framework_id,
                relationship="audits", user_id=user_id, db=db,
        )

        # Auto-evidence: audit completion record
        _insert_evidence(
            db,
            title=f"Audit Completed: {name}",
            description=(
                f"GRID audit '{name}' (id={entity_id}) completed on "
                f"{datetime.now():%Y-%m-%d %H:%M}. Report compilation task created."
            ),
            category="audit_completion",
            module="grid", entity_type="audit", entity_id=entity_id,
            user_id=user_id, tags="auto,audit,completion,grid",
        )

        _notify_admins(
            db, "grid",
            f"Audit Completed: {name}",
            "Review findings and compile report.",
            "/grid/#audits",
        )
        db.commit()
        log.info("Handled audit completion: '%s' (id=%d)", name, entity_id)
    except Exception as e:
        log.warning("audit_completed_handler error: %s", e)
    finally:
        db.close()


@on("grid.finding.created")
def grid_finding_created_handler(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    """
    When GRID creates a finding:
    - Link finding to its parent audit
    - If severity is major/critical, create a task
    """
    db = get_db()
    try:
        title = payload.get("title", f"Finding #{entity_id}")
        severity = (payload.get("severity") or "minor").lower()
        audit_id = payload.get("audit_id")

        if audit_id:
            create_cross_module_link(
                "grid", "finding", entity_id,
                "grid", "audit", audit_id,
                relationship="derived_from", user_id=user_id, db=db,
        )

        if severity in ("major", "critical"):
            _insert_task(
                db,
                title=f"Address finding: {title}",
                description=f"A {severity} finding was raised. Investigate and remediate.",
                module="grid", entity_type="finding", entity_id=entity_id,
                priority="critical" if severity == "critical" else "high",
                user_id=user_id,
            )

        # Auto-evidence: audit finding record
        _insert_evidence(
            db,
            title=f"Audit Finding: {title} ({severity})",
            description=(
                f"Finding '{title}' (severity: {severity}) raised in GRID audit "
                f"(audit_id={audit_id}) on {datetime.now():%Y-%m-%d %H:%M}."
            ),
            category="audit_finding",
            module="grid", entity_type="finding", entity_id=entity_id,
            user_id=user_id, tags=f"auto,finding,{severity},grid",
        )

        db.commit()
        log.info("Handled GRID finding %d (severity=%s)", entity_id, severity)
    except Exception as e:
        log.warning("grid_finding_created_handler error: %s", e)
    finally:
        db.close()


@on("grid.non_conformance.raised")
def nc_to_risk_register(event_type, source_module, entity_type,
                        entity_id, payload, user_id, **kw):
    """When GRID raises a major/critical non-conformance, flag in risk register."""
    severity = payload.get("severity", "minor")
    if severity.lower() not in ("major", "critical"):
        return
    db = get_db()
    try:
        title = payload.get("title", f"Non-Conformance #{entity_id}")
        audit_id = payload.get("audit_id")

        risk_id = _insert_risk(
            db,
            title=f"NC Escalation: {title}",
            description=f"A {severity} non-conformance was raised in GRID audit. Requires attention.",
            source_module="grid", entity_type="non_conformance", entity_id=entity_id,
            category="audit",
            likelihood=4 if severity == "critical" else 3,
            impact=4 if severity == "critical" else 3,
            risk_level=severity, user_id=user_id,
        )

        # Link NC → parent audit
        if audit_id and risk_id:
            create_cross_module_link(
                "grid", "non_conformance", entity_id,
                "grid", "audit", audit_id,
                relationship="derived_from", user_id=user_id, db=db,
        )

        # Auto-evidence: non-conformance documentation
        _insert_evidence(
            db,
            title=f"Non-Conformance: {title}",
            description=(
                f"A {severity} non-conformance '{title}' was raised in GRID "
                f"(audit_id={audit_id}) on {datetime.now():%Y-%m-%d %H:%M}. "
                f"Escalated to risk register."
            ),
            category="non_conformance",
            module="grid", entity_type="non_conformance", entity_id=entity_id,
            user_id=user_id, tags=f"auto,nc,{severity},grid",
        )

        _notify_admins(
            db, "grid",
            f"Non-Conformance: {title}",
            f"A {severity} NC was escalated to the risk register.",
            "/platform/risk-register",
        )
        db.commit()
    except Exception as e:
        log.warning("Could not create risk from NC: %s", e)
    finally:
        db.close()


@on("grid.policy.requested")
def grid_policy_request_handler(event_type, source_module, entity_type,
                                entity_id, payload, user_id, **kw):
    """
    When GRID requests a policy:
    - Create a task in ARIA for the compliance team to draft/approve it
    - Notify admins about the policy gap
    """
    db = get_db()
    try:
        title = payload.get("title", "Policy needed")
        framework = payload.get("framework_name", "")
        control_ref = payload.get("control_ref", "")
        audit_name = payload.get("audit_name", "")
        description = payload.get("description", "")

        _insert_task(
            db,
            title=f"Policy Request: {title}",
            description=(
                f"GRID audit '{audit_name}' requires a policy document: '{title}'. "
                f"Framework: {framework}, Control: {control_ref}. "
                f"{description} "
                f"Please draft and approve this policy in ARIA."
            ),
            module="aria", entity_type="policy_request", entity_id=entity_id,
            priority="high", user_id=user_id,
        )

        _notify_admins(
            db, "aria",
            f"Policy Requested: {title}",
            f"GRID audit '{audit_name}' needs policy '{title}' "
            f"(framework: {framework}, control: {control_ref}). "
            f"Draft and approve in ARIA.",
            "/aria/#documents",
        )

        db.commit()
        log.info("Policy request from GRID: '%s' (framework=%s, ref=%s)",
                 title, framework, control_ref)
    except Exception as e:
        log.warning("grid_policy_request_handler error: %s", e)
    finally:
        db.close()


@on("aria.policy.published")
def auto_resolve_grid_policy_requests(event_type, source_module, entity_type,
                                      entity_id, payload, user_id, **kw):
    """
    When ARIA publishes a policy, check if it fulfils any pending
    GRID policy requests (matching by framework + control_ref).
    If so, mark them fulfilled and notify the requestor.
    """
    db = get_db()
    try:
        framework = payload.get("framework", "")
        control_ref = payload.get("control_ref", "")
        title = payload.get("title", "")

        if not framework:
            return

        # Find pending requests that match this policy
        q = (
            "SELECT pr.id, pr.requested_by, pr.audit_id, pr.title AS req_title, "
            "a.name AS audit_name "
            "FROM grid_policy_requests pr "
            "LEFT JOIN grid_audits a ON pr.audit_id=a.id "
            "WHERE pr.status='pending' AND pr.framework_name=%s"
        )
        params = [framework]
        if control_ref:
            refs = [r.strip() for r in control_ref.split(",") if r.strip()]
            placeholders = " OR ".join(["pr.control_ref=%s"] * len(refs))
            q += " AND (pr.control_ref IS NULL OR pr.control_ref='' OR " + placeholders + ")"
            params.extend(refs)

        matches = db.execute(q, params).fetchall()

        for m in matches:
            db.execute(
                "UPDATE grid_policy_requests "
                "SET status='fulfilled', aria_document_id=%s, resolved_at=CURRENT_TIMESTAMP "
                "WHERE id=%s",
                (entity_id, m["id"]),
            )
            # Notify the requestor
            _notify(
                db, m["requested_by"], "grid",
                f"Policy Available: {title}",
                f"The policy '{title}' you requested for audit "
                f"'{m['audit_name'] or ''}' has been published in ARIA. "
                f"You can now attach it as evidence.",
                "/grid/#evidence",
            )

        if matches:
            db.commit()
            log.info("Auto-resolved %d GRID policy request(s) for '%s'",
                     len(matches), title)
    except Exception as e:
        log.warning("auto_resolve_grid_policy_requests error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BCM EVENTS → OTHER MODULES
# ═══════════════════════════════════════════════════════════════════════════════

@on("bcm.incident.declared")
def incident_creates_task(event_type, source_module, entity_type,
                          entity_id, payload, user_id, **kw):
    """When BCM declares an incident, create a high-priority task + risk + notification."""
    db = get_db()
    try:
        title = payload.get("title", f"Incident #{entity_id}")
        severity = (payload.get("severity") or "high").lower()

        task_id = _insert_task(
            db,
            title=f"INCIDENT: {title}",
            description="Business continuity incident declared. Immediate response required.",
            module="bcm", entity_type="incident", entity_id=entity_id,
            priority="critical", user_id=user_id,
        )

        # Also create a risk entry for tracking
        risk_id = _insert_risk(
            db,
            title=f"BCM Incident: {title}",
            description=f"Active business continuity incident. Severity: {severity}.",
            source_module="bcm", entity_type="incident", entity_id=entity_id,
            category="business_continuity",
            likelihood=5 if severity == "critical" else 4,
            impact=5 if severity == "critical" else 4,
            risk_level=severity, user_id=user_id,
        )

        if risk_id:
            create_cross_module_link(
                "bcm", "incident", entity_id,
                "platform", "risk_register", risk_id,
                relationship="triggers", user_id=user_id, db=db,
        )

        # Auto-evidence: incident declaration record
        _insert_evidence(
            db,
            title=f"Incident Declared: {title}",
            description=(
                f"Business continuity incident '{title}' declared on "
                f"{datetime.now():%Y-%m-%d %H:%M}. Severity: {severity}. "
                f"Response task and risk entry created."
            ),
            category="incident_record",
            module="bcm", entity_type="incident", entity_id=entity_id,
            user_id=user_id, tags=f"auto,incident,declared,{severity},bcm",
        )

        _notify_admins(
            db, "bcm",
            f"INCIDENT DECLARED: {title}",
            f"Severity: {severity}. Immediate response required.",
            "/bcm/#incidents",
        )
        db.commit()
    except Exception as e:
        log.warning("Could not create task from BCM incident: %s", e)
    finally:
        db.close()


@on("bcm.incident.declared")
def bcm_incident_impact_analysis(event_type, source_module, entity_type,
                                  entity_id, payload, user_id, **kw):
    """
    BCM-18: When an incident is declared, automatically run dependency impact
    analysis against the affected_systems field.

    - Tokenises affected_systems text
    - Finds matching dependency nodes by name similarity
    - Runs BFS impact chain for each matched node
    - Creates a notification with the impact summary
    - Creates a task listing all potentially impacted dependencies
    """
    db = get_db()
    try:
        title = payload.get("title", f"Incident #{entity_id}")
        affected = (payload.get("affected_systems") or "").strip()
        if not affected:
            return  # Nothing to analyse

        # Tokenise the affected_systems description into search terms
        stop = {"the", "a", "an", "is", "are", "was", "were", "and", "or",
                "of", "in", "on", "to", "for", "with", "at", "by", "from"}
        terms = [t.strip(".,;:()") for t in affected.split()
                 if len(t.strip(".,;:()")) > 2 and t.lower() not in stop]

        if not terms:
            return

        # Find dependency nodes whose names contain any of the terms
        matched_node_ids = set()
        for term in terms[:8]:  # cap to avoid over-broad matching
            rows = db.execute(
                "SELECT id, name FROM bcm_dependency_nodes WHERE name LIKE %s OR description LIKE %s",
                (f"%{term}%", f"%{term}%"),
            ).fetchall()
            for r in rows:
                matched_node_ids.add(r[0])

        if not matched_node_ids:
            # No dependency nodes matched — still create a notification
            _notify_admins(
                db, "bcm",
                f"Impact Analysis: {title}",
                "No matching dependency nodes found for affected systems. "
                "Review the dependency map to ensure it is up to date.",
                "/bcm/dependencies",
            )
            db.commit()
            return

        # For each matched node, run the impact chain (BFS, depth 5)
        impacted = {}  # node_id → node dict
        visited_chains = []

        def _bfs(start_id, depth=5):
            visited = set()
            queue = [start_id]
            chain = []
            for _ in range(depth):
                if not queue:
                    break
                next_q = []
                for nid in queue:
                    if nid in visited:
                        continue
                    visited.add(nid)
                    rows = db.execute(
                        "SELECT target_id FROM bcm_dependency_edges WHERE source_id=%s", (nid,)
                    ).fetchall()
                    for r in rows:
                        tid = r[0]
                        if tid not in visited:
                            node = db.execute(
                                "SELECT id, name, node_type, criticality FROM bcm_dependency_nodes WHERE id=%s",
                                (tid,)
                            ).fetchone()
                            if node:
                                chain.append(dict(node))
                                impacted[tid] = dict(node)
                                next_q.append(tid)
                queue = next_q
            return chain

        for nid in matched_node_ids:
            root_node = db.execute(
                "SELECT id, name, node_type, criticality FROM bcm_dependency_nodes WHERE id=%s", (nid,)
            ).fetchone()
            if root_node:
                impacted[nid] = dict(root_node)
                chain = _bfs(nid)
                if chain:
                    visited_chains.append({
                        "root": dict(root_node),
                        "downstream": chain,
                    })

        # Build impact summary text
        impacted_names = [n["name"] for n in impacted.values()]
        direct_count = len(matched_node_ids)
        total_count = len(impacted)

        summary_lines = [
            f"Incident '{title}' — auto-dependency impact analysis:",
            f"• {direct_count} directly matched node(s): {', '.join(n for nid, n_row in zip(matched_node_ids, [impacted.get(i, {}) for i in matched_node_ids]) for n in [n_row.get('name', str(nid))])}",
            f"• {total_count} total potentially impacted nodes (including downstream).",
        ]
        if visited_chains:
            summary_lines.append("Cascade chains:")
            for ch in visited_chains[:4]:  # cap output
                downstream = ", ".join(n["name"] for n in ch["downstream"][:5])
                summary_lines.append(f"  {ch['root']['name']} → {downstream or 'no downstream'}")

        summary = "\n".join(summary_lines)

        # Create a critical task with the impact report
        _insert_task(
            db,
            title=f"Dependency Impact: {title}",
            description=summary,
            module="bcm", entity_type="incident", entity_id=entity_id,
            priority="critical", user_id=user_id,
        )

        # Notify admins
        short_msg = (
            f"{total_count} potentially impacted dependency node(s) identified "
            f"for incident '{title}'. Review the impact analysis task."
        )
        _notify_admins(db, "bcm", f"Impact Analysis: {title}", short_msg, "/bcm/dependencies")

        db.commit()
        log.info(
            "BCM-18: Impact analysis for incident %d — %d direct, %d total impacted nodes",
            entity_id, direct_count, total_count,
        )
    except Exception as e:
        log.warning("bcm_incident_impact_analysis error: %s", e)
    finally:
        db.close()


@on("bcm.incident.resolved")
def incident_resolved_handler(event_type, source_module, entity_type,
                              entity_id, payload, user_id, **kw):
    """
    When BCM resolves an incident:
    - Close related tasks
    - Create a post-incident review task
    - Notify admins
    """
    db = get_db()
    try:
        title = payload.get("title", f"Incident #{entity_id}")

        # Close open tasks linked to this incident
        db.execute(
            "UPDATE task_board SET status = 'done' "
            "WHERE module = 'bcm' AND entity_type = 'incident' "
            "AND entity_id = %s AND status != 'done'",
            (entity_id,),
        )

        # Create post-incident review task
        _insert_task(
            db,
            title=f"Post-incident review: {title}",
            description=(
                "Incident resolved. Conduct post-incident review within 5 business "
                "days: root cause analysis, lessons learned, update BCM plans."
            ),
            module="bcm", entity_type="incident", entity_id=entity_id,
            priority="high", user_id=user_id,
        )

        # Auto-evidence: incident resolution record
        _insert_evidence(
            db,
            title=f"Incident Resolved: {title}",
            description=(
                f"Incident '{title}' (id={entity_id}) resolved on "
                f"{datetime.now():%Y-%m-%d %H:%M}. Related tasks closed. "
                f"Post-incident review task created."
            ),
            category="incident_record",
            module="bcm", entity_type="incident", entity_id=entity_id,
            user_id=user_id, tags="auto,incident,resolved,bcm",
        )

        _notify_admins(
            db, "bcm",
            f"Incident Resolved: {title}",
            "Post-incident review task created.",
            "/bcm/#incidents",
        )

        # ── XM-CLOSE-3: Close ORM events directly linked to this incident ──
        orm_links = db.execute(
            "SELECT target_id FROM cross_module_links "
            "WHERE source_module='bcm' AND source_type='incident' "
            "AND source_id=%s AND target_module='orm' AND target_type='event'",
            (entity_id,),
        ).fetchall()
        for link in orm_links:
            db.execute(
                "UPDATE orm_events SET status='resolved', resolved_at=CURRENT_TIMESTAMP, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=%s AND status NOT IN ('resolved','closed')",
                (link["target_id"],),
            )
            log.info("XM-CLOSE-3: BCM incident %d resolved -> closed ORM event #%d",
                     entity_id, link["target_id"])

        db.commit()
        log.info("Handled incident resolution: '%s' (id=%d)", title, entity_id)
    except Exception as e:
        log.warning("incident_resolved_handler error: %s", e)
    finally:
        db.close()


@on("bcm.risk.escalated")
def bcm_risk_escalated_handler(event_type, source_module, entity_type,
                               entity_id, payload, user_id, **kw):
    """
    When BCM escalates a risk:
    - Mirror to the platform risk register
    - Link BCM risk → platform risk
    - Create investigation task
    """
    db = get_db()
    try:
        title = payload.get("title", f"BCM Risk #{entity_id}")
        desc = payload.get("description", "")
        severity = (payload.get("severity") or "high").lower()

        lh = 5 if severity == "critical" else 4
        imp = 5 if severity == "critical" else 4

        risk_id = _insert_risk(
            db,
            title=f"BCM Escalation: {title}",
            description=desc or f"High-severity BCM risk escalated for platform tracking.",
            source_module="bcm", entity_type="risk", entity_id=entity_id,
            category="business_continuity", likelihood=lh, impact=imp,
            risk_level=severity, user_id=user_id,
        )

        if risk_id:
            create_cross_module_link(
                "bcm", "risk", entity_id,
                "platform", "risk_register", risk_id,
                relationship="escalated_to", user_id=user_id, db=db,
        )

        _insert_task(
            db,
            title=f"Assess BCM risk: {title}",
            description="Escalated BCM risk requires cross-functional assessment.",
            module="bcm", entity_type="risk", entity_id=entity_id,
            priority="critical" if severity == "critical" else "high",
            user_id=user_id,
        )

        _notify_admins(
            db, "bcm",
            f"BCM Risk Escalated: {title}",
            f"Severity: {severity}. Review in risk register.",
            "/platform/risk-register",
        )

        # GAP-6: Also escalate high/critical BCM risks to ERM enterprise risk register
        erm_id = None
        if severity in ("high", "critical"):
            erm_id = _insert_erm_risk(
                db,
                title=f"BCM Risk: {title}",
                description=desc or (
                    f"High-severity BCM risk auto-escalated to ERM. "
                    f"Severity: {severity}. Review business continuity implications."
                ),
                category="operational",
                likelihood=lh, impact=imp,
                source_module="bcm", source_risk_id=entity_id,
                board_visibility=1 if severity == "critical" else 0,
                user_id=user_id,
            )
            if erm_id:
                create_cross_module_link(
                    "bcm", "risk", entity_id,
                    "erm", "enterprise_risk", erm_id,
                    relationship="escalated_to", user_id=user_id, db=db,
                )
                log.info("GAP-6: BCM risk %d → ERM enterprise risk #%d", entity_id, erm_id)

        db.commit()
        log.info("Escalated BCM risk %d to platform", entity_id)
        # Emit after commit so nested handlers don't hit a write lock
        if severity in ("high", "critical") and erm_id:
            emit(ERM_RISK_IDENTIFIED,
                 source_module="bcm", entity_type="risk", entity_id=entity_id,
                 payload={"title": title, "severity": severity, "erm_risk_id": erm_id},
                 user_id=user_id)
    except Exception as e:
        log.warning("bcm_risk_escalated_handler error: %s", e)
    finally:
        db.close()


@on("bcm.plan.approved")
def bcm_plan_approved_handler(event_type, source_module, entity_type,
                              entity_id, payload, user_id, **kw):
    """
    When a BCM plan is approved:
    - Create a task to schedule the next exercise/test
    - Link plan to related incidents if any
    - Notify admins
    """
    db = get_db()
    try:
        title = payload.get("title", f"Plan #{entity_id}")
        plan_type = payload.get("plan_type", "continuity")

        _insert_task(
            db,
            title=f"Schedule exercise for: {title}",
            description=(
                f"BCM plan '{title}' ({plan_type}) approved. "
                f"Schedule a tabletop or functional exercise within 90 days."
            ),
            module="bcm", entity_type="plan", entity_id=entity_id,
            priority="medium", user_id=user_id,
        )

        # Auto-evidence: plan approval record
        _insert_evidence(
            db,
            title=f"Plan Approved: {title}",
            description=(
                f"BCM {plan_type} plan '{title}' (id={entity_id}) approved on "
                f"{datetime.now():%Y-%m-%d %H:%M}. Exercise scheduling task created."
            ),
            category="plan_approval",
            module="bcm", entity_type="plan", entity_id=entity_id,
            user_id=user_id, tags=f"auto,plan,approval,{plan_type},bcm",
        )

        _notify_admins(
            db, "bcm",
            f"Plan Approved: {title}",
            f"BCM plan approved — exercise scheduling task created.",
            "/bcm/#plans",
        )
        db.commit()
        log.info("Handled BCM plan approval: '%s' (id=%d)", title, entity_id)
    except Exception as e:
        log.warning("bcm_plan_approved_handler error: %s", e)
    finally:
        db.close()


# ── XM-2: BCM plan activation → ARIA control review ──────────────────────────
@on("bcm.plan.activated")
def plan_activation_triggers_control_review(event_type, source_module, entity_type,
                                             entity_id, payload, user_id, **kw):
    """
    XM-2: When a BCM plan is activated (real incident in progress), prompt the
    compliance team in ARIA to verify that related controls are still operational.
    """
    db = get_db()
    try:
        name      = payload.get("name", f"Plan #{entity_id}")
        plan_type = payload.get("plan_type", "continuity")

        _insert_task(
            db,
            title=f"CONTROL REVIEW: Verify controls for activated plan — {name}",
            description=(
                f"BCM {plan_type} plan '{name}' (id={entity_id}) has been activated. "
                f"Verify all related ARIA controls are still compliant and evidence is current. "
                f"An activated plan may indicate a control failure or changed risk posture."
            ),
            module="aria", entity_type="bcm_plan", entity_id=entity_id,
            priority="high", user_id=user_id,
        )

        _notify_admins(
            db, "aria",
            f"Control review required: BCM plan activated — {name}",
            f"Plan type: {plan_type}. Check ARIA task board for control verification task.",
            "/aria/#controls",
        )
        db.commit()
        log.info("XM-2: BCM plan %d activated → ARIA control review task created", entity_id)
    except Exception as e:
        log.warning("plan_activation_triggers_control_review error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SENTINEL EVENTS → OTHER MODULES
# ═══════════════════════════════════════════════════════════════════════════════

@on("sentinel.breach.confirmed")
def breach_creates_risk_and_task(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    """When Sentinel confirms a data breach, create risk + task + notification."""
    from modules.sentinel.jurisdictions import JURISDICTION_RULES, get_breach_deadline_hours
    db = get_db()
    try:
        title = payload.get("title", f"Data Breach #{entity_id}")
        severity = (payload.get("severity") or "critical").lower()
        affected = payload.get("affected_records", "unknown")
        regulation = payload.get("regulation") or settings.DEFAULT_REGULATION
        active_jurisdictions = payload.get("active_jurisdictions") or [regulation]
        breach_hours = get_breach_deadline_hours(regulation)

        risk_id = _insert_risk(
            db,
            title=f"Data Breach: {title}",
            description=(
                f"Confirmed data breach requiring notification assessment and remediation. "
                f"Affected records: {affected}. "
                f"{regulation} notification obligation: {breach_hours}h from discovery."
            ),
            source_module="sentinel", entity_type="breach", entity_id=entity_id,
            category="data_protection", likelihood=5, impact=5,
            risk_level="critical", user_id=user_id,
        )

        task_id = _insert_task(
            db,
            title=f"BREACH RESPONSE: {title}",
            description=(
                f"Data breach confirmed. Assess {regulation} notification obligations "
                f"within {breach_hours}h of discovery."
            ),
            module="sentinel", entity_type="breach", entity_id=entity_id,
            priority="critical", user_id=user_id,
        )

        if risk_id:
            create_cross_module_link(
                "sentinel", "breach", entity_id,
                "platform", "risk_register", risk_id,
                relationship="triggers", user_id=user_id, db=db,
            )

        # Auto-evidence: breach notification record
        _insert_evidence(
            db,
            title=f"Breach Confirmed: {title}",
            description=(
                f"Data breach '{title}' confirmed on {datetime.now():%Y-%m-%d %H:%M}. "
                f"Severity: {severity}. Affected records: {affected}. "
                f"{regulation} notification deadline: {breach_hours}h from discovery. "
                f"Risk and response task created."
            ),
            category="breach_record",
            module="sentinel", entity_type="breach", entity_id=entity_id,
            user_id=user_id, tags=f"auto,breach,{severity},sentinel",
        )

        _notify_admins(
            db, "sentinel",
            f"DATA BREACH: {title}",
            f"Severity: {severity}. {regulation} notification deadline: {breach_hours}h from discovery.",
            "/sentinel/#breaches",
        )

        # Create one regulatory obligation per jurisdiction group (grouped by deadline hours).
        # Jurisdictions sharing the same deadline are combined; different deadlines get separate rows.
        try:
            deadline_groups: dict = {}
            for jkey in active_jurisdictions:
                jrules = JURISDICTION_RULES.get(jkey, {})
                hours = jrules.get("breach_hours") or get_breach_deadline_hours(jkey)
                deadline_groups.setdefault(hours, []).append(jkey)

            for hours, jkeys in deadline_groups.items():
                due_dt = (utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
                if len(jkeys) == 1:
                    jkey = jkeys[0]
                    jrules = JURISDICTION_RULES.get(jkey, {})
                    regulator = jrules.get("authority_short") or jrules.get("authority") or "Supervisory Authority"
                    reg_name = f"{jkey} — Breach Notification"
                    obligation_text = (
                        jrules.get("breach_note")
                        or f"Notify {regulator} within {hours} hours of becoming aware of the breach."
                    )
                else:
                    authorities = []
                    for jkey in jkeys:
                        jrules = JURISDICTION_RULES.get(jkey, {})
                        auth = jrules.get("authority_short") or jrules.get("authority") or jkey
                        authorities.append(auth)
                    regulator = ", ".join(authorities)
                    reg_name = "Breach Notification — " + " | ".join(jkeys)
                    obligation_text = (
                        f"Notify all applicable supervisory authorities within {hours} hours: {regulator}."
                    )

                ob_id = insert_returning_id(db,
                    "INSERT INTO erm_regulatory_obligations "
                    "(regulator, regulation_name, obligation, applicable_departments, "
                    " evidence_required, due_date, status, notes, created_by, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    (
                        regulator,
                        reg_name,
                        obligation_text,
                        "Privacy,Legal,Compliance",
                        "Breach notification record, impact assessment on data subjects, "
                        "description of breach nature, categories and approximate number of "
                        "data subjects and records concerned.",
                        due_dt,
                        "pending",
                        f"Auto-created from Sentinel breach #{entity_id}: '{title}'. "
                        f"Severity: {severity}. Affected records: {affected}. "
                        f"Deadline: {hours}h from breach awareness ({due_dt} UTC).",
                        user_id,
                    ),
                )
                create_cross_module_link(
                    "sentinel", "breach", entity_id,
                    "erm", "obligation", ob_id,
                    relationship="triggers", user_id=user_id, db=db,
                )
                log.info(
                    "Obligation #%d created for breach #%d — %s (due %s)",
                    ob_id, entity_id, reg_name, due_dt,
                )
        except Exception as ob_exc:
            log.warning("Could not create jurisdiction obligation for breach: %s", ob_exc)

        db.commit()
        notify_connectors(
            f"[ThemisIQ] BREACH CONFIRMED: {title} — severity: {severity}, "
            f"affected records: {affected}. {regulation} deadline: {breach_hours}h. "
            f"Review: /sentinel/#breaches"
        )
    except Exception as e:
        log.warning("Could not create entries from breach: %s", e)
    finally:
        db.close()


@on("sentinel.dpia.completed")
def dpia_completed_handler(event_type, source_module, entity_type,
                           entity_id, payload, user_id, **kw):
    """
    When Sentinel completes a DPIA:
    - If risk_level is high, create a risk register entry
    - Create a task to implement recommendations
    - Link DPIA to risk register if applicable
    """
    db = get_db()
    try:
        title = payload.get("title", f"DPIA #{entity_id}")
        risk_level = (payload.get("risk_level") or "low").lower()
        recommendations = payload.get("recommendations", "")

        # Only escalate high-risk DPIAs
        risk_id = None
        if risk_level in ("high", "critical", "very high"):
            risk_id = _insert_risk(
                db,
                title=f"High-Risk DPIA: {title}",
                description=(
                    f"DPIA completed with {risk_level} residual risk. "
                    f"Recommendations: {recommendations[:200]}"
                ),
                source_module="sentinel", entity_type="dpia", entity_id=entity_id,
                category="data_protection",
                likelihood=4 if risk_level == "high" else 5,
                impact=4 if risk_level == "high" else 5,
                risk_level=risk_level, user_id=user_id,
            )
            if risk_id:
                create_cross_module_link(
                    "sentinel", "dpia", entity_id,
                    "platform", "risk_register", risk_id,
                    relationship="triggers", user_id=user_id, db=db,
        )

        # Always create implementation task
        _insert_task(
            db,
            title=f"Implement DPIA recommendations: {title}",
            description=(
                f"DPIA '{title}' completed (risk: {risk_level}). "
                f"Implement recommended mitigations."
            ),
            module="sentinel", entity_type="dpia", entity_id=entity_id,
            priority="critical" if risk_level in ("high", "critical", "very high") else "medium",
            user_id=user_id,
        )

        # Auto-evidence: DPIA completion record
        _insert_evidence(
            db,
            title=f"DPIA Completed: {title}",
            description=(
                f"Data Protection Impact Assessment '{title}' completed on "
                f"{datetime.now():%Y-%m-%d %H:%M}. Residual risk: {risk_level}. "
                f"Recommendations: {recommendations[:200]}"
            ),
            category="dpia_record",
            module="sentinel", entity_type="dpia", entity_id=entity_id,
            user_id=user_id, tags=f"auto,dpia,{risk_level},sentinel",
        )

        _notify_admins(
            db, "sentinel",
            f"DPIA Completed: {title}",
            f"Risk level: {risk_level}. Implementation task created.",
            "/sentinel/#dpias",
        )
        db.commit()
        log.info("Handled DPIA completion: '%s' (risk=%s)", title, risk_level)
    except Exception as e:
        log.warning("dpia_completed_handler error: %s", e)
    finally:
        db.close()


# ── XM-1: Sentinel breach → BCM incident ─────────────────────────────────────
@on("sentinel.breach.confirmed")
def breach_triggers_bcm_incident(event_type, source_module, entity_type,
                                  entity_id, payload, user_id, **kw):
    """
    XM-1: Confirmed data breach → auto-create a BCM incident so the
    business continuity team is looped in immediately.
    """
    db = get_db()
    try:
        title    = payload.get("title", f"Data Breach #{entity_id}")
        severity = (payload.get("severity") or "high").lower()
        # Map Sentinel severity → BCM severity tier
        bcm_sev  = {"critical": "critical", "high": "major", "medium": "significant"}.get(severity, "major")

        incident_id = insert_returning_id(db,
            "INSERT INTO bcm_incidents "
            "(title, description, severity, status, started_at, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (
                f"DATA BREACH: {title}",
                f"Automatically escalated from Sentinel breach #{entity_id}. "
                f"Severity: {severity}. Activate relevant BCM plan and initiate "
                f"crisis communications protocol.",
                bcm_sev, "open",
            ),
        )
        db.commit()

        create_cross_module_link(
            "sentinel", "breach",   entity_id,
            "bcm",      "incident", incident_id,
            relationship="triggers", user_id=user_id, db=db,
        )

        _notify_admins(
            db, "bcm",
            f"BCM INCIDENT CREATED: {title}",
            f"Data breach escalated to BCM. Incident #{incident_id} opened (severity: {bcm_sev}).",
            "/bcm/#incidents",
        )
        log.info("XM-1: breach %d → BCM incident %d", entity_id, incident_id)
    except Exception as e:
        log.warning("breach_triggers_bcm_incident error: %s", e)
    finally:
        db.close()


@on("sentinel.dsr.overdue")
def dsr_overdue_handler(event_type, source_module, entity_type,
                        entity_id, payload, user_id, **kw):
    """
    When a DSR becomes overdue:
    - Create a critical task
    - Create a risk register entry (regulatory exposure)
    - Notify admins urgently
    """
    db = get_db()
    try:
        subject = payload.get("subject_name", "Data Subject")
        request_type = payload.get("request_type", "access")
        days_overdue = payload.get("days_overdue", 0)
        deadline = payload.get("deadline", "unknown")

        risk_id = _insert_risk(
            db,
            title=f"Overdue DSR: {request_type} request (#{entity_id})",
            description=(
                f"Data subject request #{entity_id} ({request_type}) is {days_overdue} "
                f"day(s) overdue (deadline: {deadline}). Regulatory breach risk."
            ),
            source_module="sentinel", entity_type="dsr", entity_id=entity_id,
            category="data_protection", likelihood=5, impact=4,
            risk_level="high", user_id=user_id,
        )

        _insert_task(
            db,
            title=f"OVERDUE DSR: {request_type} #{entity_id}",
            description=(
                f"DSR is {days_overdue} day(s) past deadline. "
                f"Complete immediately to avoid regulatory penalty."
            ),
            module="sentinel", entity_type="dsr", entity_id=entity_id,
            priority="critical", user_id=user_id,
        )

        if risk_id:
            create_cross_module_link(
                "sentinel", "dsr", entity_id,
                "platform", "risk_register", risk_id,
                relationship="triggers", user_id=user_id, db=db,
        )

        _insert_evidence(
            db,
            title=f"DSR Overdue Alert: {request_type} #{entity_id}",
            description=(
                f"Data subject {request_type} request #{entity_id} became "
                f"{days_overdue} day(s) overdue (deadline: {deadline}). "
                f"Risk entry and critical task auto-created."
            ),
            category="dsr_overdue",
            module="sentinel", entity_type="dsr", entity_id=entity_id,
            user_id=user_id, tags=f"auto,dsr,overdue,{request_type},sentinel",
        )

        _notify_admins(
            db, "sentinel",
            f"OVERDUE DSR #{entity_id}",
            f"{request_type} request is {days_overdue} day(s) overdue. Immediate action required.",
            "/sentinel/#dsrs",
        )
        db.commit()
        log.info("Handled overdue DSR #%d (%d days overdue)", entity_id, days_overdue)
    except Exception as e:
        log.warning("dsr_overdue_handler error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# XM-3 & XM-4: GRID FINDING → SENTINEL  |  SENTINEL DPIA → ARIA CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

_DATA_KEYWORDS = frozenset({
    "data", "personal", "privacy", "gdpr", "pii", "customer",
    "user record", "database", "datastore", "dpa", "data subject",
})


@on("grid.finding.created")
def finding_triggers_sentinel_check(event_type, source_module, entity_type,
                                     entity_id, payload, user_id, **kw):
    """
    XM-3: Critical/major GRID finding whose title contains data-related keywords
    triggers a Sentinel privacy impact assessment task.
    """
    title    = payload.get("title", "")
    severity = (payload.get("severity") or "").lower()
    if severity not in ("critical", "major"):
        return
    if not any(kw in title.lower() for kw in _DATA_KEYWORDS):
        return

    db = get_db()
    try:
        _insert_task(
            db,
            title=f"PRIVACY CHECK: Audit finding may involve personal data — {title}",
            description=(
                f"GRID {severity} finding #{entity_id} contains data-related content. "
                f"Assess whether personal data is impacted and whether a DPIA or breach "
                f"notification assessment is required under Sentinel."
            ),
            module="sentinel", entity_type="grid_finding", entity_id=entity_id,
            priority="high", user_id=user_id,
        )
        create_cross_module_link(
            "grid",     "finding",      entity_id,
            "sentinel", "grid_finding", entity_id,
            relationship="triggers", user_id=user_id, db=db,
        )
        db.commit()
        log.info("XM-3: GRID finding %d → Sentinel privacy check task created", entity_id)
    except Exception as e:
        log.warning("finding_triggers_sentinel_check error: %s", e)
    finally:
        db.close()


@on("sentinel.dpia.completed")
def dpia_links_to_aria_controls(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    """
    XM-4: Completed DPIA → find ARIA controls matching the DPIA's data
    categories and create 'mitigates' cross-module links so the DPIA is
    grounded in the control framework.
    """
    categories = payload.get("data_categories", "")
    if not categories:
        return

    db = get_db()
    try:
        keywords = [c.strip().lower() for c in str(categories).split(",") if c.strip()]
        linked = 0
        for kw in keywords[:5]:   # cap to avoid runaway queries
            rows = db.execute(
                "SELECT id FROM aria_controls "
                "WHERE LOWER(name) LIKE %s OR LOWER(description) LIKE %s "
                "LIMIT 3",
                (f"%{kw}%", f"%{kw}%"),
            ).fetchall()
            for (ctrl_id,) in rows:
                create_cross_module_link(
                    "sentinel", "dpia",    entity_id,
                    "aria",     "control", ctrl_id,
                    relationship="mitigates", user_id=user_id, db=db,
        )
                linked += 1
        db.commit()
        if linked:
            log.info("XM-4: DPIA %d linked to %d ARIA control(s)", entity_id, linked)
    except Exception as e:
        log.warning("dpia_links_to_aria_controls error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ERM — AUTO-ELEVATION: All critical cross-module events → erm_enterprise_risks
# ═══════════════════════════════════════════════════════════════════════════════

def _insert_erm_risk(db, title, description, category, likelihood, impact,
                     source_module, source_risk_id=None, board_visibility=0, user_id=None):
    """Insert into erm_enterprise_risks. Returns lastrowid or None."""
    try:
        # Avoid duplicates: don't re-insert if same source entity already has an ERM risk
        if source_risk_id:
            exists = db.execute(
                "SELECT id FROM erm_enterprise_risks WHERE source_module=%s AND source_risk_id=%s",
                (source_module, source_risk_id)
            ).fetchone()
            if exists:
                return exists[0]
        cur = insert_returning_id(db,
            """INSERT INTO erm_enterprise_risks
               (title, description, category, likelihood, impact, velocity,
                treatment, status, board_visibility, source_module, source_risk_id, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (title, description, category, likelihood, impact, 3,
             "mitigate", "open", board_visibility, source_module, source_risk_id, user_id)
        )
        # PLAN-23: this insert bypasses create_enterprise_risk, so give the
        # elevated risk its ref/IRR/RRR immediately rather than waiting for
        # the next startup backfill. Lazy import avoids a circular import
        # at module load (mirrors governance/effectiveness.py's cascade).
        try:
            from modules.erm.data_service import _next_ref, recompute_residual_for_risk
            ref = _next_ref(db, "erm_enterprise_risks", "risk_ref", "RSK-", 4)
            irr = int(likelihood) * int(impact)
            db.execute(
                "UPDATE erm_enterprise_risks SET risk_ref=%s, irr_score=%s, "
                "inherent_score=%s WHERE id=%s",
                (ref, irr, irr, cur))
            recompute_residual_for_risk(db, cur)
        except Exception as exc:
            log.warning("_insert_erm_risk: ref/IRR backfill failed for risk %s: %s", cur, exc)
        return cur
    except Exception as exc:
        log.warning("_insert_erm_risk failed: %s", exc)
        return None


@on("grid.finding.created")
def finding_elevates_to_erm(event_type, source_module, entity_type,
                            entity_id, payload, user_id, **kw):
    """XM-ERM-1: Major/critical GRID findings → ERM enterprise risk (board-visible if critical)."""
    severity = (payload.get("severity") or "minor").lower()
    if severity not in ("major", "critical"):
        return
    db = get_db()
    try:
        title = payload.get("title", f"GRID Finding #{entity_id}")
        lh = 4 if severity == "critical" else 3
        imp = 5 if severity == "critical" else 4
        erm_id = _insert_erm_risk(
            db,
            title=f"Audit Finding Risk: {title}",
            description=(
                f"{severity.capitalize()} audit finding escalated to ERM. "
                f"Audit ID: {payload.get('audit_id', 'N/A')}. "
                f"{payload.get('description', '')[:300]}"
            ),
            category="compliance",
            likelihood=lh, impact=imp,
            source_module="grid", source_risk_id=entity_id,
            board_visibility=1 if severity == "critical" else 0,
            user_id=user_id,
        )
        if erm_id:
            create_cross_module_link(
                "grid", "finding", entity_id,
                "erm", "enterprise_risk", erm_id,
                relationship="escalated_to", user_id=user_id, db=db,
            )
        db.commit()
        log.info("XM-ERM-1: GRID finding %d (sev=%s) → erm_enterprise_risks #%s",
                 entity_id, severity, erm_id)
        if erm_id:
            emit(ERM_RISK_IDENTIFIED,
                 source_module="grid", entity_type="finding", entity_id=entity_id,
                 payload={"title": title, "severity": severity, "erm_risk_id": erm_id},
                 user_id=user_id)
    except Exception as e:
        log.warning("finding_elevates_to_erm error: %s", e)
    finally:
        db.close()


@on("bcm.risk.escalated")
def bcm_risk_elevates_to_erm(event_type, source_module, entity_type,
                              entity_id, payload, user_id, **kw):
    """XM-ERM-2: BCM high/critical risks → ERM enterprise risk."""
    severity = (payload.get("severity") or "high").lower()
    db = get_db()
    try:
        title = payload.get("title", f"BCM Risk #{entity_id}")
        desc = payload.get("description", "")
        lh = 5 if severity == "critical" else 4
        imp = 5 if severity == "critical" else 4
        erm_id = _insert_erm_risk(
            db,
            title=f"BCM Escalation: {title}",
            description=(
                f"High-severity BCM risk promoted to enterprise risk register. "
                f"Severity: {severity}. {desc[:250]}"
            ),
            category="operational",
            likelihood=lh, impact=imp,
            source_module="bcm", source_risk_id=entity_id,
            board_visibility=1 if severity == "critical" else 0,
            user_id=user_id,
        )
        if erm_id:
            create_cross_module_link(
                "bcm", "risk", entity_id,
                "erm", "enterprise_risk", erm_id,
                relationship="escalated_to", user_id=user_id, db=db,
            )
        db.commit()
        log.info("XM-ERM-2: BCM risk %d → erm_enterprise_risks #%s", entity_id, erm_id)
        if erm_id:
            emit(ERM_RISK_IDENTIFIED,
                 source_module="bcm", entity_type="risk", entity_id=entity_id,
                 payload={"title": title, "severity": severity, "erm_risk_id": erm_id},
                 user_id=user_id)
    except Exception as e:
        log.warning("bcm_risk_elevates_to_erm error: %s", e)
    finally:
        db.close()


@on("sentinel.breach.confirmed")
def breach_elevates_to_erm(event_type, source_module, entity_type,
                            entity_id, payload, user_id, **kw):
    """XM-ERM-3: Confirmed data breaches → board-visible ERM enterprise risk."""
    db = get_db()
    try:
        from modules.sentinel.jurisdictions import get_breach_deadline_hours
        title = payload.get("title", f"Data Breach #{entity_id}")
        severity = (payload.get("severity") or "critical").lower()
        affected = payload.get("affected_records", "unknown")
        regulation = payload.get("regulation") or settings.DEFAULT_REGULATION
        breach_hours = get_breach_deadline_hours(regulation)
        erm_id = _insert_erm_risk(
            db,
            title=f"Data Breach Risk: {title}",
            description=(
                f"Confirmed data breach escalated to ERM. Severity: {severity}. "
                f"Affected records: {affected}. "
                f"{regulation} notification obligation applies — {breach_hours}h from discovery. "
                f"Immediate executive escalation required."
            ),
            category="compliance",
            likelihood=5, impact=5,
            source_module="sentinel", source_risk_id=entity_id,
            board_visibility=1,  # Always board-visible
            user_id=user_id,
        )
        if erm_id:
            create_cross_module_link(
                "sentinel", "breach", entity_id,
                "erm", "enterprise_risk", erm_id,
                relationship="escalated_to", user_id=user_id, db=db,
            )
        db.commit()  # commit before nested emit() calls to avoid "database is locked"
        log.info("XM-ERM-3: Sentinel breach %d → erm_enterprise_risks #%s (board-visible)",
                 entity_id, erm_id)
        if erm_id:
            emit(ERM_RISK_ESCALATED,
                 source_module="sentinel", entity_type="breach", entity_id=entity_id,
                 payload={"title": title, "severity": severity, "erm_risk_id": erm_id},
                 user_id=user_id)
            # GAP-3: Check appetite immediately — don't wait for UI to poll
            _check_and_emit_appetite_breach(db, "compliance", user_id=user_id)
    except Exception as e:
        log.warning("breach_elevates_to_erm error: %s", e)
    finally:
        db.close()


@on("orm.event.elevated")
def orm_event_links_to_erm(event_type, source_module, entity_type,
                            entity_id, payload, user_id, **kw):
    """XM-ERM-4: ORM event elevation → ensure cross_module_link exists and board flag set."""
    erm_risk_id = payload.get("erm_risk_id")
    if not erm_risk_id:
        return
    db = get_db()
    try:
        create_cross_module_link(
            "orm", "event", entity_id,
            "erm", "enterprise_risk", erm_risk_id,
            relationship="elevated_to", user_id=user_id, db=db,
        )
        # Set board_visibility for critical ORM events
        sev = (payload.get("severity") or "").lower()
        if sev == "critical":
            db.execute(
                "UPDATE erm_enterprise_risks SET board_visibility=1 WHERE id=%s",
                (erm_risk_id,)
            )
        db.commit()
        log.info("XM-ERM-4: ORM event %d linked to erm_enterprise_risks #%d",
                 entity_id, erm_risk_id)
    except Exception as e:
        log.warning("orm_event_links_to_erm error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# XM-NEW: SENTINEL BREACH → POST-INCIDENT GRID AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

@on("sentinel.breach.confirmed")
def sentinel_breach_triggers_post_incident_audit(event_type, source_module, entity_type,
                                                  entity_id, payload, user_id, **kw):
    """
    GAP-1: When a high/critical Sentinel breach is confirmed, auto-create a
    draft post-incident audit in GRID so investigators have a structured workspace.
    """
    db = get_db()
    try:
        severity = (payload.get("severity") or "high").lower()
        if severity not in ("high", "critical"):
            return

        title = payload.get("title", f"Data Breach #{entity_id}")
        regulation = payload.get("regulation") or settings.DEFAULT_REGULATION
        audit_name = f"Post-Incident Audit [{regulation}]: {title}"

        # Check if a post-incident audit already exists for this breach
        existing = db.execute(
            "SELECT id FROM grid_audits WHERE name=%s", (audit_name,)
        ).fetchone()
        if existing:
            return

        audit_id = insert_returning_id(db,
            "INSERT INTO grid_audits "
            "(name, audit_type, status, scope, objective, criteria, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)",
            (
                audit_name,
                "Special",
                "Planning",
                f"Post-incident review of data breach: {title}",
                "Determine root cause, assess control failures, validate remediation, "
                "and confirm notification obligations were met.",
                f"{regulation} notification requirements; ISO 27001 A.5.24–A.5.27; "
                "Organisational incident response procedures",
            ),
        )

        create_cross_module_link(
            "sentinel", "breach", entity_id,
            "grid", "audit", audit_id,
            relationship="triggers", user_id=user_id, db=db,
        )

        # Task to notify the audit team
        _insert_task(
            db,
            title=f"Post-Incident Audit Required: {title}",
            description=(
                f"A {severity} data breach requires a formal post-incident audit. "
                f"Draft audit #{audit_id} has been created in the Audit module. "
                f"Assign auditor and begin within 5 business days."
            ),
            module="grid", entity_type="audit", entity_id=audit_id,
            priority="critical" if severity == "critical" else "high",
            user_id=user_id,
        )

        _notify_admins(
            db, "grid",
            f"Post-Incident Audit Created: {title}",
            f"Breach severity: {severity}. Draft audit ready in Audit module. "
            f"Assign auditor and activate.",
            "/grid/",
        )
        db.commit()
        log.info("GAP-1: Sentinel breach %d → GRID draft audit #%d", entity_id, audit_id)
    except Exception as e:
        log.warning("sentinel_breach_triggers_post_incident_audit error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# XM-NEW: SENTINEL BREACH → ORM OPERATIONAL EVENT
# ═══════════════════════════════════════════════════════════════════════════════

@on("sentinel.breach.confirmed")
def sentinel_breach_creates_orm_event(event_type, source_module, entity_type,
                                      entity_id, payload, user_id, **kw):
    """
    XM-SEN-ORM: Confirmed data breach → auto-create an ORM operational event
    (system_failure/fraud) so operational risk tracking is in sync with Sentinel.
    Only fires for high or critical severity breaches.
    """
    db = get_db()
    try:
        severity = (payload.get("severity") or "high").lower()
        if severity not in ("high", "critical"):
            return  # Only escalate serious breaches

        title = payload.get("title", f"Data Breach #{entity_id}")
        affected = payload.get("affected_records", 0)
        regulation = payload.get("regulation") or settings.DEFAULT_REGULATION

        orm_event_id = insert_returning_id(db,
            "INSERT INTO orm_events "
            "(title, description, event_type, severity, status, department, "
            " root_cause_category, detected_at, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (
                f"[{regulation}] Data Breach: {title}",
                (
                    f"Auto-created from Sentinel breach #{entity_id} ({regulation}). "
                    f"Severity: {severity}. Affected records: {affected}. "
                    f"Review {regulation} obligations and raise notifications if required."
                ),
                "system_failure",
                severity,
                "open",
                "IT/Security",
                "system",
            ),
        )
        db.commit()

        create_cross_module_link(
            "sentinel", "breach", entity_id,
            "orm", "event", orm_event_id,
            relationship="triggers", user_id=user_id, db=db,
        )

        _notify_admins(
            db, "orm",
            f"ORM Event Auto-Created: Data Breach",
            f"Sentinel breach '{title}' ({severity}) auto-logged as an ORM operational event. "
            f"Review in ORM → Events.",
            "/orm/",
        )
        db.commit()
        log.info("XM-SEN-ORM: Sentinel breach %d → ORM event %d", entity_id, orm_event_id)
    except Exception as e:
        log.warning("sentinel_breach_creates_orm_event error: %s", e)
    finally:
        db.close()


@on("sentinel.dsr.overdue")
def sentinel_dsr_overdue_creates_orm_event(event_type, source_module, entity_type,
                                            entity_id, payload, user_id, **kw):
    """
    XM-SEN-ORM-2: Overdue DSR → auto-create ORM compliance/human_error event
    so that compliance failures appear in the operational risk log.
    """
    db = get_db()
    try:
        request_type = payload.get("request_type", "access")
        days_overdue = payload.get("days_overdue", 0)
        subject = payload.get("subject_name", "Data Subject")

        orm_event_id = insert_returning_id(db,
            "INSERT INTO orm_events "
            "(title, description, event_type, severity, status, department, "
            " root_cause_category, detected_at, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (
                f"Overdue DSR: {request_type} request (#{entity_id})",
                (
                    f"Data subject '{subject}' {request_type} request #{entity_id} is "
                    f"{days_overdue} day(s) overdue. "
                    f"Auto-created from Sentinel DSR tracking. Resolve immediately to avoid regulatory penalty."
                ),
                "human_error",
                "high",
                "open",
                "Privacy/Compliance",
                "process",
            ),
        )
        db.commit()

        create_cross_module_link(
            "sentinel", "dsr", entity_id,
            "orm", "event", orm_event_id,
            relationship="triggers", user_id=user_id, db=db,
        )
        db.commit()
        log.info("XM-SEN-ORM-2: Sentinel DSR %d overdue → ORM event %d", entity_id, orm_event_id)
    except Exception as e:
        log.warning("sentinel_dsr_overdue_creates_orm_event error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# GAP-4: ORM EVENT LOGGED → CROSS-MODULE ACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@on("orm.event.logged")
def orm_event_logged_handler(event_type, source_module, entity_type,
                              entity_id, payload, user_id, **kw):
    """
    GAP-4: ORM_EVENT_LOGGED was emitted but had zero handlers — silently dropped.
    Now:
    - High/critical human_error events → notify compliance team
    - High financial impact (>10000) → auto-flag in risk_register
    - High/critical severity → notify ORM team
    """
    db = get_db()
    try:
        severity = (payload.get("severity") or "medium").lower()
        event_type_val = (payload.get("event_type") or "").lower()
        financial_impact = float(payload.get("financial_impact") or 0)
        title = payload.get("title", f"ORM Event #{entity_id}")

        # B1: Auto-increment KRIs linked to this event type (all severities)
        if event_type_val:
            matching_kris = db.execute(
                "SELECT id, current_value, name FROM orm_kris "
                "WHERE auto_update_event_type=%s AND status='active'",
                (event_type_val,),
            ).fetchall()
            for kri in matching_kris:
                new_val = (kri["current_value"] or 0) + 1
                db.execute(
                    "UPDATE orm_kris SET current_value=%s, trend='worsening', "
                    "last_updated=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (new_val, kri["id"]),
                )
                db.execute(
                    "INSERT INTO orm_kri_history (kri_id, value, recorded_at) VALUES (%s,%s,CURRENT_TIMESTAMP)",
                    (kri["id"], new_val),
                )
                log.info("KRI '%s' auto-incremented to %s via event type '%s'",
                         kri["name"], new_val, event_type_val)

        if severity not in ("high", "critical"):
            db.commit()
            return  # Only act on high/critical events to avoid notification spam

        # Auto-flag high-impact events in the risk register
        if financial_impact > 10000:
            risk_id = _insert_risk(
                db,
                title=f"ORM High-Impact Event: {title}",
                description=(
                    f"Operational risk event with financial impact ${financial_impact:,.0f}. "
                    f"Type: {event_type_val}. Severity: {severity}. "
                    f"Auto-flagged from ORM event #{entity_id}."
                ),
                source_module="orm", entity_type="event", entity_id=entity_id,
                category="operational", likelihood=4, impact=4,
                risk_level=severity, user_id=user_id,
            )
            if risk_id:
                create_cross_module_link(
                    "orm", "event", entity_id,
                    "platform", "risk_register", risk_id,
                    relationship="triggers", user_id=user_id, db=db,
        )

        # Notify compliance team for human_error high/critical events
        if event_type_val == "human_error":
            _notify_admins(
                db, "orm",
                f"ORM Human Error Event: {title}",
                f"A {severity} human error operational event has been logged. "
                f"Review in ORM → Events and consider policy/training actions.",
                "/orm/",
            )
        else:
            _notify_admins(
                db, "orm",
                f"ORM {severity.capitalize()} Event: {title}",
                f"A {severity} operational risk event ({event_type_val}) has been logged.",
                "/orm/",
            )

        db.commit()
        log.info("GAP-4: ORM event %d (%s, %s) handled", entity_id, severity, event_type_val)
    except Exception as e:
        log.warning("orm_event_logged_handler error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# XM-NEW: BCM INCIDENT → ERM ESCALATION
# ═══════════════════════════════════════════════════════════════════════════════

@on("bcm.incident.declared")
def bcm_incident_escalates_to_erm(event_type, source_module, entity_type,
                                   entity_id, payload, user_id, **kw):
    """
    XM-BCM-ERM: High/critical BCM incidents → board-visible ERM enterprise risk.
    BCM risks already escalate to ERM; this covers declared incidents too.
    """
    db = get_db()
    try:
        severity = (payload.get("severity") or "major").lower()
        if severity not in ("critical", "major"):
            return  # Only escalate serious incidents

        title = payload.get("title", f"BCM Incident #{entity_id}")
        erm_id = _insert_erm_risk(
            db,
            title=f"BCM Incident: {title}",
            description=(
                f"High-severity business continuity incident escalated to ERM board. "
                f"Severity: {severity}. Incident #{entity_id} declared. "
                f"BCM response teams activated. Review strategic risk impact."
            ),
            category="operational",
            likelihood=5 if severity == "critical" else 4,
            impact=5 if severity == "critical" else 4,
            source_module="bcm",
            source_risk_id=entity_id,
            board_visibility=1 if severity == "critical" else 0,
            user_id=user_id,
        )
        if erm_id:
            create_cross_module_link(
                "bcm", "incident", entity_id,
                "erm", "enterprise_risk", erm_id,
                relationship="escalated_to", user_id=user_id, db=db,
            )
            _notify_admins(
                db, "erm",
                f"ERM Risk Created: BCM Incident",
                f"BCM incident '{title}' ({severity}) auto-escalated to ERM enterprise risk #{erm_id}.",
                "/erm/",
            )
        db.commit()
        log.info("XM-BCM-ERM: BCM incident %d → erm_enterprise_risks #%s", entity_id, erm_id)
        if erm_id:
            emit(ERM_RISK_IDENTIFIED,
                 source_module="bcm", entity_type="incident", entity_id=entity_id,
                 payload={"title": title, "severity": severity, "erm_risk_id": erm_id},
                 user_id=user_id)
    except Exception as e:
        log.warning("bcm_incident_escalates_to_erm error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SENTINEL BREACH RESOLVED → CLOSE LINKED ERM RISK + RISK REGISTER
# ═══════════════════════════════════════════════════════════════════════════════

@on("sentinel.breach.resolved")
def breach_resolved_closes_linked_risks(event_type, source_module, entity_type,
                                         entity_id, payload, user_id, **kw):
    """
    XM-CLOSE-1: When a Sentinel breach is closed/resolved/contained:
      1. Close the linked ERM enterprise risk (source_module='sentinel', source_risk_id=breach_id)
      2. Close the platform risk_register entry created for this breach
      3. Close the BCM incident that was auto-created from this breach
      4. Notify risk owners and admins
    The appetite framework recalculates automatically on next load because
    get_appetite_status() queries WHERE status NOT IN ('closed','accepted').
    """
    db = get_db()
    try:
        breach_title = payload.get("title", f"Breach #{entity_id}")
        closed_status = payload.get("closed_status", "resolved")

        closed_count = 0

        # ── 1. Close the ERM enterprise risk ───────────────────────────────
        erm_rows = db.execute(
            "SELECT id, title, category, owner_id FROM erm_enterprise_risks "
            "WHERE source_module='sentinel' AND source_risk_id=%s "
            "AND status NOT IN ('closed','accepted')",
            (entity_id,),
        ).fetchall()

        for erm in erm_rows:
            db.execute(
                "UPDATE erm_enterprise_risks "
                "SET status='closed', workflow_step='closed', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=%s",
                (erm["id"],),
            )
            closed_count += 1

            # Notify the risk owner (uses same db connection — safe before commit)
            if erm["owner_id"]:
                _notify(
                    db, erm["owner_id"], "erm",
                    f"Risk Closed: {erm['title']}",
                    f"The linked Sentinel breach '{breach_title}' was {closed_status}. "
                    f"ERM risk has been automatically closed. "
                    f"Review the risk appetite dashboard to confirm posture.",
                    "/erm/appetite",
                )

            log.info(
                "XM-CLOSE-1: Sentinel breach %d resolved → closed ERM risk #%d ('%s')",
                entity_id, erm["id"], erm["title"],
            )

        # ── 2. Close the platform risk_register entry ──────────────────────
        db.execute(
            "UPDATE risk_register SET status='closed', updated_at=CURRENT_TIMESTAMP "
            "WHERE source_module='sentinel' AND source_entity_type='breach' "
            "AND source_entity_id=%s AND status != 'closed'",
            (entity_id,),
        )

        # ── 3. Close the BCM incident auto-created from this breach ────────
        # Find via cross_module_links: sentinel/breach → bcm/incident
        bcm_links = db.execute(
            "SELECT target_id FROM cross_module_links "
            "WHERE source_module='sentinel' AND source_type='breach' "
            "AND source_id=%s AND target_module='bcm' AND target_type='incident'",
            (entity_id,),
        ).fetchall()

        for link in bcm_links:
            inc_id = link["target_id"]
            db.execute(
                "UPDATE bcm_incidents "
                "SET status='resolved', resolved_at=CURRENT_TIMESTAMP "
                "WHERE id=%s AND status NOT IN ('closed','resolved')",
                (inc_id,),
            )
            log.info(
                "XM-CLOSE-1: Sentinel breach %d resolved -> closed BCM incident #%d",
                entity_id, inc_id,
            )

        # ── 4. Close the ORM event auto-created from this breach ──────────
        orm_links = db.execute(
            "SELECT target_id FROM cross_module_links "
            "WHERE source_module='sentinel' AND source_type='breach' "
            "AND source_id=%s AND target_module='orm' AND target_type='event'",
            (entity_id,),
        ).fetchall()
        for link in orm_links:
            orm_id = link["target_id"]
            db.execute(
                "UPDATE orm_events SET status='resolved', resolved_at=CURRENT_TIMESTAMP, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=%s AND status NOT IN ('resolved','closed')",
                (orm_id,),
            )
            log.info(
                "XM-CLOSE-1: Sentinel breach %d resolved -> closed ORM event #%d",
                entity_id, orm_id,
            )

        if closed_count > 0:
            _notify_admins(
                db, "erm",
                f"ERM Risk Auto-Closed: {breach_title}",
                f"Sentinel breach '{breach_title}' was {closed_status}. "
                f"{closed_count} linked ERM enterprise risk(s) automatically closed. "
                f"Risk appetite framework will reflect the updated posture.",
                "/erm/appetite",
            )
        else:
            log.info(
                "XM-CLOSE-1: Sentinel breach %d resolved — no open linked ERM risks found",
                entity_id,
            )

        db.commit()
        log.info(
            "XM-CLOSE-1: breach #%d '%s' resolved → %d ERM risk(s) closed, "
            "%d BCM incident(s) closed",
            entity_id, breach_title, closed_count, len(bcm_links),
        )
        # Emit ERM_RISK_CLOSED after commit so nested handlers don't hit a write lock
        for erm in erm_rows:
            emit(
                ERM_RISK_CLOSED,
                source_module="erm",
                entity_type="enterprise_risk",
                entity_id=erm["id"],
                payload={
                    "title": erm["title"],
                    "category": erm["category"],
                    "source_module": "sentinel",
                    "source_risk_id": entity_id,
                    "reason": f"Sentinel breach '{breach_title}' marked {closed_status}",
                },
                user_id=user_id,
            )
    except Exception as e:
        log.warning("breach_resolved_closes_linked_risks error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ERM RISK CLOSED → NOTIFY APPETITE STATUS CHANGE
# ═══════════════════════════════════════════════════════════════════════════════

@on("erm.risk.closed")
def erm_risk_closed_checks_appetite(event_type, source_module, entity_type,
                                     entity_id, payload, user_id, **kw):
    """
    When any ERM risk is closed (manually or via breach resolution):
    - Check if the risk's category is now back within appetite threshold
    - If it was previously breached and is now within bounds, notify admins
    """
    db = get_db()
    try:
        category = payload.get("category", "")
        if not category:
            return

        appetite = db.execute(
            "SELECT max_score FROM erm_risk_appetite WHERE category=%s",
            (category,),
        ).fetchone()
        if not appetite:
            return

        max_score = appetite["max_score"]
        current_max = db.execute(
            "SELECT MAX(COALESCE(rrr, likelihood*impact)) FROM erm_enterprise_risks "
            "WHERE category=%s AND status NOT IN ('closed','accepted')",
            (category,),
        ).fetchone()[0] or 0

        if current_max <= max_score:
            _notify_admins(
                db, "erm",
                f"Appetite Restored: {category.capitalize()}",
                f"Risk category '{category}' is now within appetite threshold "
                f"(current max score: {current_max}, threshold: {max_score}). "
                f"No further immediate action required.",
                "/erm/appetite",
            )
            log.info(
                "ERM appetite restored for '%s': score %d ≤ threshold %d",
                category, current_max, max_score,
            )

        # ── XM-CLOSE-2a: Close BCM incidents escalated to this ERM risk ───
        bcm_links = db.execute(
            "SELECT source_id FROM cross_module_links "
            "WHERE source_module='bcm' AND source_type='incident' "
            "AND target_module='erm' AND target_type='enterprise_risk' "
            "AND target_id=%s",
            (entity_id,),
        ).fetchall()
        for link in bcm_links:
            db.execute(
                "UPDATE bcm_incidents SET status='resolved', resolved_at=CURRENT_TIMESTAMP "
                "WHERE id=%s AND status NOT IN ('resolved','closed')",
                (link["source_id"],),
            )
            log.info("XM-CLOSE-2: ERM risk %d closed -> closed BCM incident #%d",
                     entity_id, link["source_id"])

        # ── XM-CLOSE-2b: Close ORM events elevated to this ERM risk ───────
        db.execute(
            "UPDATE orm_events SET status='resolved', resolved_at=CURRENT_TIMESTAMP, "
            "updated_at=CURRENT_TIMESTAMP WHERE erm_risk_id=%s "
            "AND status NOT IN ('resolved','closed')",
            (entity_id,),
        )
        orm_links = db.execute(
            "SELECT source_id FROM cross_module_links "
            "WHERE source_module='orm' AND source_type='event' "
            "AND target_module='erm' AND target_type='enterprise_risk' "
            "AND target_id=%s",
            (entity_id,),
        ).fetchall()
        for link in orm_links:
            db.execute(
                "UPDATE orm_events SET status='resolved', resolved_at=CURRENT_TIMESTAMP, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=%s AND status NOT IN ('resolved','closed')",
                (link["source_id"],),
            )
            log.info("XM-CLOSE-2: ERM risk %d closed -> closed ORM event #%d",
                     entity_id, link["source_id"])

        db.commit()
    except Exception as e:
        log.warning("erm_risk_closed_checks_appetite error: %s", e)
    finally:
        db.close()


@on("bcm.plan.deactivated")
def bcm_plan_deactivated_handler(event_type, source_module, entity_type,
                                  entity_id, payload, user_id, **kw):
    """
    GAP-6: BCM_PLAN_DEACTIVATED was emitted but had no handlers.
    Notify the incident commander and admins that a BCM plan has stood down,
    and create a task to complete the post-activation review.
    """
    db = get_db()
    try:
        title = payload.get("title", f"Plan #{entity_id}")
        reason = payload.get("reason", "Stand-down authorised")

        _insert_task(
            db,
            title=f"Post-Activation Review: {title}",
            description=(
                f"BCM plan '{title}' has been deactivated. "
                f"Reason: {reason}. "
                f"Complete a post-activation review: document lessons learned, "
                f"update the plan, and confirm all response actions were closed."
            ),
            module="bcm", entity_type="plan", entity_id=entity_id,
            priority="medium", user_id=user_id,
        )

        _notify_admins(
            db, "bcm",
            f"BCM Plan Stood Down: {title}",
            f"Plan deactivated. Reason: {reason}. Post-activation review task created.",
            "/bcm/",
        )

        # Notify the user who deactivated (commander) if different from admins
        if user_id:
            _notify(
                db, user_id, "bcm",
                f"Plan Deactivated: {title}",
                f"You have deactivated '{title}'. A post-activation review task has been created.",
                "/bcm/",
            )

        db.commit()
        log.info("GAP-6: BCM plan %d deactivated — post-review task created", entity_id)
    except Exception as e:
        log.warning("bcm_plan_deactivated_handler error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# XM-ERM-SENTINEL: ERM DATA BREACH RISK → SENTINEL PRIVACY BREACH
# ═══════════════════════════════════════════════════════════════════════════════

_BREACH_CATEGORIES = {
    "data_breach", "privacy_breach", "privacy",
    "compliance_&_legal_risk", "technology_risk",
}
_BREACH_TITLE_KEYWORDS = {"data breach", "privacy breach", "pii exposure", "data leak"}


@on("erm.risk.identified")
def erm_data_breach_risk_creates_sentinel_breach(event_type, source_module, entity_type,
                                                  entity_id, payload, user_id, **kw):
    """
    XM-ERM-SEN: When an ERM risk with a privacy/data-breach category is created,
    auto-create a Sentinel breach notification record so the 72h regulatory clock
    starts immediately. Idempotent: skipped if a sentinel link already exists.
    """
    category = (payload.get("category") or "").lower().replace(" ", "_")
    title_lower = (payload.get("title") or "").lower()
    has_breach_title = any(kw in title_lower for kw in _BREACH_TITLE_KEYWORDS)
    if category not in _BREACH_CATEGORIES and not has_breach_title:
        return

    db = get_db()
    try:
        erm_risk_id = payload.get("erm_risk_id") or entity_id

        # Idempotency: skip if a sentinel breach was already linked to this ERM risk
        existing = db.execute(
            "SELECT id FROM cross_module_links "
            "WHERE source_module='erm' AND source_type='enterprise_risk' "
            "AND source_id=%s AND target_module='sentinel' AND target_type='breach'",
            (erm_risk_id,),
        ).fetchone()
        if existing:
            return

        title = payload.get("title", f"ERM Data Breach Risk #{erm_risk_id}")
        severity = (payload.get("severity") or "high").lower()
        # Map ERM likelihood/impact score to breach severity
        score = (payload.get("likelihood") or 3) * (payload.get("impact") or 3)
        if score >= 20:
            sev = "critical"
        elif score >= 12:
            sev = "high"
        elif score >= 6:
            sev = "medium"
        else:
            sev = severity

        from modules.sentinel.data_service import create_breach
        from core.timeutils import utcnow

        breach_data = {
            "title": title,
            "breach_type": "unauthorized_access",
            "severity": sev,
            "status": "open",
            "discovery_date": utcnow().strftime("%Y-%m-%d"),
            "description": (
                f"Auto-created from ERM risk #{erm_risk_id} (category: {category}). "
                f"Review and complete breach details in Sentinel."
            ),
            "notification_required": 1,
        }
        breach_id = create_breach(breach_data)

        create_cross_module_link(
            "erm", "enterprise_risk", erm_risk_id,
            "sentinel", "breach", breach_id,
            relationship="triggers", user_id=user_id, db=db,
        )
        db.commit()

        # Fire SENTINEL_BREACH_CONFIRMED so downstream handlers create
        # regulatory obligations, risk register entry, tasks, and evidence.
        from modules.sentinel.data_service import get_active_jurisdictions
        emit(
            SENTINEL_BREACH_CONFIRMED,
            source_module="sentinel",
            entity_type="breach",
            entity_id=breach_id,
            payload={
                "title": title,
                "severity": sev,
                "category": category,
                "affected_records": 0,
                "description": breach_data["description"],
                "regulation": settings.DEFAULT_REGULATION,
                "active_jurisdictions": [
                    j["jurisdiction_key"] for j in get_active_jurisdictions()
                ],
            },
            user_id=user_id,
        )

        _notify_admins(
            db, "sentinel",
            f"Privacy Breach Opened: {title}",
            f"ERM risk '{title}' (category: {category}) automatically created a "
            f"Sentinel breach record. The 72h notification clock has started. "
            f"Review and complete the breach details in Sentinel.",
            "/sentinel/breaches",
        )
        db.commit()
        log.info("XM-ERM-SEN: ERM risk %d (category=%s) → Sentinel breach #%d",
                 erm_risk_id, category, breach_id)
        notify_connectors(
            f"[ThemisIQ] DATA BREACH RISK: {title} (category: {category}) — "
            f"Sentinel breach #{breach_id} created. 72h notification clock started. "
            f"Review: /sentinel/#breaches"
        )
    except Exception as e:
        log.warning("erm_data_breach_risk_creates_sentinel_breach error: %s", e)
    finally:
        db.close()


@on("erm.appetite.breached")
def appetite_breach_notify(event_type, source_module, entity_type,
                            entity_id, payload, user_id, **kw):
    """Appetite breach event → notify risk owners and admins."""
    db = get_db()
    try:
        category = payload.get("category", "unknown")
        current_score = payload.get("current_score", 0)
        max_score = payload.get("max_score", 0)
        # Notify owners of risks in that category
        rows = db.execute(
            "SELECT DISTINCT owner_id FROM erm_enterprise_risks "
            "WHERE category=%s AND status NOT IN ('closed','accepted') AND owner_id IS NOT NULL",
            (category,)
        ).fetchall()
        for row in rows:
            _notify(
                db, row[0], "erm",
                f"Risk Appetite Breach: {category}",
                f"Appetite threshold exceeded in {category} category. "
                f"Current max score: {current_score} vs threshold: {max_score}. "
                f"Review your treatment plans.",
                "/erm/appetite",
            )
        _notify_admins(
            db, "erm",
            f"Appetite Breach: {category.capitalize()}",
            f"Score {current_score} exceeds {max_score} threshold. "
            f"Risk owners notified.",
            "/erm/appetite",
        )
        db.commit()
        log.info("ERM appetite breach in '%s': notified %d owner(s)", category, len(rows))
        notify_connectors(
            f"[ThemisIQ] RISK APPETITE BREACH: {category.capitalize()} — "
            f"score {current_score} exceeds threshold {max_score}. "
            f"Review: /erm/appetite"
        )
    except Exception as e:
        log.warning("appetite_breach_notify error: %s", e)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-TRIGGER WORKFLOWS FROM MODULE EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

# Maps (trigger_module, trigger_action) on workflow definitions to event types.
# When any of these events fires, installed definitions with matching trigger
# fields will have a workflow instance started automatically.
_WORKFLOW_TRIGGER_MAP = {
    "aria.policy.published":      ("aria",     "policy.created"),
    "aria.policy.updated":        ("aria",     "policy.updated"),
    "grid.audit.completed":       ("grid",     "audit.findings_resolved"),
    "bcm.incident.declared":      ("bcm",      "incident.declared"),
    "sentinel.breach.confirmed":  ("sentinel", "breach.confirmed"),
    "erm.risk.escalated":         ("platform", "risk.escalated"),
    "erm.risk.identified":        ("platform", "risk.escalated"),
}


def _auto_trigger_workflows(db, event_type: str, source_module: str,
                            entity_type: str, entity_id: int, user_id: int) -> None:
    """Start workflow instances for any active definitions that match this event."""
    trigger = _WORKFLOW_TRIGGER_MAP.get(event_type)
    if not trigger:
        return
    trigger_module, trigger_action = trigger
    try:
        defns = db.execute(
            "SELECT id, name, steps_json FROM workflow_definitions "
            "WHERE is_active = 1 AND trigger_module = %s AND trigger_action = %s",
            (trigger_module, trigger_action)
        ).fetchall()
        if not defns:
            return

        from database import insert_returning_id
        import json as _json

        for defn in defns:
            iid = insert_returning_id(
                db,
                "INSERT INTO workflow_instances "
                "(definition_id, entity_module, entity_type, entity_id, started_by) "
                "VALUES (%s,%s,%s,%s,%s)",
                (defn["id"], source_module, entity_type, entity_id, user_id)
            )
            db.commit()
            steps = _json.loads(defn["steps_json"]) if defn["steps_json"] else []
            if steps:
                from modules.launcher.routes_workflows import _create_step_action
                _create_step_action(db, iid, 0, steps[0], defn["name"])
            log.info(
                "Auto-triggered workflow '%s' (instance=%d) for %s/%s/%d",
                defn["name"], iid, source_module, entity_type, entity_id
            )
    except Exception as exc:
        log.warning("_auto_trigger_workflows failed for %s: %s", event_type, exc)


@on(ARIA_POLICY_PUBLISHED)
def workflow_trigger_on_aria_policy(event_type, source_module, entity_type,
                                    entity_id, payload, user_id, **kw):
    db = get_db()
    try:
        _auto_trigger_workflows(db, event_type, source_module, entity_type, entity_id, user_id)
    finally:
        db.close()


@on(BCM_INCIDENT_DECLARED)
def workflow_trigger_on_bcm_incident(event_type, source_module, entity_type,
                                     entity_id, payload, user_id, **kw):
    db = get_db()
    try:
        _auto_trigger_workflows(db, event_type, source_module, entity_type, entity_id, user_id)
    finally:
        db.close()


@on(SENTINEL_BREACH_CONFIRMED)
def workflow_trigger_on_sentinel_breach(event_type, source_module, entity_type,
                                        entity_id, payload, user_id, **kw):
    db = get_db()
    try:
        _auto_trigger_workflows(db, event_type, source_module, entity_type, entity_id, user_id)
    finally:
        db.close()


@on(ERM_RISK_ESCALATED)
def workflow_trigger_on_erm_risk(event_type, source_module, entity_type,
                                 entity_id, payload, user_id, **kw):
    db = get_db()
    try:
        _auto_trigger_workflows(db, event_type, source_module, entity_type, entity_id, user_id)
    finally:
        db.close()


@on(GRID_AUDIT_COMPLETED)
def workflow_trigger_on_grid_audit(event_type, source_module, entity_type,
                                   entity_id, payload, user_id, **kw):
    db = get_db()
    try:
        _auto_trigger_workflows(db, event_type, source_module, entity_type, entity_id, user_id)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# T1.3: CONTROL EFFECTIVENESS RECOMPUTE TRIGGERS
# ═══════════════════════════════════════════════════════════════════════════════

@on("grid.audit.completed")
def recompute_effectiveness_on_audit(event_type, source_module, entity_type,
                                     entity_id, payload, user_id, **kw):
    """When a GRID audit completes, recompute scores for controls linked to it."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT DISTINCT gc.canonical_control_id FROM grid_controls gc "
            "WHERE gc.audit_id = %s AND gc.canonical_control_id IS NOT NULL",
            (entity_id,),
        ).fetchall()
        if not rows:
            return
        from modules.governance.effectiveness import recompute_controls_by_ids
        cids = [r[0] for r in rows]
        count = recompute_controls_by_ids(db, cids)
        db.commit()
        log.info("T1.3: audit %d completed -> recomputed %d control score(s)", entity_id, count)
    except Exception as exc:
        log.warning("recompute_effectiveness_on_audit error: %s", exc)
    finally:
        db.close()


@on("control.status_changed")
def recompute_effectiveness_on_status_change(event_type, source_module, entity_type,
                                              entity_id, payload, user_id, **kw):
    """When a control status changes, recompute its canonical control score if linked."""
    db = get_db()
    try:
        cid = payload.get("canonical_control_id")
        if not cid:
            # Try to find via aria_controls or grid_controls
            for tbl in ("aria_controls", "grid_controls", "orm_rcsa_controls"):
                try:
                    row = db.execute(
                        f"SELECT canonical_control_id FROM {tbl} WHERE id=%s",
                        (entity_id,),
                    ).fetchone()
                    if row and row[0]:
                        cid = row[0]
                        break
                except Exception:
                    continue
        if not cid:
            return
        from modules.governance.effectiveness import recompute_control
        recompute_control(db, int(cid))
        db.commit()
        log.info("T1.3: control status change -> recomputed score for canonical_control %s", cid)
    except Exception as exc:
        log.warning("recompute_effectiveness_on_status_change error: %s", exc)
    finally:
        db.close()


@on("orm.event.logged")
def recompute_effectiveness_on_orm_event(event_type, source_module, entity_type,
                                          entity_id, payload, user_id, **kw):
    """When a high/critical ORM event is logged, recompute controls linked to its risk."""
    severity = (payload.get("severity") or "").lower()
    if severity not in ("high", "critical"):
        return
    db = get_db()
    try:
        event_row = db.execute(
            "SELECT erm_risk_id FROM orm_events WHERE id=%s", (entity_id,)
        ).fetchone()
        if not event_row or not event_row[0]:
            return
        risk_id = event_row[0]
        rows = db.execute(
            "SELECT DISTINCT control_id FROM risk_controls WHERE risk_id=%s",
            (risk_id,),
        ).fetchall()
        if not rows:
            return
        from modules.governance.effectiveness import recompute_controls_by_ids
        cids = [r[0] for r in rows if r[0]]
        count = recompute_controls_by_ids(db, cids)
        db.commit()
        log.info(
            "T1.3: ORM %s event %d -> risk %d -> recomputed %d control score(s)",
            severity, entity_id, risk_id, count,
        )
    except Exception as exc:
        log.warning("recompute_effectiveness_on_orm_event error: %s", exc)
    finally:
        db.close()
