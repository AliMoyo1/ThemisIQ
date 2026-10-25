"""
Sentinel multi-jurisdiction registry of indicative internal review targets.

Machine-readable rules consumed by:
  - data_service.py  (breach/DSR deadline calculation)
  - scheduler.py     (breach/DSR email alerts)
  - routes.py        (jurisdiction API)
  - templates        (dynamic UI — authority, deadlines, legal bases)

Keys match the ``regulation`` field stored on every sentinel table.
These legacy values are not approved legal advice. A separately approved rule
card and case facts are required for an operational legal deadline.
"""
from __future__ import annotations

JURISDICTION_RULES: dict[str, dict] = {
    "GDPR": {
        "name": "EU General Data Protection Regulation",
        "region": "Europe",
        "flag": "EU",
        "authority": "National Data Protection Authority (Supervisory Authority)",
        "authority_short": "National DPA",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Article 33 provides for notice without undue delay and, where feasible, within 72 hours of awareness unless unlikely to risk individuals' rights and freedoms. Confirm applicability.",
        "dsr_days": 30,
        "dsr_extension_days": 60,
        "dpo_required": True,
        "registration_required": False,
        "has_lia": True,
        "dpia_required": True,
    },
    "UK GDPR": {
        "name": "UK General Data Protection Regulation",
        "region": "Europe",
        "flag": "GB",
        "authority": "Information Commissioner's Office (ICO)",
        "authority_short": "ICO",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Article 33 provides for notice without undue delay and, where feasible, within 72 hours of awareness unless unlikely to risk individuals' rights and freedoms. Confirm applicability.",
        "dsr_days": 30,
        "dsr_extension_days": 60,
        "dpo_required": True,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "Zimbabwe CDPA": {
        "name": "Cyber and Data Protection Act [Chapter 12:07]",
        "region": "Africa",
        "flag": "ZW",
        "authority": "Postal and Telecommunications Regulatory Authority (POTRAZ)",
        "authority_short": "POTRAZ",
        "breach_hours": 24,
        "breach_asap": False,
        "breach_note": "Section 19 provides a 24-hour authority notice period for a security breach affecting processed data. The statutory trigger needs specialist interpretation.",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "South Africa POPIA": {
        "name": "Protection of Personal Information Act 4 of 2013",
        "region": "Africa",
        "flag": "ZA",
        "authority": "Information Regulator (South Africa)",
        "authority_short": "Information Regulator",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Section 22 requires notification to the Regulator and affected subjects as soon as reasonably possible after discovery, subject to its conditions.",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "Kenya DPA": {
        "name": "Data Protection Act No. 24 of 2019",
        "region": "Africa",
        "flag": "KE",
        "authority": "Office of the Data Protection Commissioner (ODPC)",
        "authority_short": "ODPC",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Section 43 requires controller notification within 72 hours of awareness where the breach presents a real risk of harm.",
        "dsr_days": 7,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "Nigeria NDPR": {
        "name": "Nigeria Data Protection Act 2023 / NDPR 2019",
        "region": "Africa",
        "flag": "NG",
        "authority": "Nigeria Data Protection Commission (NDPC)",
        "authority_short": "NDPC",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify NDPC within 72 hours; notify affected persons within 7 days",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "Ghana DPA": {
        "name": "Data Protection Act 2012 (Act 843)",
        "region": "Africa",
        "flag": "GH",
        "authority": "Data Protection Commission (DPC) Ghana",
        "authority_short": "DPC Ghana",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify DPC and affected persons without undue delay",
        "dsr_days": 21,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": True,
        "has_lia": False,
        "dpia_required": False,
    },
    "UAE PDPL": {
        "name": "Federal Decree-Law No. 45 of 2021 on Personal Data Protection",
        "region": "Middle East",
        "flag": "AE",
        "authority": "UAE Data Office",
        "authority_short": "UAE Data Office",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify UAE Data Office within 72 hours",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
    "Saudi PDPL": {
        "name": "Personal Data Protection Law (Royal Decree M/19, 2021)",
        "region": "Middle East",
        "flag": "SA",
        "authority": "National Data Management Office (NDMO) / SDAIA",
        "authority_short": "NDMO/SDAIA",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify NDMO within 72 hours of discovery",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
    "Qatar DPL": {
        "name": "Personal Data Privacy Protection Law No. 13 of 2016",
        "region": "Middle East",
        "flag": "QA",
        "authority": "Ministry of Transport and Communications (MOTC) Qatar",
        "authority_short": "MOTC Qatar",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify MOTC without undue delay",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "Bahrain PDPL": {
        "name": "Personal Data Protection Law 2018",
        "region": "Middle East",
        "flag": "BH",
        "authority": "Personal Data Protection Authority (PDPA) Bahrain",
        "authority_short": "PDPA Bahrain",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify PDPA within 72 hours",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
    "Canada PIPEDA": {
        "name": "Personal Information Protection and Electronic Documents Act",
        "region": "Americas",
        "flag": "CA",
        "authority": "Office of the Privacy Commissioner of Canada (OPC)",
        "authority_short": "OPC Canada",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify OPC and individuals ASAP when real risk of significant harm exists",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "Canada Bill C-11": {
        "name": "Consumer Privacy Protection Act (Bill C-11 / CPPA)",
        "region": "Americas",
        "flag": "CA",
        "authority": "Office of the Privacy Commissioner of Canada (OPC)",
        "authority_short": "OPC Canada",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify OPC and individuals ASAP if significant harm likely",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": True,
        "dpia_required": True,
    },
    "USA CCPA/CPRA": {
        "name": "California Consumer Privacy Act / Privacy Rights Act",
        "region": "Americas",
        "flag": "US",
        "authority": "California Privacy Protection Agency (CPPA)",
        "authority_short": "CPPA (CA)",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify consumers in most expedient time; no fixed regulatory deadline",
        "dsr_days": 45,
        "dsr_extension_days": 45,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
    "Brazil LGPD": {
        "name": "Lei Geral de Proteção de Dados Pessoais (Law 13,709/2018)",
        "region": "Americas",
        "flag": "BR",
        "authority": "Autoridade Nacional de Proteção de Dados (ANPD)",
        "authority_short": "ANPD",
        "breach_hours": 48,
        "breach_asap": False,
        "breach_note": "Notify ANPD within reasonable timeframe (ANPD guidance: 2 business days)",
        "dsr_days": 15,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": False,
        "has_lia": True,
        "dpia_required": True,
    },
    "India DPDP": {
        "name": "Digital Personal Data Protection Act 2023",
        "region": "Asia-Pacific",
        "flag": "IN",
        "authority": "Data Protection Board of India",
        "authority_short": "Data Protection Board",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Intimate Data Protection Board and affected Data Principals without delay",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
    "Singapore PDPA": {
        "name": "Personal Data Protection Act 2012 (revised 2021)",
        "region": "Asia-Pacific",
        "flag": "SG",
        "authority": "Personal Data Protection Commission (PDPC)",
        "authority_short": "PDPC",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify PDPC within 3 calendar days if significant harm likely",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "Australia Privacy Act": {
        "name": "Privacy Act 1988 (Cth)",
        "region": "Asia-Pacific",
        "flag": "AU",
        "authority": "Office of the Australian Information Commissioner (OAIC)",
        "authority_short": "OAIC",
        "breach_hours": 720,
        "breach_asap": False,
        "breach_note": "Notify OAIC within 30 days of assessing as an eligible data breach",
        "dsr_days": 30,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "New Zealand Privacy Act": {
        "name": "Privacy Act 2020",
        "region": "Asia-Pacific",
        "flag": "NZ",
        "authority": "Office of the Privacy Commissioner (OPC) New Zealand",
        "authority_short": "OPC NZ",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify OPC NZ as soon as practicable if serious harm likely",
        "dsr_days": 20,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "Japan APPI": {
        "name": "Act on Protection of Personal Information (APPI) 2022",
        "region": "Asia-Pacific",
        "flag": "JP",
        "authority": "Personal Information Protection Commission (PPC) Japan",
        "authority_short": "PPC Japan",
        "breach_hours": 720,
        "breach_asap": False,
        "breach_note": "Notify PPC within 30 days (60 days for large breaches); notify subjects promptly",
        "dsr_days": 60,
        "dsr_extension_days": 0,
        "dpo_required": False,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": False,
    },
    "South Korea PIPA": {
        "name": "Personal Information Protection Act (PIPA) 2023",
        "region": "Asia-Pacific",
        "flag": "KR",
        "authority": "Personal Information Protection Commission (PIPC) South Korea",
        "authority_short": "PIPC Korea",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify PIPC within 72 hours; notify individuals without delay",
        "dsr_days": 10,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": False,
        "has_lia": False,
        "dpia_required": True,
    },
}

# Research identifies a source and a draft interpretation, not an approved rule.
# Other legacy entries have no validated source in this review and their numeric
# values are only internal triage targets.
_BREACH_RESEARCHED = {"GDPR", "UK GDPR", "Zimbabwe CDPA", "South Africa POPIA", "Kenya DPA", "Canada PIPEDA"}
_DSR_RESEARCHED = {"GDPR", "UK GDPR", "Kenya DPA", "USA CCPA/CPRA"}
_BREACH_SOURCES = {
    "GDPR": ("GDPR Article 33", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    "UK GDPR": ("ICO personal data breaches guidance", "https://ico.org.uk/for-organisations/report-a-breach/personal-data-breach/personal-data-breaches-a-guide/"),
    "Zimbabwe CDPA": ("Cyber and Data Protection Act section 19 (gazette reproduction)", "https://cyrilla.org/api/files/17222583289941iwm2aigj4w.pdf"),
    "South Africa POPIA": ("Information Regulator section 22 fact sheet", "https://inforegulator.org.za/2025/08/19/fact-sheet-handling-of-security-compromises/"),
    "Kenya DPA": ("ODPC section 43 breach reporting", "https://www.odpc.go.ke/report-a-data-breach/"),
    "Canada PIPEDA": ("OPC mandatory breach reporting guidance", "https://www.priv.gc.ca/en/privacy-topics/privacy-for-businesses/privacy-breaches-at-your-business/gd_pb_201810/"),
}
_DSR_SOURCES = {
    "GDPR": ("GDPR Article 12", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    "UK GDPR": ("ICO rights request time limits", "https://ico.org.uk/for-the-public/time-limits-for-responding-to-data-protection-rights-requests/"),
    "Kenya DPA": ("Kenya Data Protection (General) Regulations 2021", "https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf"),
    "USA CCPA/CPRA": ("California Attorney General CCPA guidance", "https://oag.ca.gov/privacy/ccpa"),
}
for _key, _rule in JURISDICTION_RULES.items():
    _rule["breach_source_status"] = "researched_unapproved" if _key in _BREACH_RESEARCHED else "unverified"
    _rule["dsr_source_status"] = "researched_unapproved" if _key in _DSR_RESEARCHED else "unverified"
    if _key in _BREACH_SOURCES:
        _rule["breach_source_title"], _rule["breach_source_url"] = _BREACH_SOURCES[_key]
    if _key in _DSR_SOURCES:
        _rule["dsr_source_title"], _rule["dsr_source_url"] = _DSR_SOURCES[_key]
    if _rule["breach_source_status"] == "unverified":
        _rule["breach_note"] = ("No validated legal notification period is recorded for this jurisdiction. "
                                "The legacy countdown is an internal review target only.")

# Canada's 2020 Bill C-11 died on the Order Paper. Keep its key to explain old
# records, but never treat the proposal's legacy numbers as an enacted rule.
JURISDICTION_RULES["Canada Bill C-11"]["legal_status"] = "proposal_not_enacted"
JURISDICTION_RULES["Canada Bill C-11"]["breach_note"] = (
    "Historical proposal, not an enacted privacy law. Reclassify this record under the applicable law.")
JURISDICTION_RULES["Canada Bill C-11"]["source_url"] = "https://www.parl.ca/LegisInfo/en/bill/43-2/c-11"
JURISDICTION_RULES["Canada Bill C-11"]["breach_source_title"] = "Parliament of Canada bill history"
JURISDICTION_RULES["Canada Bill C-11"]["breach_source_url"] = "https://www.parl.ca/LegisInfo/en/bill/43-2/c-11"


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def get_jurisdiction(key: str) -> dict | None:
    """Return rules dict for a jurisdiction key, or None if unknown."""
    return JURISDICTION_RULES.get(key)


def list_jurisdictions() -> list[dict]:
    """Known keys, including withdrawn proposals needed to explain stored records."""
    return [{"key": k, **v} for k, v in JURISDICTION_RULES.items()]


def get_breach_deadline_hours(regulation: str) -> int:
    """
    Indicative internal review hours after the recorded discovery date.
    ASAP entries use a 24-hour internal triage target, not a statutory period.
    """
    j = JURISDICTION_RULES.get(regulation, {})
    if j.get("breach_asap"):
        return 24
    return j.get("breach_hours") or 72


def breach_clock(regulation, discovery_date) -> dict:
    """What the notification clock of one breach can honestly say, from its trigger and its rule.

    state "no_trigger"  the discovery date is not recorded: no clock is running, whatever else is on the record
          "no_rule"     the regulation is not one this platform has a rule for: no deadline is calculated
          "asap"        the regulation sets no fixed hours ("as soon as practicable"): any figure shown is an internal target
          "indicative"  hours after the recorded discovery date under the configured rule

    Every deadline here is indicative: it counts from the recorded date by the configured rule, and the privacy specialist
    decides what the legal trigger and obligation are. The platform does not state a legal conclusion."""
    if not discovery_date:
        return {"state": "no_trigger", "hours": None, "basis": None,
                "label": "Not started: the discovery date is not recorded, so no deadline is calculated."}
    rule = JURISDICTION_RULES.get(regulation)
    if rule is None:
        return {"state": "no_rule", "hours": None, "basis": None,
                "label": f"No rule is configured for {regulation or 'this regulation'}, so no deadline is calculated."}
    if rule.get("legal_status") == "proposal_not_enacted":
        return {"state": "no_rule", "hours": None, "basis": None,
                "label": "This entry describes a historical proposal, not an enacted law. Select the applicable regulation."}
    if rule.get("breach_source_status") == "unverified":
        hours = get_breach_deadline_hours(regulation)
        return {"state": "unverified", "hours": hours, "basis": "Legacy internal review target",
                "label": f"No legal notification period has been verified for {regulation}. "
                         + (f"The {hours}-hour countdown is an internal review target only." if hours else
                            "No numeric review clock is available; a specialist must assess the case.")}
    if rule.get("breach_asap"):
        wording = {"South Africa POPIA": "as soon as reasonably possible",
                   "Canada PIPEDA": "as soon as feasible"}.get(regulation, "as soon as practicable")
        return {"state": "asap", "hours": None, "basis": f"{regulation}: {wording}",
                "label": f"{regulation} has no fixed-hour notification period in the researched source ({wording}). "
                         "A specialist must confirm the trigger and obligation."}
    hours = rule.get("breach_hours")
    if not hours:
        return {"state": "no_rule", "hours": None, "basis": None,
                "label": f"No notification period is configured for {regulation}, so no deadline is calculated."}
    return {"state": "indicative", "hours": hours, "basis": f"{hours} hours after the recorded discovery date under {regulation}",
            "label": f"Indicative: {hours} hours after the recorded discovery date under {regulation}. "
                     "A privacy specialist confirms the legal trigger and obligation."}


def get_dsr_deadline_days(regulation: str) -> int | None:
    """Legacy internal DSR review target. Request-specific legal periods need approval."""
    j = JURISDICTION_RULES.get(regulation, {})
    if j.get("legal_status") == "proposal_not_enacted":
        return None
    return j.get("dsr_days") or 30


def get_authority(regulation: str) -> str:
    """Full authority name for a regulation."""
    j = JURISDICTION_RULES.get(regulation, {})
    return j.get("authority", "Supervisory Authority")


def get_authority_short(regulation: str) -> str:
    """Short authority name for UI display."""
    j = JURISDICTION_RULES.get(regulation, {})
    return j.get("authority_short", "DPA")


def lia_applies(regulation: str) -> bool:
    """True when Legitimate Interest Assessments are relevant for this regulation."""
    j = JURISDICTION_RULES.get(regulation, {})
    return bool(j.get("has_lia", False))


def is_asap_jurisdiction(regulation: str) -> bool:
    """True when the legacy registry uses an ASAP internal review target."""
    j = JURISDICTION_RULES.get(regulation, {})
    return bool(j.get("breach_asap", False))


def jurisdictions_by_region() -> dict[str, list[dict]]:
    """All jurisdictions grouped by region."""
    groups: dict[str, list] = {}
    for key, rules in JURISDICTION_RULES.items():
        if rules.get("legal_status") == "proposal_not_enacted":
            continue
        region = rules.get("region", "Other")
        groups.setdefault(region, []).append({"key": key, **rules})
    return groups
