"""
Guided tours and the getting-started checklist for the Themis help bubble.

Tours are written here, not generated: no AI is involved and nothing about the page leaves the browser. A tour is
offered only when its area is open to the person, using the same rules as the shell's navigation (core/shell_context).
Each step names a path, a CSS selector on that page, and the text to show. Optional steps are ones some roles do not
see (a link gated by a finer capability); the browser skips them when the element is absent.
"""
from core import ai_rollout
from core.rbac import has_capability, user_modules


def _step(path, selector, title, body, optional=False):
    return {"path": path, "selector": selector, "title": title, "body": body, "optional": optional}


def _nav(path, href, title, body, optional=False):
    return _step(path, f'.nav-item[href="{href}"]', title, body, optional)


TOURS = [
    {
        "id": "welcome", "area": None, "title": "Welcome to ThemisIQ",
        "summary": "Find your way around: modules, search, notifications and your work.",
        "steps": [
            _step("/", ".icon-sidebar", "Your modules",
                  "Each icon opens a module you have access to. Hover over the rail to see their names."),
            _step("/", "#railPin", "Keep the names showing",
                  "Pin the rail to keep module names visible. Your choice is remembered.", optional=True),
            _step("/", "#globalSearch", "Search everything",
                  "Search across every module at once: risks, controls, policies, audits, vendors and more. "
                  "Press Ctrl+K from anywhere."),
            _step("/", "#notifBtn", "Notifications",
                  "Assignments, approvals waiting for you and deadline alerts arrive here."),
            _step("/my-work", "#myWorkQ", "My Work",
                  "Everything assigned to you across modules, in one list. Search and filter it here."),
            _step("/my-work", ".trainer-icon", "Ask Themis",
                  "Open Themis any time to ask how to do something, or to take another tour."),
        ],
    },
    {
        "id": "governance", "area": "aria", "title": "Governance (ARIA)",
        "summary": "Standards, control mapping and policies.",
        "steps": [
            _nav("/aria/", "/aria/frameworks", "Standards and controls",
                 "Load the standards you follow and manage their controls."),
            _nav("/aria/", "/aria/mapping", "One control, many standards",
                 "Match equivalent controls across standards once. A different reviewer approves each match."),
            _nav("/aria/", "/aria/documents", "Policies and documents",
                 "Policies with full version history. An author can never approve their own version."),
            _nav("/aria/", "/aria/ai-generator", "Draft with ARIA",
                 "Write a first draft of a policy or procedure for a control, then edit, preview and send it "
                 "for approval.", optional=True),
            _nav("/aria/", "/aria/ask", "Ask ARIA",
                 "Ask a question and get an answer from your approved policies and controls, with the source.",
                 optional=True),
        ],
    },
    {
        "id": "audit", "area": "grid", "title": "Audit (GRID)",
        "summary": "Audits, controls, evidence, findings and reports.",
        "steps": [
            _nav("/grid/", "/grid/audits", "Audits",
                 "Plan an audit with its scope, objective and criteria, for one standard or several at once."),
            _nav("/grid/", "/grid/controls", "Controls to test",
                 "The controls in scope, with their status and the evidence behind them."),
            _nav("/grid/", "/grid/evidence", "Evidence",
                 "Attach proof to the control it supports. The same file can serve several audits."),
            _nav("/grid/", "/grid/findings", "Findings",
                 "Record what failed, plan the corrective action and track it to closure."),
            _nav("/grid/", "/grid/reports", "Reports",
                 "Audit reports and compliance scores, ready to share."),
        ],
    },
    {
        "id": "privacy", "area": "sentinel", "title": "Privacy (Sentinel)",
        "summary": "Processing records, DPIAs, breaches and subject requests.",
        "steps": [
            _nav("/sentinel/", "/sentinel/ropa", "Records of processing",
                 "Each processing activity with its purpose, legal basis, data and retention."),
            _nav("/sentinel/", "/sentinel/dpia", "DPIAs",
                 "Impact assessments for high-risk processing, with a first draft you review."),
            _nav("/sentinel/", "/sentinel/breaches", "Breaches",
                 "Log a breach. Each jurisdiction it touches gets its own deadline and decision."),
            _nav("/sentinel/", "/sentinel/dsr", "Subject requests",
                 "Requests from individuals, each with its legal deadline."),
        ],
    },
    {
        "id": "resilience", "area": "bcm", "title": "Resilience (BCM)",
        "summary": "Impact analysis, plans, exercises and incidents.",
        "steps": [
            _nav("/bcm/", "/bcm/bia", "Business impact analysis",
                 "Your critical processes, their recovery objectives and what they depend on."),
            _nav("/bcm/", "/bcm/plans", "Continuity plans",
                 "Plans for each process, reviewed and approved, ready when they are needed."),
            _nav("/bcm/", "/bcm/exercises", "Exercises",
                 "Rehearse your plans from a scenario and record what you learned."),
            _nav("/bcm/", "/bcm/incidents", "Incidents",
                 "Run an incident: actions, decisions, updates and alerts that move on if no one responds."),
        ],
    },
    {
        "id": "enterprise-risk", "area": "erm", "title": "Enterprise risk (ERM)",
        "summary": "The register, appetite, indicators and scenarios.",
        "steps": [
            _nav("/erm/", "/erm/register", "Risk register",
                 "Enterprise risks with owners, scores, treatments and their history."),
            _nav("/erm/", "/erm/appetite", "Risk appetite",
                 "How much risk you accept in each area. Risks above it are flagged."),
            _nav("/erm/", "/erm/indicators", "Key risk indicators",
                 "Measures with thresholds that warn you when a risk is moving."),
            _nav("/erm/", "/erm/scenario-studio", "Scenario Studio",
                 "Test a what-if against your baseline and capture a board pack.", optional=True),
        ],
    },
    {
        "id": "operations-risk", "area": "orm", "title": "Operations risk (ORM)",
        "summary": "Events, self assessments and indicators.",
        "steps": [
            _nav("/orm/", "/orm/events", "Events",
                 "Log losses and near misses, then follow them to the root cause."),
            _nav("/orm/", "/orm/assessment", "Self assessment",
                 "Teams rate their own risks and controls, with actions where needed."),
            _nav("/orm/", "/orm/indicators", "Indicators",
                 "Operational measures with their history and thresholds."),
        ],
    },
    {
        "id": "ai-governance", "area": "ai_governance", "title": "AI Governance",
        "summary": "Register AI uses, review them and keep watching.",
        "steps": [
            _nav("/ai-governance/", "/ai-governance/register", "Register an AI use",
                 "Describe an AI use in a short guided form. It stays a draft until you submit it.",
                 optional=True),
            _nav("/ai-governance/", "/ai-governance/systems", "AI systems",
                 "Every AI use your organisation has accepted, with its tier and status."),
            _nav("/ai-governance/", "/ai-governance/review", "Review requests",
                 "New requests waiting for a reviewer to accept them into the inventory.", optional=True),
            _nav("/ai-governance/", "/ai-governance/decisions", "Decisions",
                 "Someone other than the requester decides, on a frozen record of what they were shown.",
                 optional=True),
            _nav("/ai-governance/", "/ai-governance/monitoring", "Monitoring",
                 "Evaluations and oversight that keep an approved AI use in check."),
        ],
    },
    {
        "id": "administration", "area": "admin", "title": "Administration",
        "summary": "People, standards and the audit log.",
        "steps": [
            _nav("/admin/users", "/admin/users", "People",
                 "Invite people and give each the specialist role for their work."),
            _nav("/admin/users", "/admin/frameworks", "Standards",
                 "Choose which standards are active for your organisation."),
            _nav("/admin/users", "/admin/logs", "Audit log",
                 "A record of who did what, for your organisation.", optional=True),
        ],
    },
]


def open_areas(user) -> set:
    """The tour areas this person can open, following core/shell_context."""
    areas = set(user_modules(user))
    if has_capability(user, "ai_use.view") and (ai_rollout.is_enabled(user.get("org_id"))
                                               or user.get("is_super_admin")):
        areas.add("ai_governance")
    if has_capability(user, "platform.manage_users"):
        areas.add("admin")
    return areas


def tours_for(user) -> list:
    areas = open_areas(user)
    return [t for t in TOURS if t["area"] is None or t["area"] in areas]


def checklist_for(user, mfa_enabled: bool) -> list:
    """Getting-started items. Tour items are ticked in the browser, where finished tours are remembered."""
    items = [{"id": "mfa", "label": "Turn on two-step sign-in", "done": mfa_enabled,
              "href": "/mfa/setup"}]
    items += [{"id": f"tour:{t['id']}", "label": f"Take the tour: {t['title']}", "tour": t["id"]}
              for t in tours_for(user)]
    return items
