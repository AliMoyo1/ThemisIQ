"""
Regimes: how each regulation names things and what it asks a privacy record to hold.

A regime is a small dictionary resolved from the jurisdiction registry (`modules.sentinel.jurisdictions`): the terms a form should use
(controller, responsible party, data fiduciary), the citation behind each kind of field, the option lists (lawful bases, special
category conditions, transfer mechanisms) and any field that is required, not required or not shown. Nothing here is code that
decides anything: a new regime is a new entry.

Honesty about the law. Like the registry it extends, a regime carries `status`. "researched_unapproved" means the anchors were taken from
a template the owner supplied or from the statute as the platform's own text already cites it, and no privacy specialist has approved them.
"unverified" means no statutory record keeping provision has been verified for the regulation, so there are no anchors and the register
applies the GDPR Article 30 layout as good practice. Every export prints the status.
"""
from __future__ import annotations

from functools import lru_cache

from modules.sentinel.jurisdictions import JURISDICTION_RULES

SPECIALIST_NOTE = ("These anchors and required fields were prepared from the templates supplied to the platform and public texts. "
                   "They are not approved legal advice: a privacy specialist confirms them before a record is filed with a regulator.")

DEFAULT_KEY = "GDPR"

_DEFAULT_TERMS = {"controller": "controller", "processor": "processor", "dpo": "Data Protection Officer", "special": "special category",
                  "subject": "data subject", "territory": "the EEA"}

# ── Terms ────────────────────────────────────────────────────────────────────

_TERMS = {
    "GDPR": {},
    "UK GDPR": {"territory": "the UK"},
    "Zimbabwe CDPA": {"controller": "data controller", "processor": "data processor", "special": "sensitive data", "territory": "Zimbabwe"},
    "South Africa POPIA": {"controller": "responsible party", "processor": "operator", "dpo": "Information Officer",
                           "special": "special personal information", "territory": "South Africa"},
    "Kenya DPA": {"controller": "data controller", "processor": "data processor", "special": "sensitive personal data", "territory": "Kenya"},
    "Nigeria NDPR": {"controller": "data controller", "processor": "data processor", "special": "sensitive personal data", "territory": "Nigeria"},
    "Ghana DPA": {"controller": "data controller", "processor": "data processor", "dpo": "Data Protection Supervisor",
                  "special": "special personal data", "territory": "Ghana"},
    "UAE PDPL": {"special": "sensitive personal data", "territory": "the UAE"},
    "Saudi PDPL": {"dpo": "data protection lead", "special": "sensitive data", "territory": "Saudi Arabia"},
    "Qatar DPL": {"dpo": "data protection lead", "special": "personal data of a special nature", "territory": "Qatar"},
    "Bahrain PDPL": {"dpo": "data protection lead", "special": "sensitive personal data", "territory": "Bahrain"},
    "Canada PIPEDA": {"controller": "organization", "processor": "service provider", "dpo": "Privacy officer", "special": "sensitive information",
                      "subject": "individual", "territory": "Canada"},
    "Canada Bill C-11": {"controller": "organization", "processor": "service provider", "dpo": "Privacy officer", "special": "sensitive information",
                         "subject": "individual", "territory": "Canada"},
    "USA CCPA/CPRA": {"controller": "business", "processor": "service provider", "dpo": "Privacy officer", "special": "sensitive personal information",
                      "subject": "consumer", "territory": "the United States"},
    "Brazil LGPD": {"processor": "operator", "dpo": "Data Protection Officer (encarregado)", "special": "sensitive personal data", "territory": "Brazil"},
    "India DPDP": {"controller": "data fiduciary", "special": "sensitive", "subject": "data principal", "territory": "India"},
    "Singapore PDPA": {"controller": "organisation", "processor": "data intermediary", "special": "sensitive", "subject": "individual",
                       "territory": "Singapore"},
    "Australia Privacy Act": {"controller": "APP entity", "processor": "contracted service provider", "dpo": "Privacy officer",
                              "special": "sensitive information", "subject": "individual", "territory": "Australia"},
    "New Zealand Privacy Act": {"controller": "agency", "processor": "agent", "dpo": "Privacy officer", "special": "sensitive",
                                "subject": "individual", "territory": "New Zealand"},
    "Japan APPI": {"controller": "business operator", "processor": "entrusted party", "dpo": "data protection lead",
                   "special": "special care-required personal information", "subject": "principal", "territory": "Japan"},
    "South Korea PIPA": {"controller": "personal information controller", "processor": "entrustee", "dpo": "Privacy officer",
                         "special": "sensitive information", "territory": "South Korea"},
}

# ── Anchors ──────────────────────────────────────────────────────────────────
# A role key (what a field is for) to the citation behind it. The definitions name roles; only a regime with verified anchors fills them.

_GDPR_ANCHORS = {
    "controller_identity": "Art 30(1)(a)", "purposes": "Art 30(1)(b)", "data_subjects": "Art 30(1)(c)", "data_categories": "Art 30(1)(c)",
    "recipients": "Art 30(1)(d)", "transfers": "Art 30(1)(e)", "retention": "Art 30(1)(f)", "security": "Art 30(1)(g) and Art 32(1)",
    "lawful_basis": "Art 6(1)", "special_condition": "Art 9(2)", "criminal_basis": "Art 10", "children": "Art 8", "profiling": "Art 22",
    "notice": "Art 13 and 14", "further": "Art 6(4)", "dpia": "Art 35", "processor_identity": "Art 30(2)(a)",
    "processor_categories": "Art 30(2)(b)", "processor_transfers": "Art 30(2)(c)", "processor_security": "Art 30(2)(d)", "dpa": "Art 28(3)",
    "joint": "Art 26", "representative": "Art 27", "dpo": "Art 37 to 39",
    # DPIA
    "screening_cases": "Art 35(3)", "screening_list": "Art 35(4)", "systematic": "Art 35(7)(a)", "necessity": "Art 35(7)(b)",
    "risks": "Art 35(7)(c)", "measures": "Art 35(7)(d)", "dpo_advice": "Art 35(2)", "subject_views": "Art 35(9)",
    "prior_consultation": "Art 36", "review_dpia": "Art 35(11)", "lia": "Art 6(1)(f)", "design": "Art 25", "principles": "Art 5(1)",
    "rights": "Art 12 to 22", "codes": "Art 40 and 42", "ai_act": "EU AI Act Art 27",
}

_UK_ANCHORS = dict(_GDPR_ANCHORS)
_UK_ANCHORS["ai_act"] = ""

_POPIA_ANCHORS = {
    # Section 17 requires documentation but does not enumerate the GDPR Article 30 fields.
    # Keep those field anchors empty instead of implying a more specific POPIA duty.
    "purposes": "s 13",
    "transfers": "s 72", "retention": "s 14", "security": "s 19", "lawful_basis": "s 11", "special_condition": "s 26 to 33",
    "children": "s 34 and 35", "profiling": "s 71", "notice": "s 18", "further": "s 15", "dpia": "Regulation 4(1)(b)",
    "processor_identity": "s 20 and 21", "dpa": "s 21",
}

_ANCHORS = {"GDPR": _GDPR_ANCHORS, "UK GDPR": _UK_ANCHORS, "South Africa POPIA": _POPIA_ANCHORS}

_RECORD_BASIS = {
    "GDPR": ("Article 30 GDPR requires a controller to keep a record of its processing activities in writing, including in electronic form, "
             "and to make it available to the supervisory authority on request (Art 30(3) and 30(4)). A processor keeps a record of the "
             "processing it carries out for each controller (Art 30(2))."),
    "UK GDPR": ("Article 30 UK GDPR keeps the same duty: a written record of processing activities, available to the Information Commissioner's "
                "Office on request. The territory for transfers is the UK."),
    "South Africa POPIA": ("Section 17 POPIA requires a responsible party to maintain the documentation of all processing operations under its "
                           "responsibility, as referred to in section 14 or 51 of the Promotion of Access to Information Act."),
}

_DPIA_BASIS = {
    "GDPR": "Article 35 GDPR (data protection impact assessment) and Article 36 (prior consultation of the supervisory authority).",
    "UK GDPR": "Article 35 UK GDPR and the Information Commissioner's Office list of high risk processing.",
    "South Africa POPIA": ("POPIA has no article on a DPIA by that name; Regulation 4(1)(b) of the Regulator's regulations asks the Information Officer "
                           "to ensure a personal information impact assessment is done. Section 57 and 58 set out prior authorisation."),
}

# ── Lists ────────────────────────────────────────────────────────────────────

_GDPR_SPECIAL = (
    "Art 9(2)(a): explicit consent", "Art 9(2)(b): employment, social security or social protection law",
    "Art 9(2)(c): vital interests", "Art 9(2)(d): foundation, association or non-profit body", "Art 9(2)(e): made public by the data subject",
    "Art 9(2)(f): legal claims or judicial acts", "Art 9(2)(g): substantial public interest",
    "Art 9(2)(h): health or social care, occupational medicine", "Art 9(2)(i): public health", "Art 9(2)(j): archiving, research or statistics",
)
_GENERIC_SPECIAL = (
    "Explicit consent", "Employment or social security law", "Vital interests", "Legal claims", "Made public by the data subject",
    "Health care or public health", "Substantial public interest", "Research, archiving or statistics", "Other condition (describe in the notes)",
)
_POPIA_SPECIAL = (
    "Consent of the data subject", "Necessary for a right or obligation in law", "Necessary for an obligation in international public law",
    "Historical, statistical or research purposes", "Made deliberately public by the data subject", "Authorised by the Information Regulator",
    "Other ground (describe in the notes)",
)

_GDPR_TRANSFER = ("Adequacy Decision", "SCCs", "BCRs", "Other Art 46 safeguard", "Derogation (Art 49)", "Not applicable")
_UK_TRANSFER = ("UK adequacy regulations", "UK IDTA or UK Addendum", "UK BCRs", "Other safeguard", "Derogation (UK GDPR Art 49)", "Not applicable")
_POPIA_TRANSFER = ("Recipient bound by law, binding corporate rules or agreement giving adequate protection", "Data subject consent",
                   "Necessary for a contract with the data subject", "Other ground (describe in the notes)", "Not applicable")
_GENERIC_TRANSFER = ("Adequacy or equivalent protection", "Contract clauses", "Binding corporate rules or group policy", "Data subject consent",
                     "Other safeguard (describe in the notes)", "Not applicable")

SUBJECT_SUGGESTIONS = ("Customers", "Employees", "Job applicants", "Website visitors", "Contractors and suppliers", "Children", "Patients",
                       "Students", "Members", "Business contacts")

# Lists that do not change with the regulation. Definitions name them with `list_name`.
COMMON_LISTS = {
    "controller_roles": (("controller", "Controller"), ("joint_controller", "Joint controller"), ("processor", "Processor")),
    "ropa_status": (("active", "Active"), ("draft", "Draft"), ("under_review", "Under review"), ("archived", "Obsolete, retained")),
    "risk_levels": (("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")),
    "three_levels": (("low", "Low"), ("medium", "Medium"), ("high", "High")),
    "volumes": (("low", "Low"), ("medium", "Medium"), ("high", "High")),
    "data_sources": (("direct", "Directly from the data subject"), ("indirect", "From third parties"), ("both", "Both")),
    "dpia_status": (("not_required", "Not required"), ("screening", "Screening"), ("in_progress", "In progress"), ("completed", "Completed")),
}


def _legal_bases(key: str) -> tuple:
    """Use only options explicitly listed for this jurisdiction; unknown ones need specialist review."""
    from modules.sentinel.ai_service import LEGAL_BASES
    return tuple(LEGAL_BASES.get(key, ()))


def _lists_for(key: str) -> dict:
    special = _GDPR_SPECIAL if key in ("GDPR", "UK GDPR") else _POPIA_SPECIAL if key == "South Africa POPIA" else _GENERIC_SPECIAL
    transfer = (_GDPR_TRANSFER if key == "GDPR" else _UK_TRANSFER if key == "UK GDPR" else _POPIA_TRANSFER if key == "South Africa POPIA"
                else _GENERIC_TRANSFER)
    from modules.sentinel.ai_service import DATA_CATEGORIES, SPECIAL_CATEGORIES
    lists = dict(COMMON_LISTS)
    lists.update({"lawful_bases": _legal_bases(key), "special_conditions": special, "transfer_tools": transfer,
                  "data_categories": tuple(DATA_CATEGORIES), "special_categories": tuple(SPECIAL_CATEGORIES),
                  "data_subjects": SUBJECT_SUGGESTIONS})
    return lists


# ── Resolution ───────────────────────────────────────────────────────────────

def known_keys() -> list:
    return list(JURISDICTION_RULES)


@lru_cache(maxsize=64)
def resolve(regulation: str | None) -> dict:
    """The regime for a regulation key. An unknown or empty key resolves to GDPR (the layout the registry already defaults to); a key that
    is not in the registry keeps its own name and reads as an unverified regime."""
    key = (regulation or "").strip() or DEFAULT_KEY
    rule = JURISDICTION_RULES.get(key)
    terms = dict(_DEFAULT_TERMS)
    terms.update(_TERMS.get(key, {}))
    # "special category" needs "data" after it, "special personal information" and "sensitive data" do not
    terms["special_data"] = terms["special"] if terms["special"].endswith(("data", "information", "nature")) else terms["special"] + " data"
    anchors = _ANCHORS.get(key, {})
    name = (rule or {}).get("name") or key
    authority = (rule or {}).get("authority") or "the supervisory authority"
    short = (rule or {}).get("authority_short") or "the supervisory authority"
    verified = key in _ANCHORS
    basis = _RECORD_BASIS.get(key) or (
        f"No statutory record of processing provision has been verified for {name}. This register applies the Article 30 GDPR layout as good "
        f"practice; a privacy specialist confirms what {short} expects.")
    return {
        "key": key, "name": name, "terms": {**terms, "regulator": short}, "territory": terms["territory"], "anchors": anchors,
        "status": "researched_unapproved" if verified else "unverified", "record_basis": basis,
        "dpia_basis": _DPIA_BASIS.get(key) or "No statutory impact assessment provision has been verified for this regulation; the DPIA layout is applied as good practice.",
        "authority": authority, "authority_short": short, "lists": _lists_for(key), "hidden": frozenset(), "required_add": frozenset(),
        "required_drop": frozenset(), "notes": SPECIALIST_NOTE,
    }


def all_list_options() -> dict:
    """Every option of every regime, by list name: what a stored value is checked against, so a value saved under one regulation is not
    refused after the record moves to another."""
    out = {}
    for key in list(JURISDICTION_RULES) + [DEFAULT_KEY]:
        for name, options in resolve(key)["lists"].items():
            seen = out.setdefault(name, [])
            for option in options:
                value = option if isinstance(option, str) else option[0]
                if value not in seen:
                    seen.append(value)
    return out


def regulations() -> list:
    """The regulations a record can be filed under, for the form's choice: key, name, status."""
    out = []
    for key in JURISDICTION_RULES:
        regime = resolve(key)
        out.append({"key": key, "name": regime["name"], "status": regime["status"], "territory": regime["territory"]})
    return out
