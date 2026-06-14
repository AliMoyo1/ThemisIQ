"""
DPIAforge — AI service abstraction layer.
Supports Anthropic, OpenAI and Google Gemini via .env config.
Falls back to pure HTTP (requests) so no SDK install required.
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

AI_PROVIDER   = os.getenv("AI_PROVIDER", "anthropic").lower()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MDL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MDL    = os.getenv("OPENAI_MODEL", "gpt-4o")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
GEMINI_MDL    = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")


# ── low-level call ────────────────────────────────────────────────────────────

def _call_anthropic(system: str, user: str, max_tokens=4096) -> str:
    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MDL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=120)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _call_openai(system: str, user: str, max_tokens=4096) -> str:
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": OPENAI_MDL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_gemini(system: str, user: str, max_tokens=4096) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MDL}:generateContent?key={GEMINI_KEY}"
    body = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = requests.post(url, json=body, timeout=120)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def call_ai(system: str, user: str, max_tokens=4096) -> tuple[str | None, str | None]:
    """Returns (text, error_message)."""
    try:
        if AI_PROVIDER == "anthropic":
            if not ANTHROPIC_KEY:
                return None, "ANTHROPIC_API_KEY not set in .env"
            return _call_anthropic(system, user, max_tokens), None
        elif AI_PROVIDER == "openai":
            if not OPENAI_KEY:
                return None, "OPENAI_API_KEY not set in .env"
            return _call_openai(system, user, max_tokens), None
        elif AI_PROVIDER == "gemini":
            if not GEMINI_KEY:
                return None, "GEMINI_API_KEY not set in .env"
            return _call_gemini(system, user, max_tokens), None
        else:
            return None, f"Unknown AI_PROVIDER: {AI_PROVIDER}"
    except requests.HTTPError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = e.response.text[:500]
        return None, f"API error {e.response.status_code}: {detail}"
    except Exception as e:
        return None, str(e)


# ── regulation context ────────────────────────────────────────────────────────

REGULATION_META = {
    "GDPR": {
        "full": "EU General Data Protection Regulation (GDPR) 2016/679",
        "authority": "relevant EU Data Protection Authority (DPA)",
        "key_articles": "Arts. 35–36 (DPIA), Art. 5 (principles), Art. 6 (lawful basis), Art. 9 (special categories)",
        "thresholds": "systematic monitoring, large-scale special-category data, public area monitoring",
    },
    "Zimbabwe CDPA": {
        "full": "Zimbabwe Cyber and Data Protection Act [Chapter 12:07] (2021)",
        "authority": "Postal and Telecommunications Regulatory Authority (POTRAZ)",
        "key_articles": "Part III (data protection principles), s. 20+ (controller obligations)",
        "thresholds": "processing of sensitive personal information, automated decisions",
    },
    "South Africa POPIA": {
        "full": "South Africa Protection of Personal Information Act 4 of 2013 (POPIA)",
        "authority": "Information Regulator (South Africa)",
        "key_articles": "s. 22 (PIA), Conditions 1–8, s. 26 (special categories)",
        "thresholds": "high-risk processing, sensitive personal information, children's data",
    },
    "UAE PDPL": {
        "full": "UAE Federal Decree-Law No. 45 of 2021 on Personal Data Protection",
        "authority": "UAE Data Office",
        "key_articles": "Art. 16 (impact assessment), Arts. 4–8 (processing conditions), Art. 22 (sensitive data)",
        "thresholds": "sensitive personal data, new technologies, systematic processing",
    },
    "Saudi PDPL": {
        "full": "Saudi Arabia Personal Data Protection Law (Royal Decree M/19, 2021)",
        "authority": "National Data Management Office (NDMO) / Saudi Data and AI Authority (SDAIA)",
        "key_articles": "Art. 29 (impact assessment), Arts. 4–7 (data processing rules), Art. 23 (sensitive data)",
        "thresholds": "sensitive data, cross-border transfers, automated decision-making",
    },
    "Qatar DPL": {
        "full": "Qatar Personal Data Privacy Protection Law No. 13 of 2016",
        "authority": "Ministry of Transport and Communications (MOTC)",
        "key_articles": "Arts. 4–6 (controller obligations), Art. 17 (sensitive data), cross-border transfer rules",
        "thresholds": "special category data, large-scale processing, systematic surveillance",
    },
}


# ── AI tasks ──────────────────────────────────────────────────────────────────

def ai_research(activity_type: str, regulation: str, context: str = "") -> tuple:
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a senior Data Protection Officer and privacy lawyer. "
        "You produce detailed, accurate, professionally-worded DPIA research reports. "
        "Always cite the relevant legal articles/sections. Be thorough and practical."
    )
    user = f"""Conduct a DPIA preliminary research report for the following:

Processing Activity: {activity_type}
Regulation: {meta.get('full', regulation)}
Supervisory Authority: {meta.get('authority', 'N/A')}
Key Legal Provisions: {meta.get('key_articles', 'N/A')}
DPIA Triggers: {meta.get('thresholds', 'N/A')}
{f'Additional Context: {context}' if context else ''}

Write a structured research report covering:
1. Nature and scope of this processing activity
2. Why a DPIA is required under {regulation}
3. Applicable legal bases and conditions
4. Typical personal data involved (categories & special categories)
5. Common privacy risks for this activity type
6. Recommended technical and organisational safeguards
7. Relevant regulatory guidance or precedents
8. Data subject rights implications

Be specific, cite the law, and make this immediately useful for completing the DPIA."""
    return call_ai(system, user, max_tokens=3000)


def ai_generate_full_dpia(dpia: dict) -> tuple:
    regulation = dpia.get("regulation", "GDPR")
    meta = REGULATION_META.get(regulation, {})
    system = (
        "You are a senior DPO and privacy counsel. "
        "Generate a complete, legally rigorous Data Protection Impact Assessment document. "
        "Write in formal, professional language suitable for regulatory submission. "
        "Be comprehensive, specific, and cite the relevant law throughout."
    )
    cats = ", ".join(dpia.get("data_categories", [])) or "Not specified"
    scats = ", ".join(dpia.get("special_cats", [])) or "None"
    user = f"""Generate a complete DPIA document under {meta.get('full', regulation)}.

=== DPIA DETAILS ===
Reference: {dpia.get('ref_number')}
Title: {dpia.get('title')}
Organisation: {dpia.get('org_name')} | Dept: {dpia.get('department')}
Data Controller: {dpia.get('controller_name')} | DPO: {dpia.get('dpo_name')}
Processing Activity: {dpia.get('activity_type')}
Purpose: {dpia.get('purpose')}
Legal Basis: {dpia.get('legal_basis')}
Data Categories: {cats}
Special Categories: {scats}
Data Subjects: {dpia.get('data_subjects')} (~{dpia.get('subject_count')} individuals)
Retention: {dpia.get('retention')}
Systems: {dpia.get('systems')}
Third-party Processors: {dpia.get('processors')}
International Transfers: {dpia.get('intl_transfer')} → {dpia.get('transfer_dest')} via {dpia.get('transfer_mech')}
Necessity Notes: {dpia.get('necessity')}
Proportionality Notes: {dpia.get('proportionality')}
Overall Risk: {dpia.get('overall_risk')} | Residual Risk: {dpia.get('residual_risk')}
DPO Consulted: {dpia.get('dpo_consulted')} | Authority Consulted: {dpia.get('auth_consulted')}
Consultation Notes: {dpia.get('consult_notes')}

=== REGULATION ===
Full Name: {meta.get('full', regulation)}
Supervisory Authority: {meta.get('authority')}
Key Articles: {meta.get('key_articles')}

Write the full DPIA document with these sections:

# EXECUTIVE SUMMARY

## 1. DESCRIPTION OF PROCESSING
### 1.1 Nature of Processing
### 1.2 Scope
### 1.3 Context
### 1.4 Purposes

## 2. LEGAL BASIS FOR PROCESSING
### 2.1 Lawful Basis Analysis
### 2.2 Compliance Assessment

## 3. NECESSITY & PROPORTIONALITY
### 3.1 Necessity
### 3.2 Proportionality
### 3.3 Data Minimisation

## 4. DATA SUBJECT RIGHTS
### 4.1 Applicable Rights Under {regulation}
### 4.2 Mechanisms for Rights Exercise

## 5. RISK ASSESSMENT
### 5.1 Identified Risks
### 5.2 Likelihood & Severity Analysis
### 5.3 Overall Risk Rating

## 6. RISK MITIGATION MEASURES
### 6.1 Technical Measures
### 6.2 Organisational Measures
### 6.3 Legal/Contractual Measures

## 7. RESIDUAL RISK ASSESSMENT

## 8. CONSULTATION
### 8.1 DPO Consultation
### 8.2 Supervisory Authority Consultation
### 8.3 Data Subject Consultation

## 9. CONCLUSION & DECISION
### 9.1 Overall Assessment
### 9.2 Decision
### 9.3 Conditions & Recommendations

Each section must be fully written, specific to this processing activity, and cite {regulation} articles/sections."""
    return call_ai(system, user, max_tokens=6000)


def ai_suggest_risks(activity: str, regulation: str, categories: list) -> tuple:
    """Returns (list_of_risks, error)."""
    cats = ", ".join(categories) if categories else "general personal data"
    system = (
        "You are a privacy risk expert. Return ONLY valid JSON, no markdown, no explanation."
    )
    user = f"""For processing activity "{activity}" under {regulation} involving {cats},
return a JSON array of 5 risks in this exact format:
[
  {{
    "desc": "Short risk description",
    "likelihood": "High|Medium|Low",
    "impact": "High|Medium|Low",
    "mitigation": "Recommended mitigation measure"
  }}
]"""
    text, err = call_ai(system, user, max_tokens=800)
    if err:
        return None, err
    try:
        # Strip possible code fences
        clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean), None
    except Exception as e:
        return None, f"JSON parse error: {e} — raw: {text[:200]}"
