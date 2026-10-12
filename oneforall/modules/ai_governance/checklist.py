"""
AI governance G3: which assessments an AI use needs, why, and where each one stands (requirement rules v1).

The rules read the profile's answers and the tier and say, for each step, one of:

  required        the answers point to it; a decision about the use waits for it
  recommended     worth doing, does not hold a decision
  not_applicable  the answers rule it out
  needs_review    an answer the rule needs is missing; this is never treated as "not applicable"

Every step carries the reasons it got its applicability, the module that owns the work, and the form that opens it. How
far a step has got is read from the owning module's own records (scoped to the viewer); this module copies nothing from
them. A reviewer may mark a required step not applicable with a reason; that is stored with the rule version and the
fingerprint of the facts it was judged against, and shows as out of date when the facts change.

Requirement rules are deterministic and explainable. No model and no web text sets applicability.
"""
import json

from modules.ai_governance import rules

RULE_VERSION = "v1"

APPLICABILITY = ("required", "recommended", "not_applicable", "needs_review")
_PERSONAL = {"personal", "sensitive_personal", "health"}
_SENSITIVE = {"sensitive_personal", "health"}
_VENDOR_PROVIDED = {"vendor_service", "embedded_vendor"}

# key -> (title, owning module, what the form prefills from the profile)
STEPS = {
    "aiia": ("AI impact assessment", "Privacy", ("name", "purpose", "deployment", "autonomy", "data categories", "affected people")),
    "dpia": ("Data protection impact assessment", "Privacy", ("purpose", "data categories", "affected people")),
    "ropa": ("Record of processing activities", "Privacy", ("purpose", "data categories", "provider")),
    "vendor": ("Provider review", "Vendor directory", ("provider",)),
    "aims": ("AI management assessment", "Operations risk", ("name", "purpose")),
    "policy": ("Policy or procedure for this use", "Governance", ("name", "purpose")),
}
ORDER = tuple(STEPS)


def _step(key, applicability, reasons):
    title, module, prefill = STEPS[key]
    return {"key": key, "title": title, "module": module, "applicability": applicability, "reasons": reasons,
            "prefill": list(prefill), "blocks_decision": applicability == "required"}


def evaluate(profile: dict) -> list:
    """The steps for one profile (as `service._profile` returns it), in a fixed order, each with its applicability and the
    reasons. Pure: the same answers always give the same steps."""
    answers = {("provider_name" if k == "provider_note" else k): v for k, v in profile.items()}
    screening = rules.screen(answers)
    tier = rules.effective_tier(profile.get("provisional_tier"), profile.get("adopted_tier"))
    categories = set(profile.get("data_categories") or [])
    people = set(profile.get("affected_people") or []) - {"none"}
    fired = {r["rule"]: r["text"] for r in screening["reasons"]}
    missing = set(screening["missing"])
    steps = []

    def tier_reason():
        tier_name = rules.TIER_LABELS.get(tier, tier)
        adopted = profile.get("adopted_tier") is not None
        return f"The tier is {tier_name.lower()}" + (" (adopted by a reviewer)." if adopted else " (provisional).")

    # AI impact assessment: follows the tier
    if tier == "needs_review":
        steps.append(_step("aiia", "needs_review", ["Too few screening answers to say: " + ", ".join(rules.label(f) for f in screening["missing"]) + "."]))
    elif tier in ("moderate", "elevated"):
        steps.append(_step("aiia", "required", [tier_reason()] + [fired[r] for r in sorted(fired)]))
    else:
        steps.append(_step("aiia", "recommended", [tier_reason(), "No rule points to a required assessment."]))

    # Data protection impact assessment and the record of processing follow the personal data declared
    if "data_categories" in missing and not categories:
        steps.append(_step("dpia", "needs_review", ["The kinds of data have not been answered."]))
        steps.append(_step("ropa", "needs_review", ["The kinds of data have not been answered."]))
    else:
        personal = categories & _PERSONAL
        if not personal:
            steps.append(_step("dpia", "not_applicable", ["No personal data is declared."]))
            steps.append(_step("ropa", "not_applicable", ["No personal data is declared."]))
        else:
            if "E3" in fired:
                steps.append(_step("dpia", "required", [fired["E3"]]))
            elif profile.get("affects_decisions") is True:
                steps.append(_step("dpia", "required", ["Personal data is used and its output informs significant decisions about people."]))
            elif people or "M1" in fired:
                steps.append(_step("dpia", "recommended", ["Personal data is processed. A DPIA is recommended; the reviewer decides."]))
            else:
                steps.append(_step("dpia", "recommended", ["Personal data is processed."]))
            steps.append(_step("ropa", "required", ["Personal data is processed, so the processing is recorded."]))

    # Provider review follows how it is provided
    deployment = profile.get("deployment")
    if not deployment:
        steps.append(_step("vendor", "needs_review", ["How the AI is provided has not been answered."]))
    elif deployment in _VENDOR_PROVIDED:
        steps.append(_step("vendor", "required", ["A vendor provides it: " + rules.DEPLOYMENT.get(deployment, deployment).lower() + "."]))
    else:
        steps.append(_step("vendor", "not_applicable", ["Built or hosted by the organization: " + rules.DEPLOYMENT.get(deployment, deployment).lower() + "."]))

    # AI management assessment and policy follow the tier
    if tier == "needs_review":
        steps.append(_step("aims", "needs_review", ["The tier is not known yet."]))
        steps.append(_step("policy", "needs_review", ["The tier is not known yet."]))
    elif tier == "elevated":
        steps.append(_step("aims", "required", [tier_reason(), "An elevated use is assessed for AI management risk."]))
        steps.append(_step("policy", "required", [tier_reason(), "An elevated use needs a policy or procedure that covers it."]))
    elif tier == "moderate":
        steps.append(_step("aims", "recommended", [tier_reason()]))
        steps.append(_step("policy", "recommended", [tier_reason(), "Check that an existing policy covers this use."]))
    else:
        steps.append(_step("aims", "not_applicable", [tier_reason(), "A lower tier use is not assessed for AI management risk separately."]))
        steps.append(_step("policy", "recommended", ["Check that an existing policy covers this use."]))

    by_key = {s["key"]: s for s in steps}
    return [by_key[k] for k in ORDER]


# ── Where each step stands, from the owning module's records ────────────────

COMPLETE_STATUSES = {"completed", "complete", "approved", "closed", "active", "published", "finalized", "signed"}
STARTED_STATUSES = {"draft", "in_progress", "in progress", "open", "review", "under_review", "pending", "pending_review"}


def progress(records: list, changed_at=None) -> dict:
    """{"state": not_started|in_progress|complete, "stale": bool, "records": [...]} from a step's records, each
    {"title", "url", "status", "updated_at"}. A record last updated before the use's facts changed is stale."""
    if not records:
        return {"state": "not_started", "stale": False, "records": []}
    complete = [r for r in records if str(r.get("status") or "").lower() in COMPLETE_STATUSES]
    state = "complete" if complete else "in_progress"
    basis = complete or records
    stale = bool(changed_at) and all(str(r.get("updated_at") or "")[:10] < str(changed_at)[:10] for r in basis if r.get("updated_at"))
    stale = stale and any(r.get("updated_at") for r in basis)
    return {"state": state, "stale": stale, "records": records}


def snapshot(steps: list) -> str:
    """The checklist as it was judged, for the record: rule version and each step's applicability."""
    return json.dumps({"rule_version": RULE_VERSION, "steps": {s["key"]: s["applicability"] for s in steps}}, sort_keys=True)
