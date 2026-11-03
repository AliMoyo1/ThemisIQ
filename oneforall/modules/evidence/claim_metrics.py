"""The Vault's three claim figures as registered metrics (plan 23, P1).

Built from the Vault's own coverage count (`coverage_for`), so the figure and the Vault page cannot count different rows:
of every record the Vault measures and the viewer may open, the share with a live link, with current proof and with
accepted proof. A link is not proof, and only a reviewer other than the person who attached the file makes it accepted.
"""
from core import metric_registry as registry, metric_state as ms
from core.best_effort import swallowed
from core.report_kit.identity import pct

KEYS = (("vault.linked", "linked"), ("vault.current_proof", "current"), ("vault.accepted", "accepted"))


def metrics(db, user) -> dict:
    from core.auth import licensed_modules_for
    from modules.evidence.routes import coverage_for
    try:
        coverage = coverage_for(user)
        # A person's own modules already follow the licence; a whole-organization build (a super administrator actor,
        # as the group figures use) does not, so it is limited here: an unlicensed module adds nothing.
        licensed = licensed_modules_for(db, user.get("org_id")) if user.get("is_super_admin") else None
    except Exception:
        swallowed("Vault claim figures")
        return {key: registry.build(key, ms.unavailable) for key, _ in KEYS}
    rows = [data for module, data in coverage.items() if licensed is None or module in licensed]
    total = sum(data["total"] for data in rows)
    out = {}
    for key, part in KEYS:
        if not total:
            out[key] = registry.build(key, ms.not_measured, "No record that can carry proof exists yet.")
            continue
        done = sum(data[part] for data in rows)
        out[key] = registry.build(key, ms.measured, pct(done, total),
                                  detail={"unit": "percent", "claims": done, "total": total})
    return out
