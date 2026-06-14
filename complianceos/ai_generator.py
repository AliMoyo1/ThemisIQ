"""
ai_generator.py — AI Policy Generator for ARIA
Uses Anthropic Claude API to generate professional compliance policy documents
"""
import os, httpx, json

CLAUDE_MODEL = "claude-sonnet-4-20250514"

def get_api_key() -> str:
    """Read API key from environment variable or .env file directly."""
    # 1. Check environment variable first (set via 'set' command or system env)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # 2. Manually parse .env file - handles encoding issues
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    if key:
                        return key
    except Exception:
        pass
    return ""

FRAMEWORK_CONTEXT = {
    "ISO 27001": {
        "full_name": "ISO/IEC 27001:2022 Information Security Management System",
        "audience": "information security team, IT management, and all staff",
        "tone": "formal, risk-based, aligned with ISO management system structure",
        "structure_note": "Follow ISO 27001 Annex A control objectives. Include purpose, scope, policy statements, roles & responsibilities, and review cycle.",
        "org_type": "any organisation implementing an ISMS"
    },
    "ISO 42001": {
        "full_name": "ISO/IEC 42001:2023 Artificial Intelligence Management System",
        "audience": "AI development teams, data scientists, senior management, and governance functions",
        "tone": "forward-looking, ethics-conscious, technically aware, governance-focused",
        "structure_note": "Address AI-specific risks including bias, transparency, human oversight, and responsible AI principles.",
        "org_type": "organisations developing, deploying, or using AI systems"
    },
    "SOC 2 Type II": {
        "full_name": "SOC 2 Type II — Trust Services Criteria (AICPA)",
        "audience": "security and compliance team, service organisation personnel",
        "tone": "precise, audit-ready, control-focused, suitable for external review",
        "structure_note": "Written to satisfy SOC 2 Trust Services Criteria. Include control objectives, control activities, and monitoring requirements.",
        "org_type": "service organisations handling customer data"
    },
    "PCI DSS": {
        "full_name": "Payment Card Industry Data Security Standard v4.0",
        "audience": "IT security team, payment processing staff, merchants and service providers",
        "tone": "prescriptive, technically detailed, compliance-driven",
        "structure_note": "Reference specific PCI DSS requirements. Include cardholder data environment (CDE) scope where relevant. Be specific about technical controls.",
        "org_type": "organisations that store, process, or transmit cardholder data"
    },
    "GDPR": {
        "full_name": "General Data Protection Regulation (EU) 2016/679",
        "audience": "data protection officer, legal team, all staff handling personal data",
        "tone": "legally precise, rights-focused, data subject-centric",
        "structure_note": "Reference specific GDPR articles. Include lawful basis, data subject rights, controller obligations, and documentation requirements.",
        "org_type": "organisations processing personal data of EU/EEA data subjects"
    },
    "Zimbabwe CDPA": {
        "full_name": "Zimbabwe Cyber and Data Protection Act [Chapter 12:07]",
        "audience": "data protection officer, management, all staff handling personal information",
        "tone": "legally precise, locally contextualised for Zimbabwe, rights-focused",
        "structure_note": "Reference specific sections of the Zimbabwe CDPA. Align with POTRAZ regulatory requirements. Consider the Zimbabwean business and regulatory context.",
        "org_type": "organisations operating in Zimbabwe that process personal information"
    },
    "HIPAA": {
        "full_name": "Health Insurance Portability and Accountability Act (HIPAA)",
        "audience": "healthcare workforce, privacy and security officers, business associates",
        "tone": "medically-contextualised, legally precise, patient-rights focused",
        "structure_note": "Reference specific HIPAA Rules (Privacy, Security, Breach Notification). Address PHI/ePHI specifically. Include workforce training requirements.",
        "org_type": "covered entities and business associates handling protected health information"
    }
}

POLICY_SYSTEM_PROMPT = """You are a senior GRC (Governance, Risk and Compliance) consultant and policy writer with 15+ years of experience writing professional compliance documentation. You specialise in information security, data protection, and regulatory compliance across multiple frameworks.

Your task is to write a complete, professional compliance policy or procedure document. Your output must be:

1. PROFESSIONAL — Written at the standard of a Big 4 consulting firm or enterprise compliance team
2. SPECIFIC — Tailored to the exact framework and control, not generic
3. ACTIONABLE — Contains clear, implementable requirements
4. COMPLETE — Covers all necessary sections for the document type
5. AUDIT-READY — Written to satisfy an external auditor reviewing this document

Format your response using clean Markdown. Use the following structure:

# [Document Title]

**Document Reference:** [Framework]-[Control Ref]-[DOC TYPE]-001  
**Version:** 1.0  
**Classification:** Internal  
**Review Cycle:** Annual  

---

## 1. Purpose
[Clear statement of why this document exists]

## 2. Scope
[Who and what this applies to]

## 3. Policy Statement / Procedure Overview
[The core content — this should be the most detailed section]

## 4. Roles & Responsibilities
[Who is responsible for what]

## 5. Requirements / Procedures
[Detailed requirements, steps, or controls — use numbered lists for procedures]

## 6. Compliance & Enforcement
[Consequences of non-compliance, monitoring approach]

## 7. Related Documents
[List of related policies, standards, and procedures]

## 8. Review & Approval
[Review cycle, approval authority]

---
*This document was generated as a draft. It must be reviewed, customised to your organisation, and formally approved before use.*

Write the full document. Do not truncate or summarise — produce the complete text."""


async def generate_policy(framework: str, control_ref: str, control_name: str,
                           control_description: str, doc_type: str,
                           org_name: str = "Your Organisation") -> dict:
    """
    Call Claude API to generate a compliance policy document.
    Returns dict with 'content' (markdown) and 'tokens_used'.
    """
    ANTHROPIC_API_KEY = get_api_key()
    if not ANTHROPIC_API_KEY:
        return {
            "success": False,
            "error": "ANTHROPIC_API_KEY not configured. Please add it to your .env file.",
            "content": ""
        }

    fw_ctx = FRAMEWORK_CONTEXT.get(framework, {
        "full_name": framework,
        "audience": "all relevant staff",
        "tone": "professional and clear",
        "structure_note": "Include purpose, scope, policy statements, and review cycle.",
        "org_type": "the organisation"
    })

    user_prompt = f"""Please write a complete {doc_type} document for the following compliance requirement:

**Framework:** {fw_ctx['full_name']}
**Control Reference:** {control_ref}
**Control Name:** {control_name}
**Control Description:** {control_description}
**Document Type:** {doc_type}
**Organisation:** {org_name}
**Target Audience:** {fw_ctx['audience']}

**Writing Guidelines:**
- Tone: {fw_ctx['tone']}
- Structure Note: {fw_ctx['structure_note']}
- This document is for: {fw_ctx['org_type']}
- Organisation name placeholder: use "{org_name}" throughout

Write the complete {doc_type} document now. Make it thorough, professional, and immediately usable as a working draft."""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 4000,
                    "system": POLICY_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}]
                }
            )

        if response.status_code != 200:
            err = response.json()
            return {
                "success": False,
                "error": f"API error {response.status_code}: {err.get('error', {}).get('message', 'Unknown error')}",
                "content": ""
            }

        data = response.json()
        content = data["content"][0]["text"]
        tokens = data.get("usage", {})

        return {
            "success": True,
            "content": content,
            "input_tokens": tokens.get("input_tokens", 0),
            "output_tokens": tokens.get("output_tokens", 0),
            "model": CLAUDE_MODEL
        }

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again.", "content": ""}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "content": ""}


async def generate_gap_analysis(framework: str, controls_data: list) -> dict:
    """
    Generate a gap analysis summary for a framework based on current control statuses.
    """
    ANTHROPIC_API_KEY = get_api_key()
    if not ANTHROPIC_API_KEY:
        return {"success": False, "error": "API key not configured", "content": ""}

    not_started = [c for c in controls_data if c["status"] == "Not Started"]
    in_progress = [c for c in controls_data if c["status"] == "In Progress"]
    implemented = [c for c in controls_data if c["status"] == "Implemented"]
    total = len(controls_data)
    pct = round(len(implemented) / total * 100, 1) if total > 0 else 0

    gaps_text = "\n".join([f"- [{c['ref']}] {c['name']}: {c['status']}" for c in not_started[:20]])

    prompt = f"""You are a senior GRC consultant. Based on the following {framework} compliance data, write a concise Gap Analysis Report.

**Framework:** {framework}
**Total Controls:** {total}
**Implemented:** {len(implemented)} ({pct}%)
**In Progress:** {len(in_progress)}
**Not Started (Gaps):** {len(not_started)}

**Top Gaps (Not Started):**
{gaps_text}

Write a professional Gap Analysis Report with:
1. Executive Summary (3-4 sentences on overall compliance posture)
2. Key Findings (top 5 most critical gaps with risk context)
3. Priority Recommendations (what to tackle first and why)
4. Suggested Roadmap (30/60/90 day actions)

Keep it concise but actionable. Write for a CISO or Compliance Manager audience."""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
        data = response.json()
        return {"success": True, "content": data["content"][0]["text"]}
    except Exception as e:
        return {"success": False, "error": str(e), "content": ""}
