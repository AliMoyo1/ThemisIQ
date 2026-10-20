"""
The first screen of the Command Centre (plans/2026-10-governance-rework/04 section 1): what needs action today, what
changed, what lacks proof, and what can be reported.

Every panel is read on its own, through the person's own scope. A panel that cannot be read says so and the others are
unaffected: it is never shown as an empty panel. Every number links to the list that holds it, and nothing here is a
second store of anything: the panels read My Work, the change signals, the Evidence Vault's coverage and the report
presets that already exist.
"""
import logging

from core import metric_state as ms
from modules.launcher import report_builders as builders
from modules.launcher.my_work_service import get_my_work
from modules.launcher.scoped_metrics import run_scope_key

log = logging.getLogger("oneforall.first_screen")

MODULE_TITLES = {
    "aria": "Governance (ARIA)", "grid": "Audit (GRID)", "bcm": "Continuity (BCM)", "sentinel": "Privacy (Sentinel)",
    "erm": "Enterprise risk (ERM)", "orm": "Operational risk (ORM)",
}
_SECTION_WORDS = {"overdue": "Overdue", "needs_my_action": "Needs you", "due_soon": "Due soon"}
TOP = 3


def _panel(key, title, build) -> dict:
    try:
        got = build()
        got.setdefault("state", "ok")
    except Exception:
        log.warning("First screen: the %s panel could not be read", key, exc_info=True)
        got = {"state": "unavailable", "note": ms.UNAVAILABLE_NOTE}
    got.update(key=key, title=title)
    return got


def _open_changes(db, user) -> list:
    from modules.governance import change_signals
    return change_signals.list_open(db, user, limit=100)


def build(db, user) -> dict:
    work_cache = {}

    def work():
        if "w" not in work_cache:
            work_cache["w"] = get_my_work(user, page_size=100)
        return work_cache["w"]

    def action():
        w = work()
        changes = len(_open_changes(db, user))
        counts = w["counts"]
        # A connected record that changed is shown under "what changed", so it is not counted a second time here.
        needs = max(0, counts.get("needs_my_action", 0) - changes)
        top = []
        for section in ("overdue", "needs_my_action", "due_soon"):
            for item in w["sections"].get(section, []):
                if item["entity_type"] == "change_review":
                    continue
                top.append({"title": item["title"], "link": item["link"], "label": _SECTION_WORDS[section],
                            "due": item.get("due_date")})
        degraded = [s["source"].replace("_", " ") for s in w["source_states"] if s["state"] == "degraded"]
        got = {"counts": {"overdue": counts.get("overdue", 0), "needs_you": needs, "due_soon": counts.get("due_soon", 0),
                          "waiting": counts.get("waiting_on_others", 0)},
               "items": top[:TOP], "link": "/my-work"}
        if degraded:
            got.update(state="partial", note="These sources could not be read just now, so their items may be missing: "
                       + ", ".join(degraded) + ".")
        return got

    def changed():
        w = work()
        signals = _open_changes(db, user)
        items = [{"title": f"{s['target']['title']}: {s['source']['title']} changed", "link": "/governance/changes"}
                 for s in signals[:TOP]]
        return {"counts": {"to_look_at": len(signals), "unread": w["counts"].get("recently_changed", 0)},
                "items": items, "link": "/governance/changes"}

    def proof():
        from modules.evidence.routes import coverage_for
        cov = coverage_for(user)
        modules = []
        for module, data in cov.items():
            if not data["total"]:
                continue
            modules.append({"module": module, "title": MODULE_TITLES.get(module, module), "total": data["total"],
                            "without_proof": data["total"] - data["current"],
                            "waiting_review": data["current"] - data["accepted"], "accepted": data["accepted"]})
        modules.sort(key=lambda m: (-m["without_proof"], m["title"]))
        if not modules:
            return {"state": "not_measured", "note": "No record you may open can carry proof yet, so there is nothing "
                    "to measure.", "counts": None, "items": [], "link": "/evidence/"}
        return {"counts": {"without_proof": sum(m["without_proof"] for m in modules),
                           "waiting_review": sum(m["waiting_review"] for m in modules),
                           "records": sum(m["total"] for m in modules)},
                "items": [{"title": f"{m['title']}: {m['without_proof']} of {m['total']} without current proof",
                           "link": "/evidence/"} for m in modules[:TOP]],
                "link": "/evidence/",
                "definition": "Without proof means no live link to a current file that has not expired or been returned. "
                              "A linked file is not accepted proof until a reviewer accepts it."}

    def reportable():
        reader = builders.Reader(db, user)
        presets = []
        for key, preset in builders.PRESETS.items():
            if key == "preset_case":
                continue
            parts = preset["parts"]
            open_parts = [p for p in parts if any(not reader.hidden(t) for t in builders.READS[p])]
            presets.append({"key": key, "label": preset["label"], "purpose": preset["purpose"],
                            "sections_open": len(open_parts), "sections_total": len(parts)})
        last = db.execute(
            "SELECT rr.id, rr.completed_at, rd.name FROM report_runs rr JOIN report_definitions rd "
            "ON rd.id = rr.definition_id WHERE rr.status = 'completed' AND rr.snapshot_hash IS NOT NULL "
            "AND rr.triggered_by = %s ORDER BY rr.id DESC LIMIT 1", (run_scope_key(user),)).fetchone()
        return {"presets": presets, "link": "/reports",
                "last_run": {"id": last["id"], "name": last["name"], "at": str(last["completed_at"] or "")[:16]}
                if last else None}

    panels = [
        _panel("action", "What needs action today", action),
        _panel("changed", "What changed", changed),
        _panel("proof", "What lacks proof", proof),
        _panel("report", "What can be reported", reportable),
    ]
    return {"panels": panels,
            "sources": [{"source": p["key"], "state": p["state"]} for p in panels],
            "as_of": ms._now()}
