"""
AI governance: what an AI use declaration may say, and the screening rules read from it (rule set v1).

The answers are shared by the intake form and the AI profile, so a fact is asked once. `clean` checks one set of
answers; `screen` turns them into a provisional tier with every rule that fired and every answer still missing.

The tier is an internal screening aid: it says what to look at first. It is not a legal classification, it never
approves or rejects anything, and a reviewer adopts a tier of their own with a reason. A rule that does not fire
because an answer is missing never makes a use "lower": unanswered means "needs review".
"""
import re

RULE_VERSION = "v1"

TIERS = ("needs_review", "lower", "moderate", "elevated")
TIER_LABELS = {"needs_review": "Needs review", "lower": "Lower", "moderate": "Moderate", "elevated": "Elevated"}
_TIER_ORDER = {t: i for i, t in enumerate(TIERS)}

CAPABILITY_TYPES = {
    "generate": "Writes text, images, code or other content",
    "classify": "Sorts or labels things",
    "predict": "Forecasts or scores something",
    "recommend": "Suggests options to a person",
    "decide": "Makes or drives a decision",
    "assist": "Helps a person do a task",
    "other": "Something else",
}
AUTONOMY = {
    "assist_only": "A person does the work; the AI helps",
    "recommend": "The AI suggests and a person chooses",
    "decide_with_review": "The AI decides and a person reviews",
    "decide_automatically": "The AI decides with no review",
}
DEPLOYMENT = {
    "internal_build": "Built in-house",
    "vendor_service": "A vendor's AI service that we call",
    "embedded_vendor": "AI built into software we already use",
    "open_model_hosted": "An open model that we host",
}
DATA_CATEGORIES = {
    "public": "Public information",
    "internal": "Internal business information",
    "confidential": "Confidential business information",
    "personal": "Personal data",
    "sensitive_personal": "Special-category personal data",
    "financial": "Financial data",
    "health": "Health data",
}
AFFECTED_PEOPLE = {
    "none": "No one outside the team",
    "employees": "Employees",
    "customers": "Customers",
    "public": "The general public",
    "vulnerable": "Children or other vulnerable people",
}
JURISDICTIONS = {
    "ZW": "Zimbabwe", "ZA": "South Africa", "KE": "Kenya", "NG": "Nigeria", "GH": "Ghana", "UK": "United Kingdom",
    "EU": "European Union", "US": "United States", "AE": "United Arab Emirates", "OTHER": "Somewhere else",
}

_SENSITIVE = {"sensitive_personal", "health"}

# Longest value of each free-text answer. Anything longer is refused, never silently cut.
_TEXT_LIMITS = {
    "name": 120, "purpose": 2000, "provider_name": 200, "intended_users": 500, "planned_use": 1000,
    "model_changes": 500, "human_oversight": 1000, "target_launch": 40, "source_ref": 80,
}
_LISTS = {"data_categories": DATA_CATEGORIES, "affected_people": AFFECTED_PEOPLE, "jurisdictions": JURISDICTIONS}
_CHOICES = {"deployment": DEPLOYMENT, "autonomy": AUTONOMY, "capability_type": CAPABILITY_TYPES}
_YES_NO = ("affects_decisions", "external_access")  # True, False, or None for "not answered yet"
_INTS = ("owner_user_id", "business_unit_id")

FIELDS = tuple(_TEXT_LIMITS) + tuple(_LISTS) + tuple(_CHOICES) + _YES_NO + _INTS

# What a submission cannot go without. Everything else is asked when it becomes relevant and only sharpens the tier.
REQUIRED_TO_SUBMIT = ("name", "purpose", "deployment", "owner_user_id", "data_categories", "intended_users")
# The answers the screening rules read; any of them missing keeps a use at "needs review" unless a rule already fired.
SCREENING_FIELDS = ("purpose", "deployment", "data_categories", "affected_people", "autonomy", "affects_decisions",
                    "external_access")

_QUESTION_LABEL = {
    "name": "name", "purpose": "purpose", "deployment": "how it is provided", "owner_user_id": "owner",
    "data_categories": "kinds of data", "intended_users": "intended users", "affected_people": "who is affected",
    "autonomy": "how much it decides on its own", "affects_decisions": "effect on decisions about people",
    "external_access": "outside access", "business_unit_id": "business unit",
}


def label(field: str) -> str:
    """How a question is named in a message to a person."""
    return _QUESTION_LABEL.get(field, field.replace("_", " "))


def _blank(value) -> bool:
    return value is None or value == [] or value == () or (isinstance(value, str) and not value.strip())


def clean(raw) -> tuple:
    """(answers, errors). `answers` holds only known fields with usable values; `errors` maps a field to a sentence.
    A field left out stays out, a field set to null or empty is kept as "not answered". Nothing here is required:
    that is `missing_for_submit`, so a half-finished draft can always be saved."""
    if not isinstance(raw, dict):
        return {}, {"_": "Send the answers as an object."}
    answers, errors = {}, {}
    for field in FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field in _TEXT_LIMITS:
            if value is None:
                answers[field] = None
            elif not isinstance(value, str):
                errors[field] = f"The {label(field)} must be text."
            else:
                value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value).strip()
                if len(value) > _TEXT_LIMITS[field]:
                    errors[field] = f"The {label(field)} is too long (at most {_TEXT_LIMITS[field]} characters)."
                else:
                    answers[field] = value or None
        elif field in _LISTS:
            if value is None:
                answers[field] = []
            elif not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors[field] = f"The {label(field)} must be a list of choices."
            else:
                unknown = sorted({v for v in value if v not in _LISTS[field]})
                if unknown:
                    errors[field] = f"Unknown choice for {label(field)}: {', '.join(unknown[:3])}."
                else:
                    answers[field] = list(dict.fromkeys(value))
        elif field in _CHOICES:
            if value in (None, ""):
                answers[field] = None
            elif value not in _CHOICES[field]:
                errors[field] = f"Unknown choice for {label(field)}."
            else:
                answers[field] = value
        elif field in _YES_NO:
            if value in (None, "", "unknown"):
                answers[field] = None
            elif isinstance(value, bool):
                answers[field] = value
            else:
                errors[field] = f"Answer {label(field)} with yes, no or not sure."
        elif field in _INTS:
            if value in (None, ""):
                answers[field] = None
            elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
                errors[field] = f"Choose the {label(field)} from the list."
            else:
                answers[field] = value
    if "none" in answers.get("affected_people", []) and len(answers["affected_people"]) > 1:
        errors["affected_people"] = "\"No one outside the team\" cannot be combined with other choices."
        del answers["affected_people"]
    return answers, errors


def missing_for_submit(answers: dict) -> list:
    """The required answers that are not there yet, in the order they are asked."""
    return [f for f in REQUIRED_TO_SUBMIT if _blank(answers.get(f))]


def missing_for_screening(answers: dict) -> list:
    return [f for f in SCREENING_FIELDS if _blank(answers.get(f))]


def screen(answers: dict) -> dict:
    """The provisional tier of one set of answers: {"tier", "rule_version", "reasons", "missing", "complete"}.

    Each reason names the rule, the tier it points to and the answers it read. The tier is the highest tier any fired
    rule points to; with no rule fired it is "lower" only when every screening answer is given, otherwise
    "needs_review"."""
    categories = set(answers.get("data_categories") or [])
    people = set(answers.get("affected_people") or [])
    outside_team = bool(people - {"none"})
    fired = []

    def fire(rule, tier, text, *fields):
        fired.append({"rule": rule, "tier": tier, "text": text, "fields": list(fields)})

    if answers.get("affects_decisions") is True:
        fire("E1", "elevated", "Its output informs decisions with legal or similarly significant effects on people.",
             "affects_decisions")
    if answers.get("autonomy") == "decide_automatically" and outside_team:
        fire("E2", "elevated", "It decides with no human review and the decisions reach people.",
             "autonomy", "affected_people")
    if categories & _SENSITIVE and outside_team:
        fire("E3", "elevated", "It handles special-category or health data and people outside the team are affected.",
             "data_categories", "affected_people")
    if "personal" in categories or categories & _SENSITIVE:
        fire("M1", "moderate", "It processes personal data.", "data_categories")
    if answers.get("external_access") is True:
        fire("M2", "moderate", "People outside the organization use it or see what it produces.", "external_access")
    if answers.get("autonomy") == "decide_with_review":
        fire("M3", "moderate", "It makes decisions that a person then reviews.", "autonomy")
    if "financial" in categories:
        fire("M4", "moderate", "It uses financial data.", "data_categories")
    if "confidential" in categories:
        fire("M5", "moderate", "It uses confidential business information.", "data_categories")

    missing = missing_for_screening(answers)
    if fired:
        tier = max((f["tier"] for f in fired), key=_TIER_ORDER.__getitem__)
    elif missing:
        tier = "needs_review"
    else:
        tier = "lower"
    return {"tier": tier, "rule_version": RULE_VERSION, "reasons": fired, "missing": missing, "complete": not missing}


def is_tier(value) -> bool:
    return value in TIERS


def effective_tier(provisional, adopted) -> str:
    """What the workspace shows: the reviewer's adopted tier when there is one, else the provisional one."""
    return adopted if is_tier(adopted) else (provisional if is_tier(provisional) else "needs_review")
