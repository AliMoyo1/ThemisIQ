"""
The definition of every number a dashboard shows (plans/2026-10-governance-rework/04 section 2).

A card is built from a metric that is registered here, so that the words on the card, the page that explains it
(/metrics) and the list behind it cannot drift apart. Each definition says what the number means in plain words, which
rows are eligible, what a percentage is a percentage of, the window, who sees what, how it is refreshed, what is left out
and where the rows are listed.

`fields(key)` returns the pieces a `core.metric_state` metric carries (label, definition, denominator, window, drilldown),
so a builder writes `ms.measured(key, **registry.fields(key), value=...)` and never restates a definition.
"""
from dataclasses import asdict, dataclass

# Control statuses in ARIA: Not Started, In Progress, Draft, Under Review, Approved, Implemented, Needs Update.
# "Approved" means the control's documentation is approved. It is not implementation, so it is never counted as it.
CONTROL_IMPLEMENTED = "status = 'Implemented'"
# One condition per meaning, so that a dashboard card and a report figure with the same name cannot count different rows.
BREACH_ACTIVE = "status NOT IN ('closed', 'resolved')"
INCIDENT_ACTIVE = "status NOT IN ('resolved', 'closed')"
EXERCISE_COMPLETED = "status IN ('completed', 'completed_awaiting_review', 'closed')"


@dataclass(frozen=True)
class Definition:
    key: str
    label: str
    module: str               # the licensed module whose access governs who may see it; "" for the platform
    owner: str                # the code that produces it
    definition: str           # what the number means, in plain words
    eligibility: str          # which rows count
    denominator: "str | None" # what a percentage is of; None for a count
    window: str
    scope: str                # who sees which rows
    refresh: str
    exclusions: str
    drilldown: "str | None"   # the page that opens the rows
    exact: bool = True        # the page lists exactly the rows that are counted (False: it opens the module, not the rows)
    ownership: str = "business_unit_or_organization"  # row owner, distinct from who may view the metric

    def as_dict(self) -> dict:
        return asdict(self)


_READ = "Read when the page opens, and again every five minutes while it stays open."
_VISIBLE = "Only rows the viewer may open in the owning module: their business units, or organization wide."
_NOW = "Now: every row as it stands when the page is read."

REGISTRY: dict = {}


def _add(key, label, module, owner, definition, eligibility, *, denominator=None, window=_NOW, scope=_VISIBLE,
         refresh=_READ, exclusions="None.", drilldown=None, exact=True,
         ownership="business_unit_or_organization"):
    REGISTRY[key] = Definition(key, label, module, owner, definition, eligibility, denominator, window, scope, refresh,
                               exclusions, drilldown, exact, ownership)


# ── Command Centre ──────────────────────────────────────────────────────────

_CC = "modules/launcher/command_metrics.py"
_add("cc.controls_implemented", "Controls implemented", "aria", _CC,
     "The share of controls whose status is Implemented. A control that is only Approved (its documentation is approved) "
     "is not implemented and is not counted.",
     "Every control the viewer may open.", denominator="All controls the viewer may open.", drilldown="/aria/", exact=False,
     ownership="organization")
_add("cc.active_frameworks", "Active frameworks", "aria", _CC,
     "Frameworks that are switched on for the organization.", "Frameworks marked active.", drilldown="/projects",
     ownership="organization")
_add("cc.overdue_actions", "Overdue actions", "", _CC,
     "Tasks past their due date that are not done, plus service clocks that are active and breached.",
     "Tasks with a due date in the past and a status other than done; active service clocks marked breached.",
     drilldown="/my-work?section=overdue", exact=False, ownership="mixed_sources")
_add("cc.critical_high_risks", "Critical and high risks", "erm", _CC,
     "Enterprise risks rated critical or high that are not closed or accepted.",
     "Enterprise risks the viewer may open, rated critical or high, with a status other than closed or accepted.",
     drilldown="/erm/")
_add("cc.open_breaches", "Open breaches", "sentinel", _CC,
     "Personal data breaches rated high or critical that are not closed or resolved.",
     "Breaches the viewer may open, rated high or critical, still open.", drilldown="/sentinel/breaches")
_add("cc.appetite_breaches", "Appetite breaches", "erm", _CC,
     "Risk categories whose worst open risk scores above the category's limit.",
     "Categories that have a limit set, judged over the enterprise risks the viewer may open.",
     denominator="Categories that have a limit set.", drilldown="/erm/", exact=False,
     exclusions="A category with no limit is not judged. Without any limit the number is not measured.",
     ownership="mixed_sources")
_add("cc.orm_open_events", "Open operational events", "orm", _CC,
     "Operational events that are open or under investigation and were created in the last 30 days.",
     "Events the viewer may open.", window="The last 30 days, by the day the event was created.", drilldown="/orm/")
_add("cc.bcm_active_incidents", "Active incidents", "bcm", _CC,
     "Continuity incidents that are not resolved or closed.", "Incidents the viewer may open.", drilldown="/bcm/incidents")
_add("cc.grid_open_audit_controls", "Audit controls not yet compliant", "grid", _CC,
     "Controls under audit whose status is not compliant, not applicable or closed. These are audit controls, not findings: "
     "findings are the non-conformances an audit raises.",
     "Audit controls of audits the viewer may open.", drilldown="/grid/controls", exact=False)
_add("cc.upcoming_reviews", "Reviews due within 30 days", "", _CC,
     "Enterprise risks whose review date falls within 30 days, plus continuity plans last reviewed more than 335 days ago.",
     "Risks and plans the viewer may open that are not closed or accepted.",
     window="The next 30 days; for plans, a last review older than 335 days.", drilldown=None, exact=False,
     ownership="mixed_sources")
_add("cc.evidence_files", "Evidence files", "", _CC,
     "Files held in the Evidence Vault that are in the library: current and expired files. Archived files and files "
     "replaced by a newer version are not counted.",
     "Files the viewer may open.", drilldown="/evidence/")
_add("cc.evidence_expiring", "Evidence expiring within 30 days", "", _CC,
     "Current files whose expiry date falls within the next 30 days.", "Current files the viewer may open.",
     window="The next 30 days.", drilldown="/evidence/")
_add("cc.sla_on_time", "Service clocks resolved on time", "", _CC,
     "Of the service clocks that have ended, the share that ended without a breach.",
     "Service clocks the viewer may open that are resolved or breached.",
     denominator="Service clocks that have ended (met or breached). Active clocks are not in it.",
     exclusions="Active clocks that have not ended. With none ended the number is not measured.", drilldown=None, exact=False)
_add("cc.workflows_active", "Active workflows", "", _CC,
     "Workflow instances that are running.", "Instances the viewer may open.", drilldown="/workflows")
_add("cc.open_risks", "Open risks by level", "", _CC,
     "Open enterprise and platform risks, by rating level.",
     "Risks the viewer may open that are not closed.", drilldown="/risk-register", ownership="mixed_sources")
_add("cc.module_health", "Share of records in their good state", "", _CC,
     "For one module, the share of its main records that are in the good state of that module: controls implemented, "
     "audits completed, plans approved, breaches closed, risks closed, events resolved.",
     "The module's main records the viewer may open.",
     denominator="All of that module's main records the viewer may open.",
     exclusions="A module with nothing recorded is not measured. It is not shown as 100 per cent.", drilldown=None, exact=False,
     ownership="mixed_sources")

# ── Business continuity dashboard ───────────────────────────────────────────

_BCM = "modules/bcm/dashboard_metrics.py"
_add("bcm.bia_with_plan", "Analyses with a continuity plan", "bcm", _BCM,
     "The share of business impact analyses that have at least one continuity plan linked to them.",
     "Analyses the viewer may open.", denominator="All analyses the viewer may open.", drilldown="/bcm/bia")
_add("bcm.plans", "Continuity plans", "bcm", _BCM, "Continuity plans recorded.", "Plans the viewer may open.",
     drilldown="/bcm/plans")
_add("bcm.active_incidents", "Open incidents", "bcm", _BCM, "Incidents that are not resolved or closed.",
     "Incidents the viewer may open.", drilldown="/bcm/incidents")
_add("bcm.exercises_completed", "Exercises completed", "bcm", _BCM,
     "The share of exercises that are completed, awaiting review or closed.", "Exercises the viewer may open.",
     denominator="All exercises the viewer may open, including cancelled ones.",
     exclusions="With no exercise recorded the number is not measured.", drilldown="/bcm/exercises")
_add("bcm.open_risks", "Open continuity risks", "bcm", _BCM, "Continuity risks with the status open.",
     "Continuity risks the viewer may open.", drilldown="/bcm/risks", ownership="organization")
_add("bcm.risk_levels", "Continuity risks by level", "bcm", _BCM,
     "Continuity risks that are not closed, banded by score: critical 20 and over, high 12 to 19, medium 6 to 11, low under 6.",
     "Continuity risks the viewer may open.", drilldown="/bcm/risks", ownership="organization")

# ── Privacy dashboard ───────────────────────────────────────────────────────

_SEN = "modules/sentinel/dashboard_metrics.py"
_add("sentinel.ropa_records", "Processing records", "sentinel", _SEN,
     "Records in the register of processing activities.", "Records the viewer may open.", drilldown="/sentinel/ropa")
_add("sentinel.ropa_coverage", "Business processes with a processing record", "sentinel", _SEN,
     "The share of business processes that have at least one processing record connected to them by a confirmed link.",
     "Active business processes the viewer may open.",
     denominator="Active business processes the viewer may open, recorded in Governance.",
     exclusions="Proposed links are not counted. Without any business process recorded the number is not measured.",
     drilldown="/sentinel/ropa", ownership="mixed_sources")
_add("sentinel.dpia_active", "Impact assessments in progress", "sentinel", _SEN,
     "Privacy impact assessments that are not completed or closed.", "Assessments the viewer may open.",
     drilldown="/sentinel/dpia")
_add("sentinel.dsr_open", "Data subject requests waiting", "sentinel", _SEN,
     "Data subject requests that are open, new or in progress.", "Requests the viewer may open.",
     drilldown="/sentinel/dsr")
_add("sentinel.breaches_active", "Open breaches", "sentinel", _SEN,
     "Personal data breaches that are not closed or resolved.", "Breaches the viewer may open.",
     drilldown="/sentinel/breaches")

# ── Evidence Vault ──────────────────────────────────────────────────────────

_VAULT = "modules/evidence/routes.py"
_add("vault.linked", "Claims with a live link", "", _VAULT,
     "Claims (records) that have at least one live evidence link. A link is not proof.",
     "Records of the kind that the viewer may open.", denominator="Records of that kind the viewer may open.",
     drilldown="/evidence/", exact=False, ownership="mixed_sources")
_add("vault.current_proof", "Claims with current proof", "", _VAULT,
     "Claims with a live link to a current file that has not expired and whose link was not returned or rejected.",
     "As above.", denominator="Records of that kind the viewer may open.", drilldown="/evidence/", exact=False,
     ownership="mixed_sources")
_add("vault.accepted", "Claims with accepted proof", "", _VAULT,
     "Claims whose current proof a reviewer other than the person who attached it has accepted.",
     "As above.", denominator="Records of that kind the viewer may open.", drilldown="/evidence/", exact=False,
     ownership="mixed_sources")


# ── Access ──────────────────────────────────────────────────────────────────

def get(key: str) -> Definition:
    return REGISTRY[key]


def fields(key: str) -> dict:
    """What a metric of this key carries from its definition."""
    d = REGISTRY[key]
    return {"label": d.label, "definition": d.definition, "denominator": d.denominator, "window": d.window,
            "drilldown": d.drilldown}


def build(key: str, builder, *args, **kwargs) -> dict:
    """`builder(key, label, ...)` from core.metric_state, with the registered definition filled in."""
    f = fields(key)
    label = f.pop("label")
    return builder(key, label, *args, **{**f, **kwargs})


def visible_to(user: dict) -> list:
    """Definitions of the metrics whose module the viewer may open (the platform's own are for everyone)."""
    from core.rbac import has_capability, user_modules
    modules = set(user_modules(user))
    out = []
    for d in REGISTRY.values():
        if d.module and not (d.module in modules and has_capability(user, f"module.{d.module}.access")):
            continue
        out.append(d)
    return out
