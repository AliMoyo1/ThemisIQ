"""
Sentinel module — AI service layer.

Async port of the original Data Protection Sentinel AI service.
Supports Anthropic, OpenAI, and Google Gemini providers.
Uses httpx for async HTTP calls (matching the ARIA module pattern).
"""
import json
import httpx

from config import settings
from core.ai_client import wrap_user_input as _u

# ── Provider config (read from unified settings) ────────────────────────────

def _provider():
    return getattr(settings, "AI_PROVIDER", "anthropic").lower()

def _anthropic_key():
    return getattr(settings, "ANTHROPIC_API_KEY", "")

def _anthropic_model():
    return getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

def _openai_key():
    return getattr(settings, "OPENAI_API_KEY", "")

def _openai_model():
    return getattr(settings, "OPENAI_MODEL", "gpt-4o")

def _gemini_key():
    return getattr(settings, "GEMINI_API_KEY", "")

def _gemini_model():
    return getattr(settings, "GEMINI_MODEL", "gemini-1.5-pro")

def _deepseek_key():
    return getattr(settings, "DEEPSEEK_API_KEY", "")

def _deepseek_model():
    return getattr(settings, "DEEPSEEK_MODEL", "deepseek-chat")

def _ollama_host():
    return getattr(settings, "OLLAMA_HOST", "http://localhost:11434")

def _ollama_model():
    return getattr(settings, "OLLAMA_MODEL", "llama3.2")


# ── Low-level async API calls ───────────────────────────────────────────────

async def _call_anthropic(system: str, user: str, max_tokens: int = 4096) -> str:
    headers = {
        "x-api-key": _anthropic_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": _anthropic_model(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers, json=body,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


async def _call_openai(system: str, user: str, max_tokens: int = 4096) -> str:
    headers = {
        "Authorization": f"Bearer {_openai_key()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _openai_model(),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=body,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _call_gemini(system: str, user: str, max_tokens: int = 4096) -> str:
    model = _gemini_model()
    key = _gemini_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _call_deepseek(system: str, user: str, max_tokens: int = 4096) -> str:
    """DeepSeek chat API — OpenAI-compatible format."""
    headers = {
        "Authorization": f"Bearer {_deepseek_key()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _deepseek_model(),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers, json=body,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _call_deepseek_multi(system: str, messages: list, max_tokens: int = 1500) -> str:
    """Multi-turn DeepSeek call (for chat with history)."""
    headers = {
        "Authorization": f"Bearer {_deepseek_key()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _deepseek_model(),
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers, json=body,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _call_ollama(system: str, user: str, max_tokens: int = 4096) -> str:
    """Ollama local inference — uses the OpenAI-compatible /v1/ endpoint (available since Ollama 0.1.24)."""
    host = _ollama_host().rstrip("/")
    body = {
        "model": _ollama_model(),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=180) as client:  # local models can be slow
        r = await client.post(f"{host}/v1/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _call_ollama_multi(system: str, messages: list, max_tokens: int = 1500) -> str:
    """Multi-turn Ollama call (for chat with history)."""
    host = _ollama_host().rstrip("/")
    body = {
        "model": _ollama_model(),
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{host}/v1/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def call_ai(system: str, user: str, max_tokens: int = 4096):
    """Returns (text, error_message). Provider-agnostic dispatcher."""
    provider = _provider()
    try:
        if provider == "anthropic":
            if not _anthropic_key():
                return None, "ANTHROPIC_API_KEY not configured"
            return await _call_anthropic(system, user, max_tokens), None
        elif provider == "openai":
            if not _openai_key():
                return None, "OPENAI_API_KEY not configured"
            return await _call_openai(system, user, max_tokens), None
        elif provider == "gemini":
            if not _gemini_key():
                return None, "GEMINI_API_KEY not configured"
            return await _call_gemini(system, user, max_tokens), None
        elif provider == "deepseek":
            if not _deepseek_key():
                return None, "DEEPSEEK_API_KEY not configured"
            return await _call_deepseek(system, user, max_tokens), None
        elif provider == "ollama":
            return await _call_ollama(system, user, max_tokens), None
        else:
            return None, f"Unknown AI_PROVIDER: {provider}"
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = e.response.text[:500]
        return None, f"API error {e.response.status_code}: {detail}"
    except Exception as e:
        return None, str(e)


async def _call_anthropic_multi(system: str, messages: list, max_tokens: int = 1500) -> str:
    """Multi-turn Anthropic call (for chat with history)."""
    headers = {
        "x-api-key": _anthropic_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": _anthropic_model(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers, json=body,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


# ═════════════════════════════════════════════════════════════════════════════
# REGULATION REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

REGULATIONS = [
    ("GDPR",                  "GDPR — EU General Data Protection Regulation 2016/679"),
    ("UK GDPR",               "UK GDPR — United Kingdom General Data Protection Regulation"),
    ("Zimbabwe CDPA",         "Zimbabwe Cyber & Data Protection Act [Chapter 12:07] (2021)"),
    ("South Africa POPIA",    "South Africa POPIA — Protection of Personal Information Act 4 of 2013"),
    ("Kenya DPA",             "Kenya Data Protection Act No. 24 of 2019"),
    ("Nigeria NDPR",          "Nigeria NDPR — Nigeria Data Protection Regulation 2019"),
    ("Ghana DPA",             "Ghana Data Protection Act 2012 (Act 843)"),
    ("UAE PDPL",              "UAE Federal Decree-Law No. 45 of 2021 on Personal Data Protection"),
    ("Saudi PDPL",            "Saudi Arabia PDPL — Personal Data Protection Law (Royal Decree M/19)"),
    ("Qatar DPL",             "Qatar Personal Data Privacy Protection Law No. 13 of 2016"),
    ("Bahrain PDPL",          "Bahrain Personal Data Protection Law 2018"),
    ("Canada PIPEDA",         "Canada PIPEDA — Personal Information Protection and Electronic Documents Act"),
    ("Canada Bill C-11",      "Canada — Consumer Privacy Protection Act (Bill C-11)"),
    ("USA CCPA/CPRA",         "USA CCPA/CPRA — California Consumer Privacy Act & Privacy Rights Act"),
    ("Brazil LGPD",           "Brazil LGPD — Lei Geral de Proteção de Dados Pessoais (2018)"),
    ("India DPDP",            "India Digital Personal Data Protection Act 2023"),
    ("Singapore PDPA",        "Singapore Personal Data Protection Act 2012 (revised 2021)"),
    ("Australia Privacy Act", "Australia Privacy Act 1988 (Cth) (revised 2022)"),
    ("New Zealand Privacy Act","New Zealand Privacy Act 2020"),
    ("Japan APPI",            "Japan Act on Protection of Personal Information (APPI) 2022"),
    ("South Korea PIPA",      "South Korea Personal Information Protection Act (PIPA) 2023"),
]

REGULATION_META = {
    "GDPR": {
        "full": "EU General Data Protection Regulation 2016/679",
        "authority": "relevant EU Data Protection Authority (Supervisory Authority)",
        "key_articles": "Arts. 35-36 (DPIA), Art. 5 (principles), Art. 6 (lawful basis), Art. 9 (special categories), Art. 13-14 (transparency)",
        "thresholds": "systematic monitoring, large-scale special-category data, public area monitoring, automated decisions",
        "breach_window": "72 hours to supervisory authority; without undue delay to subjects",
        "dsr_window": "1 month (extendable to 3 months)",
        "rights": "Access, Erasure, Portability, Rectification, Restriction, Objection, Automated decision-making",
    },
    "UK GDPR": {
        "full": "United Kingdom General Data Protection Regulation (UK GDPR)",
        "authority": "Information Commissioner's Office (ICO)",
        "key_articles": "Arts. 35-36 (DPIA), Art. 5 (principles), Art. 6 (lawful basis), Art. 9 (special categories)",
        "thresholds": "systematic monitoring, large-scale processing, new technologies, automated decisions",
        "breach_window": "72 hours to ICO; without undue delay to subjects",
        "dsr_window": "1 month (extendable to 3 months)",
        "rights": "Access, Erasure, Portability, Rectification, Restriction, Objection",
    },
    "Zimbabwe CDPA": {
        "full": "Zimbabwe Cyber and Data Protection Act [Chapter 12:07] (2021)",
        "authority": "Postal and Telecommunications Regulatory Authority (POTRAZ)",
        "key_articles": "Part III (data protection principles), s. 20+ (controller obligations), s. 30 (impact assessments)",
        "thresholds": "processing of sensitive personal information, automated decisions, large scale processing",
        "breach_window": "72 hours to POTRAZ",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Deletion, Portability, Objection",
    },
    "South Africa POPIA": {
        "full": "South Africa Protection of Personal Information Act 4 of 2013 (POPIA)",
        "authority": "Information Regulator (South Africa)",
        "key_articles": "s. 22 (PIA), Conditions 1-8, s. 26 (special categories), s. 73 (breach notification)",
        "thresholds": "high-risk processing, sensitive personal information, children's data, automated profiling",
        "breach_window": "Immediately to Information Regulator; ASAP to data subjects",
        "dsr_window": "30 days",
        "rights": "Access, Correction/Deletion, Objection",
    },
    "Kenya DPA": {
        "full": "Kenya Data Protection Act No. 24 of 2019",
        "authority": "Office of the Data Protection Commissioner (ODPC)",
        "key_articles": "Part III (principles), Part V (rights), s. 42 (impact assessments), s. 43 (breach notification)",
        "thresholds": "high-risk processing, sensitive data, children's data, systematic profiling",
        "breach_window": "72 hours to ODPC",
        "dsr_window": "21 days",
        "rights": "Access, Rectification, Erasure, Portability, Restriction, Objection",
    },
    "Nigeria NDPR": {
        "full": "Nigeria Data Protection Regulation 2019 (NDPR) — Nigeria Data Protection Act 2023",
        "authority": "Nigeria Data Protection Commission (NDPC)",
        "key_articles": "Art. 2 (principles), Art. 3 (controller obligations), Art. 2.9 (impact assessments)",
        "thresholds": "large-scale processing, sensitive personal data, processing for profit",
        "breach_window": "72 hours to NDPC; 7 days to data subjects",
        "dsr_window": "30 days",
        "rights": "Access, Rectification, Erasure, Portability, Objection",
    },
    "UAE PDPL": {
        "full": "UAE Federal Decree-Law No. 45 of 2021 on Personal Data Protection",
        "authority": "UAE Data Office",
        "key_articles": "Art. 16 (impact assessment), Arts. 4-8 (processing conditions), Art. 22 (sensitive data)",
        "thresholds": "sensitive personal data, new technologies, systematic processing, cross-border transfers",
        "breach_window": "72 hours to UAE Data Office",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Erasure, Portability, Restriction, Objection",
    },
    "Saudi PDPL": {
        "full": "Saudi Arabia Personal Data Protection Law (Royal Decree M/19, 2021)",
        "authority": "National Data Management Office (NDMO) / Saudi Data and AI Authority (SDAIA)",
        "key_articles": "Art. 29 (impact assessment), Arts. 4-7 (data processing rules), Art. 23 (sensitive data)",
        "thresholds": "sensitive data, cross-border transfers, automated decision-making, large-scale processing",
        "breach_window": "72 hours to NDMO",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Erasure, Portability",
    },
    "Qatar DPL": {
        "full": "Qatar Personal Data Privacy Protection Law No. 13 of 2016",
        "authority": "Ministry of Transport and Communications (MOTC)",
        "key_articles": "Arts. 4-6 (controller obligations), Art. 17 (sensitive data), cross-border transfer rules",
        "thresholds": "special category data, large-scale processing, systematic surveillance",
        "breach_window": "Not specified — notify without undue delay",
        "dsr_window": "30 days",
        "rights": "Access, Rectification, Erasure, Restriction",
    },
    "Bahrain PDPL": {
        "full": "Bahrain Personal Data Protection Law 2018",
        "authority": "Personal Data Protection Authority (PDPA) Bahrain",
        "key_articles": "Arts. 6-10 (conditions for processing), Art. 28 (impact assessments), Art. 15 (sensitive data)",
        "thresholds": "sensitive data, automated decisions, cross-border transfers, large-scale processing",
        "breach_window": "72 hours to PDPA",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Erasure, Portability, Objection",
    },
    "Ghana DPA": {
        "full": "Ghana Data Protection Act 2012 (Act 843)",
        "authority": "Data Protection Commission (DPC) Ghana",
        "key_articles": "Part II (principles), Part III (rights), s. 33 (impact assessment), registration requirements",
        "thresholds": "sensitive personal data, systematic processing, automated decisions",
        "breach_window": "Notify DPC and subjects without undue delay",
        "dsr_window": "21 days",
        "rights": "Access, Rectification, Objection",
    },
    "Canada PIPEDA": {
        "full": "Canada Personal Information Protection and Electronic Documents Act (PIPEDA)",
        "authority": "Office of the Privacy Commissioner of Canada (OPC)",
        "key_articles": "Schedule 1 (fair information principles), s. 10 (breach of security safeguards)",
        "thresholds": "real risk of significant harm from a breach, systematic profiling, sensitive data",
        "breach_window": "ASAP to OPC and affected individuals if real risk of significant harm",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Withdrawal of consent",
    },
    "Canada Bill C-11": {
        "full": "Canada Consumer Privacy Protection Act (Bill C-11 / CPPA)",
        "authority": "Office of the Privacy Commissioner of Canada (OPC)",
        "key_articles": "Legitimate interest, consent requirements, algorithmic transparency, de-identification",
        "thresholds": "automated decision-making with significant impact, sensitive data, children's data",
        "breach_window": "ASAP to OPC and individuals if real risk of significant harm",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Erasure, Portability, Explanation of automated decisions",
    },
    "USA CCPA/CPRA": {
        "full": "California Consumer Privacy Act (CCPA) / California Privacy Rights Act (CPRA)",
        "authority": "California Privacy Protection Agency (CPPA)",
        "key_articles": "ss. 1798.100-1798.199 CCPA; CPRA amendments on sensitive personal information",
        "thresholds": "businesses meeting revenue/data thresholds, selling/sharing personal information",
        "breach_window": "Statutory damages available; notify ASAP after discovery",
        "dsr_window": "45 days (extendable by 45 days)",
        "rights": "Access, Deletion, Opt-out (sale/sharing), Non-discrimination, Correction, Limitation of sensitive data use",
    },
    "Brazil LGPD": {
        "full": "Brazil Lei Geral de Protecao de Dados Pessoais — Law No. 13,709/2018",
        "authority": "Autoridade Nacional de Protecao de Dados (ANPD)",
        "key_articles": "Art. 5 (definitions), Art. 7-11 (lawful basis), Art. 38 (impact assessment), Art. 48 (breach)",
        "thresholds": "high-risk processing, sensitive data, automated decisions with significant effects",
        "breach_window": "Reasonable timeframe to ANPD and subjects",
        "dsr_window": "15 days",
        "rights": "Access, Correction, Anonymisation/Deletion, Portability, Revocation, Objection",
    },
    "India DPDP": {
        "full": "India Digital Personal Data Protection Act 2023",
        "authority": "Data Protection Board of India",
        "key_articles": "s. 4 (grounds for processing), s. 8 (obligations of data fiduciaries), s. 10 (significant data fiduciaries)",
        "thresholds": "significant data fiduciaries, children's data, cross-border transfers",
        "breach_window": "Intimation to Board and affected Data Principals",
        "dsr_window": "Not specified — reasonable timeframe",
        "rights": "Access, Correction, Erasure, Grievance redressal, Nomination",
    },
    "Singapore PDPA": {
        "full": "Singapore Personal Data Protection Act 2012 (revised 2021)",
        "authority": "Personal Data Protection Commission (PDPC)",
        "key_articles": "Part III-IV (obligations), Part VIA (data breach notification), Part VI (data innovation)",
        "thresholds": "significant harm from breach, systematic processing, overseas transfers",
        "breach_window": "3 days to PDPC (significant); notify individuals if significant harm",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Withdrawal of consent, Data portability",
    },
    "Australia Privacy Act": {
        "full": "Australia Privacy Act 1988 (Cth)",
        "authority": "Office of the Australian Information Commissioner (OAIC)",
        "key_articles": "Australian Privacy Principles (APPs 1-13), Part IIIC (Notifiable Data Breaches)",
        "thresholds": "entities with >$3M annual turnover, health information, eligible data breaches",
        "breach_window": "30 days to OAIC once eligibility assessed; notify affected individuals",
        "dsr_window": "30 days",
        "rights": "Access, Correction, Complaint",
    },
    "New Zealand Privacy Act": {
        "full": "New Zealand Privacy Act 2020",
        "authority": "Office of the Privacy Commissioner (OPC) New Zealand",
        "key_articles": "Information Privacy Principles (IPPs 1-13), Part 6 (breach notification)",
        "thresholds": "serious harm from breach, overseas transfers, automated decisions",
        "breach_window": "ASAP to OPC if serious harm likely; notify affected individuals",
        "dsr_window": "20 working days",
        "rights": "Access, Correction",
    },
    "Japan APPI": {
        "full": "Japan Act on Protection of Personal Information (APPI) — amended 2022",
        "authority": "Personal Information Protection Commission (PPC) Japan",
        "key_articles": "Art. 17 (purpose limitation), Art. 23-24 (third party provision), Art. 26 (breach), Art. 28 (overseas transfer)",
        "thresholds": "sensitive personal information, large-scale data handling, overseas transfer without consent",
        "breach_window": "ASAP to PPC (within 30 days for most; 60 days for large breaches) and affected individuals",
        "dsr_window": "Promptly",
        "rights": "Disclosure, Correction, Deletion, Objection to third party provision",
    },
    "South Korea PIPA": {
        "full": "South Korea Personal Information Protection Act (PIPA) 2023",
        "authority": "Personal Information Protection Commission (PIPC) South Korea",
        "key_articles": "Art. 15 (grounds), Art. 23 (sensitive info), Art. 29 (security measures), Art. 34 (breach notification)",
        "thresholds": "sensitive information, large-scale processing, automated decisions with significant effects",
        "breach_window": "72 hours to PIPC; notify affected individuals without delay",
        "dsr_window": "10 days",
        "rights": "Access, Correction, Deletion, Suspension of processing, Portability",
    },
}

LEGAL_BASES = {
    "GDPR": [
        "Consent — Art. 6(1)(a)",
        "Contract performance — Art. 6(1)(b)",
        "Legal obligation — Art. 6(1)(c)",
        "Vital interests — Art. 6(1)(d)",
        "Public task — Art. 6(1)(e)",
        "Legitimate interests — Art. 6(1)(f)",
    ],
    "UK GDPR": [
        "Consent — Art. 6(1)(a)",
        "Contract performance — Art. 6(1)(b)",
        "Legal obligation — Art. 6(1)(c)",
        "Vital interests — Art. 6(1)(d)",
        "Public task — Art. 6(1)(e)",
        "Legitimate interests — Art. 6(1)(f)",
    ],
    "Zimbabwe CDPA": [
        "Consent", "Contract necessity", "Legal obligation",
        "Vital interests", "Public interest", "Legitimate interests of the controller",
    ],
    "South Africa POPIA": [
        "Consent — Condition 1", "Contractual necessity", "Legal obligation",
        "Vital interests of the data subject", "Public law duty",
        "Legitimate interests of the responsible party",
    ],
    "Kenya DPA": [
        "Consent", "Contract performance", "Legal obligation",
        "Vital interests", "Public interest or official authority",
        "Legitimate interests of the controller",
    ],
    "Nigeria NDPR": [
        "Consent", "Contract performance", "Legal obligation",
        "Vital interests", "Public interest", "Legitimate interests",
    ],
    "UAE PDPL": [
        "Explicit consent", "Contractual necessity", "Legal obligation",
        "Vital interests", "Public interest", "Legitimate interests",
    ],
    "Saudi PDPL": [
        "Explicit consent", "Legal or regulatory requirement",
        "Contract conclusion or execution", "Protection of vital interests",
        "Data made publicly available by the subject", "Judicial and security purposes",
    ],
    "Qatar DPL": [
        "Consent of the data subject", "Contract with the data subject",
        "Legal obligation", "Vital interests",
        "Public interest or government task", "Legitimate interests",
    ],
    "Bahrain PDPL": [
        "Explicit consent", "Contract necessity", "Legal obligation",
        "Vital interests", "Public interest", "Legitimate interests of the controller",
    ],
    "Ghana DPA": [
        "Consent", "Contract necessity", "Legal obligation",
        "Vital interests", "Public interest",
    ],
    "Canada PIPEDA": [
        "Expressed consent", "Implied consent", "Legal requirement",
        "Contractual necessity", "Public interest",
    ],
    "Canada Bill C-11": [
        "Consent (express or implied)", "Legitimate interests (with risk assessment)",
        "Sensitive information — explicit consent", "Legal requirement", "Employment purposes",
    ],
    "USA CCPA/CPRA": [
        "Notice and opt-out opportunity", "Opt-in (sensitive personal information)",
        "Business purpose necessity", "Service provider disclosure", "Legal obligation",
    ],
    "Brazil LGPD": [
        "Consent — Art. 7(I)", "Legal or regulatory compliance — Art. 7(II)",
        "Public policy execution — Art. 7(III)", "Research studies — Art. 7(IV)",
        "Contract execution — Art. 7(V)", "Judicial proceedings — Art. 7(VI)",
        "Life or physical safety protection — Art. 7(VII)", "Health protection — Art. 7(VIII)",
        "Legitimate interests — Art. 7(IX)", "Credit protection — Art. 7(X)",
    ],
    "India DPDP": [
        "Consent — s. 6", "Legitimate uses — s. 7 (state functions)",
        "Legal obligation", "Medical emergencies / epidemic response", "Employment purposes",
    ],
    "Singapore PDPA": [
        "Consent — Part IV", "Legitimate interests — Second Schedule",
        "Business improvement purposes", "Legal requirement", "Research purposes",
    ],
    "Australia Privacy Act": [
        "Consent", "Direct relationship with the individual",
        "Required or authorised by law", "Necessary for enforcement body functions",
        "Necessary for a health situation",
    ],
    "New Zealand Privacy Act": [
        "Directly related purpose", "Consent", "Legal requirement",
        "Publicly available information", "Serious threat to safety",
    ],
    "Japan APPI": [
        "Consent", "Necessary for contract", "Necessary for compliance with laws",
        "Necessary to protect vital interests", "Necessary for public interest",
        "Legitimate interests of the business operator",
    ],
    "South Korea PIPA": [
        "Consent — Art. 15(1)(1)", "Special laws/regulations — Art. 15(1)(2)",
        "Contract performance — Art. 15(1)(4)", "Vital interests — Art. 15(1)(5)",
        "Legitimate interests — Art. 15(1)(6)",
    ],
}

ACTIVITY_TYPES = [
    "Automated decision-making / AI", "Biometric data processing",
    "CCTV / video surveillance", "Children's data processing",
    "Cloud migration of personal data", "Credit scoring / financial profiling",
    "Criminal record processing", "Cross-border data transfers",
    "Customer analytics & profiling", "Employee monitoring",
    "Fraud detection / prevention", "Health data processing",
    "Identity verification (KYC/AML)", "IoT / smart device data collection",
    "Location tracking", "Loyalty programme management",
    "Marketing & direct communications", "Mobile app data collection",
    "Online behavioural advertising", "Payroll & HR data processing",
    "Recruitment & background checks", "Research & statistical analysis",
    "Social media monitoring", "Third-party data sharing",
    "Other (describe below)",
]

DATA_CATEGORIES = [
    "Basic identifiers (name, address, ID numbers)",
    "Contact data (email, phone)",
    "Financial data (bank details, payment info)",
    "Employment & HR data", "Location data",
    "Online identifiers (IP, cookies, device IDs)",
    "Behavioural / usage data", "Communications data",
    "Academic / education records", "Criminal records",
    "Immigration / nationality data",
]

SPECIAL_CATEGORIES = [
    "Racial or ethnic origin", "Political opinions",
    "Religious or philosophical beliefs", "Trade union membership",
    "Genetic data", "Biometric data (for identification)",
    "Health / medical data", "Sex life or sexual orientation",
    "Criminal convictions and offences",
    "Financial distress / insolvency data", "Children's personal data",
]


# ═════════════════════════════════════════════════════════════════════════════
# AI FEATURES
# ═════════════════════════════════════════════════════════════════════════════

async def ai_research(activity_type: str, regulation: str, context: str = ""):
    """DPIA preliminary research report."""
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a senior Data Protection Officer and privacy lawyer with expertise across "
        "all major global data protection frameworks. You produce detailed, accurate, "
        "professionally-worded DPIA research reports. Always cite the relevant legal articles. "
        "Be thorough, practical, and jurisdiction-specific."
    )
    user = f"""Conduct a DPIA preliminary research report for the following:

Processing Activity: {_u(activity_type)}
Regulation: {meta.get('full', regulation)}
Supervisory Authority: {meta.get('authority', 'N/A')}
Key Legal Provisions: {meta.get('key_articles', 'N/A')}
DPIA Triggers: {meta.get('thresholds', 'N/A')}
{f'Additional Context: {_u(context)}' if context else ''}

Write a structured research report covering:
1. Nature and scope of this processing activity
2. Why a DPIA is required under {regulation}
3. Applicable legal bases and conditions
4. Typical personal data involved (categories & special categories)
5. Common privacy risks for this activity type
6. Recommended technical and organisational safeguards
7. Relevant regulatory guidance or precedents
8. Data subject rights implications under {regulation}

Be specific, cite the law, and make this immediately useful for completing the DPIA."""
    return await call_ai(system, user, max_tokens=3000)


async def ai_generate_full_dpia(dpia: dict):
    """Generate a complete DPIA document."""
    regulation = dpia.get("regulation", "GDPR")
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a senior DPO and privacy counsel. "
        "Generate a complete, legally rigorous Data Protection Impact Assessment. "
        "Write in formal, professional language suitable for regulatory submission. "
        "Be comprehensive, specific, and cite the relevant law throughout."
    )
    cats = ", ".join(dpia.get("data_categories", [])) if isinstance(dpia.get("data_categories"), list) else str(dpia.get("data_categories", "Not specified"))
    scats = ", ".join(dpia.get("special_cats", [])) if isinstance(dpia.get("special_cats"), list) else str(dpia.get("special_cats", "None"))
    user = f"""Generate a complete DPIA under {meta.get('full', regulation)}.

Reference: {dpia.get('ref_number')} | Title: {_u(dpia.get('title', ''))}
Organisation: {_u(dpia.get('org_name', ''))} | Dept: {_u(dpia.get('department', ''))}
Controller: {_u(dpia.get('controller_name', ''))} | DPO: {_u(dpia.get('dpo_name', ''))}
Activity: {_u(dpia.get('activity_type', ''))} | Purpose: {_u(dpia.get('purpose', ''))}
Legal Basis: {_u(dpia.get('legal_basis', ''))}
Data: {_u(cats)} | Special: {_u(scats)}
Subjects: {_u(dpia.get('data_subjects', ''))} (~{dpia.get('subject_count')})
Retention: {_u(dpia.get('retention', ''))} | Systems: {_u(dpia.get('systems', ''))}
Processors: {_u(dpia.get('processors', ''))}
Transfers: {dpia.get('intl_transfer')} -> {_u(dpia.get('transfer_dest', ''))} via {_u(dpia.get('transfer_mech', ''))}
Overall Risk: {dpia.get('overall_risk')} | Residual: {dpia.get('residual_risk')}

Regulation: {meta.get('full', regulation)}
Authority: {meta.get('authority')} | Articles: {meta.get('key_articles')}

Write a full DPIA with all sections: Executive Summary, Description of Processing, Legal Basis,
Necessity & Proportionality, Data Subject Rights, Risk Assessment (with likelihood/severity matrix),
Risk Mitigation (technical & organisational), Residual Risk, Consultation, Conclusion & Decision.
Cite {regulation} throughout."""
    return await call_ai(system, user, max_tokens=6000)


async def ai_suggest_risks(activity: str, regulation: str, categories: list):
    """Suggest privacy risks as structured JSON."""
    cats = ", ".join(categories) if categories else "general personal data"
    system = "You are a privacy risk expert. Return ONLY valid JSON, no markdown, no explanation."
    user = f"""For processing activity {_u(activity)} under {regulation} involving {_u(cats)},
return a JSON array of 5 risks:
[{{"desc":"Short risk description","likelihood":"High|Medium|Low","impact":"High|Medium|Low","mitigation":"Mitigation measure"}}]"""
    text, err = await call_ai(system, user, max_tokens=800)
    if err:
        return None, err
    try:
        clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean), None
    except Exception as e:
        return None, f"JSON parse error: {e}"


async def ai_score_ropa(ropa: dict):
    """Score a RoPA entry for risk level."""
    system = (
        "You are a privacy risk analyst. Assess the risk level of a data processing activity. "
        "Return ONLY valid JSON, no markdown."
    )
    user = f"""Assess the privacy risk level for this processing activity:
Name: {_u(ropa.get('processing_name', ''))}
Purpose: {_u(ropa.get('purpose', ''))}
Legal basis: {_u(ropa.get('legal_basis', ''))}
Data categories: {_u(str(ropa.get('data_categories', [])))}
Special categories: {_u(str(ropa.get('special_categories', [])))}
Data subjects: {_u(ropa.get('data_subjects', ''))}
Volume: {ropa.get('subject_count')}
International transfers: {ropa.get('intl_transfers')}
Regulation: {ropa.get('regulation', 'GDPR')}

Return JSON: {{"risk_score": "low|medium|high|critical", "rationale": "2-3 sentence explanation", "dpia_required": true|false, "flags": ["flag1","flag2"]}}"""
    text, err = await call_ai(system, user, max_tokens=500)
    if err:
        return None, err
    try:
        clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean), None
    except Exception as e:
        return None, f"JSON parse error: {e}"


async def ai_assess_breach(breach: dict):
    """Assess a data breach and recommend notifications."""
    regulation = breach.get("regulation", "GDPR")
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a data breach response expert and privacy lawyer. "
        "Provide a practical, actionable breach impact assessment."
    )
    user = f"""Assess this data breach under {meta.get('full', regulation)}:

Title: {_u(breach.get('title', ''))}
Discovery date: {breach.get('discovery_date')}
Incident date: {breach.get('incident_date')}
Type: {_u(breach.get('breach_type', ''))}
Description: {_u(breach.get('description', ''))}
Data types affected: {_u(str(breach.get('data_types', [])))}
Estimated affected individuals: {breach.get('affected_count')}
Severity (self-assessed): {_u(breach.get('severity', ''))}

Regulatory framework: {meta.get('full', regulation)}
Authority: {meta.get('authority')}
Breach notification window: {meta.get('breach_window', 'Not specified')}

Provide:
1. SEVERITY ASSESSMENT — Is this a low/medium/high/critical breach and why?
2. NOTIFICATION REQUIREMENT — Must this be reported to the regulator? To data subjects?
3. NOTIFICATION DEADLINES — When must notifications occur?
4. IMMEDIATE ACTIONS — Top 5 actions to take right now
5. MITIGATION — How to contain and remediate the breach
6. REGULATORY RISK — Potential fines/enforcement risk

Be specific and practical."""
    return await call_ai(system, user, max_tokens=2000)


async def ai_draft_dsr_response(dsr: dict):
    """Draft a DSR response letter."""
    regulation = dsr.get("regulation", "GDPR")
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a privacy lawyer drafting formal data subject rights response letters. "
        "Be professional, compliant, and clear."
    )
    user = f"""Draft a response letter for this data subject request:

Request type: {_u(dsr.get('request_type', ''))}
Requester name: {_u(dsr.get('requester_name', ''))}
Requester email: {_u(dsr.get('requester_email', ''))}
Description: {_u(dsr.get('description', ''))}
Received: {dsr.get('received_date')}
Deadline: {dsr.get('deadline_date')}
Regulation: {meta.get('full', regulation)}
Rights framework: {meta.get('rights', 'Standard rights')}
Response window: {meta.get('dsr_window', '30 days')}

Write a professional response letter that:
- Acknowledges receipt of the request
- Explains the applicable rights under {regulation}
- States what action will be taken
- Gives the timeline
- Provides escalation/complaint options
- Is properly formatted as a formal letter"""
    return await call_ai(system, user, max_tokens=1500)


async def ai_generate_privacy_notice(data: dict):
    """Generate a privacy notice."""
    regulation = data.get("regulation", "GDPR")
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a privacy lawyer writing GDPR-compliant privacy notices. "
        "Write in plain language that is clear, concise, and legally complete."
    )
    user = f"""Generate a privacy notice under {meta.get('full', regulation)} for:

Organisation: {_u(data.get('org_name', '[Organisation Name]'))}
DPO: {_u(data.get('dpo_name', '[DPO Name]'))} | Email: {_u(data.get('dpo_email', '[DPO Email]'))}
Audience: {_u(data.get('audience', 'Customers and website visitors'))}
Processing activities: {_u(data.get('activities', 'Various data processing activities'))}
Data types: {_u(data.get('data_types', 'Names, contact details, and other personal data'))}
Purposes: {_u(data.get('purposes', 'Service delivery, marketing, and legal compliance'))}
Retention: {_u(data.get('retention', 'As per retention schedule'))}

Requirements under {regulation}:
- Key articles: {meta.get('key_articles', 'Transparency obligations')}
- Data subject rights: {meta.get('rights', 'Standard rights')}

Write a complete privacy notice with all required sections:
1. Who we are (controller details)
2. What data we collect
3. Why we collect it (purposes & legal basis)
4. How long we keep it
5. Who we share it with
6. International transfers (if applicable)
7. Your rights under {regulation}
8. How to exercise your rights
9. Complaints
10. How to contact us / Changes to this notice

Use plain language. Organise with clear headings."""
    return await call_ai(system, user, max_tokens=3000)


async def ai_vendor_check(vendor: dict):
    """Assess a vendor/processor for data protection compliance."""
    system = (
        "You are a data protection due diligence expert. "
        "Assess this vendor/processor for privacy compliance risks."
    )
    user = f"""Assess this data processor/vendor for data protection compliance:

Name: {_u(vendor.get('name', ''))}
Type: {_u(vendor.get('type', ''))}
Country: {_u(vendor.get('country', ''))}
Services: {_u(vendor.get('services', ''))}
Data types processed: {_u(str(vendor.get('data_types', [])))}
Data subjects: {_u(vendor.get('data_subjects', ''))}
DPA status: {_u(vendor.get('dpa_status', ''))}
Regulation: {vendor.get('regulation', 'GDPR')}

Provide:
1. RISK RATING — low/medium/high/critical with explanation
2. KEY CONCERNS — top 3 data protection concerns
3. REQUIRED CLAUSES — what must be in the DPA
4. DUE DILIGENCE CHECKLIST — 5 things to verify
5. TRANSFER MECHANISM — what safeguard is needed for cross-border transfers
6. RECOMMENDATION — approve/approve with conditions/reject"""
    return await call_ai(system, user, max_tokens=1500)


async def ai_chat(message: str, regulation: str = None, history: list = None):
    """General AI privacy compliance chat."""
    reg_context = ""
    if regulation and regulation in REGULATION_META:
        meta = REGULATION_META[regulation]
        reg_context = (
            f"\n\nActive regulation context: {meta['full']}\n"
            f"Authority: {meta['authority']}\nKey articles: {meta['key_articles']}"
        )
    system = (
        "You are a senior Data Protection Officer and privacy compliance expert with deep expertise in "
        "GDPR, UK GDPR, POPIA, Kenya DPA, Nigeria NDPR, Zimbabwe CDPA, UAE PDPL, Saudi PDPL, "
        "Qatar DPL, PIPEDA, CCPA/CPRA, LGPD, India DPDP, APPI, and other major data protection laws. "
        "You provide accurate, practical, jurisdiction-specific advice. Always cite relevant articles. "
        "Be concise but thorough. If unsure, say so and recommend seeking formal legal advice."
        + reg_context
    )
    # Build conversation history; wrap current user message to prevent injection
    messages = []
    if history:
        for h in history[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": _u(message)})

    provider = _provider()
    try:
        if provider == "anthropic":
            if not _anthropic_key():
                return None, "ANTHROPIC_API_KEY not configured"
            return await _call_anthropic_multi(system, messages, max_tokens=1500), None
        elif provider == "deepseek":
            if not _deepseek_key():
                return None, "DEEPSEEK_API_KEY not configured"
            return await _call_deepseek_multi(system, messages, max_tokens=1500), None
        elif provider == "ollama":
            return await _call_ollama_multi(system, messages, max_tokens=1500), None
        else:
            return await call_ai(system, message, max_tokens=1500)
    except Exception as e:
        return None, str(e)


async def ai_gap_analysis(regulation_from: str, regulation_to: str, activities: str):
    """Perform cross-regulation gap analysis."""
    meta_from = REGULATION_META.get(regulation_from, {})
    meta_to = REGULATION_META.get(regulation_to, {})
    system = (
        "You are a cross-jurisdictional data protection expert. "
        "Identify compliance gaps when expanding from one regulatory framework to another."
    )
    user = f"""Perform a compliance gap analysis:

FROM: {meta_from.get('full', regulation_from)}
TO: {meta_to.get('full', regulation_to)}

Current processing activities: {_u(activities)}

Identify:
1. KEY DIFFERENCES — where {regulation_to} differs from {regulation_from}
2. NEW OBLIGATIONS — what you must now comply with
3. GAP LIST — specific gaps in the current practices for each activity
4. PRIORITY ACTIONS — top 5 actions to become compliant
5. TIMELINE — suggested implementation timeline
6. QUICK WINS — what is already compliant"""
    return await call_ai(system, user, max_tokens=2500)
