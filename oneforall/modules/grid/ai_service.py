"""
GRID module - AI services.

Ported from AuditSphere's ai.js + checklistParser.js.
Provides AI-powered compliance analysis: checklist parsing, gap analysis,
control suggestions, report narrative, and compliance chat.

Uses the unified core.ai_client for multi-provider support
(Anthropic, DeepSeek, Gemini, OpenAI, Ollama).
"""
import io
import json
import re
import csv
from pathlib import Path

from core.ai_client import create_message, is_configured, provider_name, safe_json_parse, wrap_user_input as _u


def _call_ai(messages: list, system: str = "", max_tokens: int = 2000) -> str:
    text = create_message(messages, system=system, max_tokens=max_tokens)
    return re.sub(r"```json|```", "", text).strip()


# ---- AI functions ----

def batch_risk_score(items: list, framework_name: str) -> dict:
    text = _call_ai([{
        "role": "user",
        "content": (
            f"You are a {framework_name} compliance expert. "
            "For each evidence/control item, assign risk level and evidence count.\n\n"
            f"Items: {json.dumps(items)}\n\n"
            "Rules:\n"
            '- risk_level: "Critical" (security boundary, encryption, access control), '
            '"High" (audit logs, vulnerability mgmt), "Medium" (policies, procedures), '
            '"Low" (awareness training, minor admin)\n'
            "- evidence_required: 1-4 integer\n"
            "- evidence_items: 1-3 short strings naming what to collect\n\n"
            "Return ONLY a compact JSON object keyed by the seq field value "
            '(integers as strings):\n'
            '{"1":{"risk_level":"High","evidence_required":2,'
            '"evidence_items":["Policy doc","Approval record"]}}'
        ),
    }], max_tokens=4000)
    parsed = safe_json_parse(text, {})
    return {int(k): v for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def parse_checklist_with_ai(raw_text: str, framework_name: str) -> list:
    text = _call_ai([{
        "role": "user",
        "content": (
            f"Parse this compliance checklist for {framework_name}. "
            f"Extract all control/evidence items.\n{_u(raw_text[:6000])}\n"
            'Return ONLY a JSON array: [{"control_id":"1","name":"Name",'
            '"description":"Desc","risk_level":"High","evidence_required":1,'
            '"evidence_items":["Item"]}]'
        ),
    }], max_tokens=4000)
    parsed = safe_json_parse(text, [])
    if not isinstance(parsed, list):
        raise RuntimeError("AI returned invalid format")
    return parsed


def generate_gap_analysis(controls: list, framework_name: str) -> dict:
    summary = [
        {
            "id": c.get("control_id", ""),
            "name": c.get("name", ""),
            "status": c.get("status", ""),
            "risk": c.get("risk_level", ""),
            "evidence": c.get("evidence_count", 0),
            "required": c.get("evidence_required", 1),
        }
        for c in controls
    ]
    text = _call_ai([{
        "role": "user",
        "content": (
            f"{framework_name} gap analysis for these controls: {json.dumps(summary)}\n"
            'Return ONLY JSON: {"readiness_score":75,"risk_summary":"2-sentence summary",'
            '"critical_gaps":["gap1"],"quick_wins":["win1"],'
            '"recommendations":[{"priority":"High","action":"action","impact":"impact"}],'
            '"estimated_completion":"X weeks"}'
        ),
    }])
    return safe_json_parse(text, {
        "readiness_score": 0,
        "risk_summary": "Analysis unavailable",
        "critical_gaps": [],
        "quick_wins": [],
        "recommendations": [],
    })


def suggest_control_details(control_id: str, name: str, framework_name: str) -> dict:
    text = _call_ai([{
        "role": "user",
        "content": (
            f'{framework_name} control: ID="{control_id}" Name="{name}"\n'
            'Return ONLY JSON: {"description":"2-3 sentences",'
            '"risk_level":"Critical|High|Medium|Low",'
            '"evidence_items":["Item 1","Item 2","Item 3"],'
            '"tips":"One practical tip"}'
        ),
    }])
    return safe_json_parse(text, {
        "description": "",
        "risk_level": "Medium",
        "evidence_items": [],
        "tips": "",
    })


def generate_report_narrative(audit_data: dict) -> dict:
    text = _call_ai([{
        "role": "user",
        "content": (
            "Professional audit report executive summary:\n"
            f"Audit: {audit_data.get('auditName')}, "
            f"Framework: {audit_data.get('framework')}\n"
            f"Completion: {audit_data.get('completionPct', 0)}%, "
            f"Total: {audit_data.get('totalControls', 0)}, "
            f"Complete: {audit_data.get('complete', 0)}, "
            f"Pending: {audit_data.get('pending', 0)}, "
            f"Overdue: {audit_data.get('overdue', 0)}\n"
            f"Audit date: {audit_data.get('auditDate', 'TBD')}, "
            f"Critical gaps: {', '.join(audit_data.get('criticalGaps', [])[:5]) or 'None'}\n"
            'Return ONLY JSON: {"executive_summary":"3-4 sentences",'
            '"overall_status":"On Track|At Risk|Critical",'
            '"key_findings":["f1","f2","f3"],"conclusion":"1-2 sentences"}'
        ),
    }], max_tokens=1500)
    return safe_json_parse(text, {
        "executive_summary": "",
        "overall_status": "In Progress",
        "key_findings": [],
        "conclusion": "",
    })


def ask_compliance_ai(question: str, context: dict | None = None) -> str:
    return _call_ai(
        [{"role": "user", "content": _u(question)}],
        system=(
            "You are G.R.I.D AI's compliance assistant. Help with ISO 27001, "
            "SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, ISO 42001. "
            f"Be concise and practical. Context: {json.dumps(context or {})}"
        ),
        max_tokens=800,
    )


# ---- Checklist parser (Excel / CSV) ----

def _clean(val) -> str:
    if val is None:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()


_COL_MATCHERS = {
    "name": ["evidence name", "control name", "name", "requirement", "title", "evidence"],
    "desc": ["description", "desc", "detail", "requirement description", "control description"],
    "id": ["#", "no", "number", "id", "seq", "item", "ref", "sr no", "sl no"],
    "applicable": ["applicable", "applicability", "in scope"],
    "note": ["comment", "auditor", "remark", "note", "observation"],
}


def _detect_columns(header_row: list, data_rows: list) -> dict:
    idx = {}
    lower_headers = [str(h or "").lower().strip() for h in header_row]
    for key, patterns in _COL_MATCHERS.items():
        for i, h in enumerate(lower_headers):
            if any(p in h for p in patterns):
                if key not in idx:
                    idx[key] = i
    if data_rows and len(data_rows) > 0:
        first_val = str(data_rows[0][0] if data_rows[0] else "")
        if first_val.isdigit():
            idx.setdefault("id", 0)
    return idx


def _extract_rows_from_excel(file_bytes: bytes) -> list:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    results = []

    for ws in wb.worksheets:
        rows_data = []
        for row in ws.iter_rows(values_only=True):
            rows_data.append(list(row))
        if len(rows_data) < 2:
            continue

        col_idx = _detect_columns(rows_data[0], rows_data[1:])
        name_col = col_idx.get("name", 1)
        desc_col = col_idx.get("desc", 2)
        id_col = col_idx.get("id", 0)
        app_col = col_idx.get("applicable", 4)
        note_col = col_idx.get("note", 7)

        for i in range(1, len(rows_data)):
            row = rows_data[i]

            def safe_get(idx):
                return row[idx] if idx < len(row) else None

            raw_id = safe_get(id_col)
            name = _clean(safe_get(name_col))
            desc = _clean(safe_get(desc_col))

            if not name and not desc:
                continue
            if name.lower().startswith("evidence name") and i < 5:
                continue

            results.append({
                "seq": len(results) + 1,
                "raw_id": str(raw_id) if raw_id not in (None, "") else str(len(results) + 1),
                "name": name[:200],
                "description": desc[:400],
                "applicable": _clean(safe_get(app_col)).lower(),
                "note": _clean(safe_get(note_col))[:150],
                "sheet": ws.title,
            })

    wb.close()
    return results


def _extract_rows_from_csv(file_bytes: bytes) -> list:
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows_data = [row for row in reader]
    if len(rows_data) < 2:
        return []

    col_idx = _detect_columns(rows_data[0], rows_data[1:])
    name_col = col_idx.get("name", 1)
    desc_col = col_idx.get("desc", 2)
    id_col = col_idx.get("id", 0)
    app_col = col_idx.get("applicable", 4)
    note_col = col_idx.get("note", 7)

    results = []
    for i in range(1, len(rows_data)):
        row = rows_data[i]

        def safe_get(idx):
            return row[idx] if idx < len(row) else None

        name = _clean(safe_get(name_col))
        desc = _clean(safe_get(desc_col))
        if not name and not desc:
            continue

        raw_id = safe_get(id_col)
        results.append({
            "seq": len(results) + 1,
            "raw_id": str(raw_id) if raw_id not in (None, "") else str(len(results) + 1),
            "name": name[:200],
            "description": desc[:400],
            "applicable": _clean(safe_get(app_col)).lower(),
            "note": _clean(safe_get(note_col))[:150],
            "sheet": "csv",
        })
    return results


def _score_risks_in_batches(rows: list, framework_name: str) -> list:
    BATCH = 40
    scored = []

    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        payload = [
            {"seq": r["seq"], "n": r["name"][:100], "d": r["description"][:120]}
            for r in batch
        ]

        try:
            risk_map = batch_risk_score(payload, framework_name)
        except Exception:
            risk_map = {
                r["seq"]: {"risk_level": "Medium", "evidence_required": 1, "evidence_items": []}
                for r in batch
            }

        for row in batch:
            risk = risk_map.get(row["seq"], {})
            scored.append({
                "control_id": row["raw_id"],
                "name": row["name"],
                "description": row["description"] or row["note"],
                "risk_level": risk.get("risk_level", "Medium"),
                "evidence_required": risk.get("evidence_required", 1),
                "evidence_items": risk.get("evidence_items", [row["name"]]),
                "applicable": row["applicable"],
            })

    return scored


def parse_checklist_file(
    file_bytes: bytes,
    framework_name: str = "ISO 27001",
    skip_ai: bool = False,
    extension: str = "",
) -> list:
    ext = extension.lower()
    rows = []

    if ext in (".xlsx", ".xls", ".xlsm", ""):
        try:
            rows = _extract_rows_from_excel(file_bytes)
        except Exception:
            if ext == "":
                try:
                    rows = _extract_rows_from_csv(file_bytes)
                except Exception:
                    raise RuntimeError("Could not parse file. Upload as .xlsx or .csv")
            else:
                raise
    elif ext in (".csv", ".tsv", ".txt"):
        rows = _extract_rows_from_csv(file_bytes)
    elif ext == ".pdf":
        raise RuntimeError("PDF checklists not supported. Export to Excel or CSV.")
    else:
        raise RuntimeError(f'Unsupported file type "{ext}". Upload .xlsx, .xls, or .csv')

    if not rows:
        raise RuntimeError("No data rows found. Check that the file has a header row and data.")

    applicable = [
        r for r in rows
        if "not applicable" not in r["applicable"] or len(r["name"]) > 5
    ]

    if skip_ai:
        return [
            {
                "control_id": r["raw_id"],
                "name": r["name"],
                "description": r["description"],
                "risk_level": "Medium",
                "evidence_required": 1,
                "evidence_items": [r["name"]],
            }
            for r in applicable
        ]

    return _score_risks_in_batches(applicable, framework_name)


# ---- AI Post-Incident Checklist ----

def generate_incident_checklist(
    incident: dict,
    regulations: list[str] | None = None,
    policies: list[str] | None = None,
) -> list[dict]:
    """Generate a post-incident closure checklist based on the incident details.

    Returns a list of checklist items, each with:
      - category (Containment / Notification / Investigation / Remediation / Documentation / Recovery)
      - name (short task title)
      - description (what needs to be verified)
      - evidence_required (list of evidence item names needed)
      - policy_ref (suggested ARIA policy that governs this item, if any)
    """
    if not is_configured():
        return _stub_incident_checklist(incident)

    reg_ctx = ""
    if regulations:
        reg_ctx = f"\nActive regulatory frameworks: {', '.join(regulations)}. Reference these specifically."
    pol_ctx = ""
    if policies:
        pol_ctx = (
            f"\nAvailable ARIA policies: {', '.join(policies[:30])}. "
            "For each checklist item, suggest which of these policies governs it in the policy_ref field. "
            "Use the exact policy name from this list when matching, or leave policy_ref empty if none match."
        )

    prompt = (
        "You are an incident response and audit expert. Given the incident below, "
        "generate a post-incident closure checklist of 8-15 items that an auditor must "
        "verify before the post-incident audit can be signed off.\n\n"
        "Group items into these categories: Containment, Notification, Investigation, "
        "Remediation, Documentation, Recovery.\n\n"
        f"Incident title: {_u(incident.get('title', 'Unknown'))}\n"
        f"Type: {_u(incident.get('type', incident.get('breach_type', 'Unknown')))}\n"
        f"Severity: {_u(incident.get('severity', 'Unknown'))}\n"
        f"Description: {_u(incident.get('description', ''))}\n"
        f"Data types affected: {_u(incident.get('data_types', ''))}\n"
        f"Affected count: {incident.get('affected_count', 'Unknown')}\n"
        f"Cause: {_u(incident.get('cause', ''))}\n"
        f"{reg_ctx}{pol_ctx}\n\n"
        "Respond in JSON array. Each item:\n"
        '{"category":"...","name":"short task title","description":"what to verify",'
        '"evidence_required":["evidence item 1","evidence item 2"],'
        '"policy_ref":"matching ARIA policy name or empty string"}'
    )

    try:
        text = _call_ai([{"role": "user", "content": prompt}], max_tokens=3000)
        items = safe_json_parse(text, None)
        if isinstance(items, list) and items:
            return items
    except Exception:
        pass
    return _stub_incident_checklist(incident)


def _stub_incident_checklist(incident: dict) -> list[dict]:
    """Fallback checklist when AI is not configured."""
    severity = (incident.get("severity") or "high").lower()
    inc_type = (incident.get("type") or incident.get("breach_type") or "data_breach").lower()

    items = [
        {"category": "Containment", "name": "Affected systems isolated",
         "description": "Confirm all compromised or affected systems were identified and isolated to prevent further exposure.",
         "evidence_required": ["Isolation confirmation log", "Network segment change records"],
         "policy_ref": ""},
        {"category": "Containment", "name": "Compromised access revoked",
         "description": "Verify that all potentially compromised user accounts, API keys, and access credentials were revoked or reset.",
         "evidence_required": ["Credential reset confirmation", "Access audit log"],
         "policy_ref": ""},
        {"category": "Notification", "name": "Data Protection Authority notified",
         "description": "Confirm the relevant Data Protection Authority was notified within the required statutory timeframe.",
         "evidence_required": ["DPA notification letter", "Submission receipt or timestamp"],
         "policy_ref": ""},
        {"category": "Notification", "name": "Affected individuals notified",
         "description": "Verify that all affected data subjects were informed of the breach, its potential impact, and steps they should take.",
         "evidence_required": ["Notification letter template", "Distribution log"],
         "policy_ref": ""},
        {"category": "Investigation", "name": "Root cause analysis completed",
         "description": "Confirm a thorough root cause analysis was conducted identifying how the incident occurred and what controls failed.",
         "evidence_required": ["Root cause analysis report"],
         "policy_ref": ""},
        {"category": "Investigation", "name": "Impact assessment finalised",
         "description": "Verify the full scope and impact of the incident has been assessed, including affected data types, volumes, and potential harm.",
         "evidence_required": ["Impact assessment report", "Data inventory of affected records"],
         "policy_ref": ""},
        {"category": "Remediation", "name": "Vulnerability or control gap remediated",
         "description": "Confirm the specific vulnerability, process failure, or control gap that caused the incident has been fixed and tested.",
         "evidence_required": ["Change request record", "Test results or validation report"],
         "policy_ref": ""},
        {"category": "Remediation", "name": "Security controls strengthened",
         "description": "Verify that additional preventive controls have been implemented to reduce the likelihood of recurrence.",
         "evidence_required": ["Updated control documentation", "Implementation evidence"],
         "policy_ref": ""},
        {"category": "Documentation", "name": "Incident register updated",
         "description": "Confirm the breach or incident register has been updated with all relevant details, timeline, and outcomes.",
         "evidence_required": ["Updated incident register entry"],
         "policy_ref": ""},
        {"category": "Documentation", "name": "Lessons learned documented",
         "description": "Verify a lessons learned report has been prepared and shared with relevant stakeholders.",
         "evidence_required": ["Lessons learned report", "Meeting minutes from review session"],
         "policy_ref": ""},
        {"category": "Recovery", "name": "Normal operations restored",
         "description": "Confirm that all affected services and systems have been fully restored to normal operation.",
         "evidence_required": ["Service restoration confirmation", "System health check results"],
         "policy_ref": ""},
        {"category": "Recovery", "name": "Post-incident monitoring in place",
         "description": "Verify that enhanced monitoring has been established for the affected systems to detect any further issues.",
         "evidence_required": ["Monitoring configuration evidence", "Alert threshold documentation"],
         "policy_ref": ""},
    ]

    if severity == "critical":
        items.append({
            "category": "Notification",
            "name": "Board or executive management briefed",
            "description": "Confirm the board or senior management received a formal briefing on the incident, its impact, and the response.",
            "evidence_required": ["Board briefing document", "Meeting minutes"],
            "policy_ref": "",
        })

    return items
