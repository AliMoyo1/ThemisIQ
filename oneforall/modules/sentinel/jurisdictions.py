"""
Sentinel — Multi-Jurisdiction Registry.

Machine-readable rules consumed by:
  - data_service.py  (breach/DSR deadline calculation)
  - scheduler.py     (breach/DSR email alerts)
  - routes.py        (jurisdiction API)
  - templates        (dynamic UI — authority, deadlines, legal bases)

Keys match the ``regulation`` field stored on every sentinel table.
breach_hours=None means the law says "immediately" / "ASAP".
get_breach_deadline_hours() converts that to 24h (conservative floor).
"""
from __future__ import annotations

JURISDICTION_RULES: dict[str, dict] = {
    "GDPR": {
        "name": "EU General Data Protection Regulation",
        "region": "Europe",
        "flag": "🇪🇺",
        "authority": "National Data Protection Authority (Supervisory Authority)",
        "authority_short": "National DPA",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify lead supervisory authority within 72 hours of awareness",
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
        "flag": "🇬🇧",
        "authority": "Information Commissioner's Office (ICO)",
        "authority_short": "ICO",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify the ICO within 72 hours of awareness",
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
        "flag": "🇿🇼",
        "authority": "Postal and Telecommunications Regulatory Authority (POTRAZ)",
        "authority_short": "POTRAZ",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify POTRAZ within 72 hours of discovery",
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
        "flag": "🇿🇦",
        "authority": "Information Regulator (South Africa)",
        "authority_short": "Information Regulator",
        "breach_hours": None,
        "breach_asap": True,
        "breach_note": "Notify Information Regulator and data subjects immediately upon discovery",
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
        "flag": "🇰🇪",
        "authority": "Office of the Data Protection Commissioner (ODPC)",
        "authority_short": "ODPC",
        "breach_hours": 72,
        "breach_asap": False,
        "breach_note": "Notify ODPC within 72 hours of awareness",
        "dsr_days": 21,
        "dsr_extension_days": 0,
        "dpo_required": True,
        "registration_required": True,
        "has_lia": True,
        "dpia_required": True,
    },
    "Nigeria NDPR": {
        "name": "Nigeria Data Protection Act 2023 / NDPR 2019",
        "region": "Africa",
        "flag": "🇳🇬",
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
        "flag": "🇬🇭",
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
        "flag": "🇦🇪",
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
        "flag": "🇸🇦",
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
        "flag": "🇶🇦",
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
        "flag": "🇧🇭",
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
        "flag": "🇨🇦",
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
        "flag": "🇨🇦",
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
        "flag": "🇺🇸",
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
        "flag": "🇧🇷",
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
        "flag": "🇮🇳",
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
        "flag": "🇸🇬",
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
        "flag": "🇦🇺",
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
        "flag": "🇳🇿",
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
        "flag": "🇯🇵",
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
        "flag": "🇰🇷",
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


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def get_jurisdiction(key: str) -> dict | None:
    """Return rules dict for a jurisdiction key, or None if unknown."""
    return JURISDICTION_RULES.get(key)


def list_jurisdictions() -> list[dict]:
    """All known jurisdictions as a flat list with their key included."""
    return [{"key": k, **v} for k, v in JURISDICTION_RULES.items()]


def get_breach_deadline_hours(regulation: str) -> int:
    """
    Hours from discovery to authority notification deadline.
    ASAP jurisdictions return 24 (conservative floor for scheduler use).
    Unknown regulations default to 72.
    """
    j = JURISDICTION_RULES.get(regulation, {})
    if j.get("breach_asap"):
        return 24
    return j.get("breach_hours") or 72


def get_dsr_deadline_days(regulation: str) -> int:
    """Days from receipt to DSR response deadline. Defaults to 30."""
    j = JURISDICTION_RULES.get(regulation, {})
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
    """True when the law requires notification 'immediately' rather than a fixed window."""
    j = JURISDICTION_RULES.get(regulation, {})
    return bool(j.get("breach_asap", False))


def jurisdictions_by_region() -> dict[str, list[dict]]:
    """All jurisdictions grouped by region."""
    groups: dict[str, list] = {}
    for key, rules in JURISDICTION_RULES.items():
        region = rules.get("region", "Other")
        groups.setdefault(region, []).append({"key": key, **rules})
    return groups
