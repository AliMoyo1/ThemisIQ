"""
GRID module — AI services.

Ported from AuditSphere's ai.js + checklistParser.js.
Provides Claude-powered compliance analysis: checklist parsing, gap analysis,
control suggestions, report narrative, and compliance chat.
"""
import io
import json
import os
import re
import csv
from pathlib import Path

import anthropic


# ═════════════════════════════════════════════════════════════════════════════
# Claude helpers
# ═════════════════════════════════════════════════════════════════════════════

def _get_client() -> anthropic.Anthropic:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key or key.startswith("your-"):
        raise RuntimeError(
            "API key not set — set ANTHROPIC_API_KEY=sk-ant-... in your environment."
        )
    return anthropic.Anthropic(api_key=key)


def _friendly_error(err: Exception) -> str:
    msg = str(err)
    if "authentication_error" in msg or "invalid x-api-key" in msg:
        return "Invalid Anthropic API key. Check ANTHROPIC_API_KEY."
    if "rate_limit" in msg or "429" in msg:
        return "Rate limit reached. Wait a moment and try again."
    if "overloaded" in msg:
        return "Anthropic API is temporarily overloaded. Please try again."
    return msg


def call_claude(messages: list, system: str | None = None, max_tokens: int = 2000) -> str:
    """Call Claude and return stripped text (no markdown fences)."""
    client = _get_client()
    opts = dict(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=messages,
    )
    if system:
        opts["system"] = system
    try:
        resp = client.messages.create(**opts)
        text = resp.content[0].text.strip()
        return re.sub(r"```json|```", "", text).strip()
    except Exception as err:
        raise RuntimeError(_friendly_error(err))


def _safe_parse_json(text: str, fallback=None):
    """Lenient JSON parser — tries direct parse, then regex extraction."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting array
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    # Try extracting object
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return fallback


# ═════════════════════════════════════════════════════════════════════════════
# AI functions
# ═════════════════════════════════════════════════════════════════════════════

def batch_risk_score(items: list, framework_name: str) -> dict:
    """Score a batch of controls with risk levels and evidence requirements."""
    text = call_claude([{
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

    parsed = _safe_parse_json(text, {})
    return {int(k): v for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def parse_checklist_with_ai(raw_text: str, framework_name: str) -> list:
    """Legacy fallback: parse plain-text checklist via AI."""
    text = call_claude([{
        "role": "user",
        "content": (
            f"Parse this compliance checklist for {framework_name}. "
            f"Extract all control/evidence items.\n{raw_text[:6000]}\n"
            'Return ONLY a JSON array: [{"control_id":"1","name":"Name",'
            '"description":"Desc","risk_level":"High","evidence_required":1,'
            '"evidence_items":["Item"]}]'
        ),
    }], max_tokens=4000)
    parsed = _safe_parse_json(text, [])
    if not isinstance(parsed, list):
        raise RuntimeError("AI returned invalid format")
    return parsed


def generate_gap_analysis(controls: list, framework_name: str) -> dict:
    """Analyse compliance gaps across controls."""
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
    text = call_claude([{
        "role": "user",
        "content": (
            f"{framework_name} gap analysis for these controls: {json.dumps(summary)}\n"
            'Return ONLY JSON: {"readiness_score":75,"risk_summary":"2-sentence summary",'
            '"critical_gaps":["gap1"],"quick_wins":["win1"],'
            '"recommendations":[{"priority":"High","action":"action","impact":"impact"}],'
            '"estimated_completion":"X weeks"}'
        ),
    }])
    return _safe_parse_json(text, {
        "readiness_score": 0,
        "risk_summary": "Analysis unavailable",
        "critical_gaps": [],
        "quick_wins": [],
        "recommendations": [],
    })


def suggest_control_details(control_id: str, name: str, framework_name: str) -> dict:
    """Suggest description, risk level, and evidence items for a control."""
    text = call_claude([{
        "role": "user",
        "content": (
            f'{framework_name} control: ID="{control_id}" Name="{name}"\n'
            'Return ONLY JSON: {"description":"2-3 sentences",'
            '"risk_level":"Critical|High|Medium|Low",'
            '"evidence_items":["Item 1","Item 2","Item 3"],'
            '"tips":"One practical tip"}'
        ),
    }])
    return _safe_parse_json(text, {
        "description": "",
        "risk_level": "Medium",
        "evidence_items": [],
        "tips": "",
    })


def generate_report_narrative(audit_data: dict) -> dict:
    """Generate executive summary for an audit report."""
    text = call_claude([{
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
    return _safe_parse_json(text, {
        "executive_summary": "",
        "overall_status": "In Progress",
        "key_findings": [],
        "conclusion": "",
    })


def ask_compliance_ai(question: str, context: dict | None = None) -> str:
    """Compliance assistant chat."""
    return call_claude(
        [{"role": "user", "content": question}],
        system=(
            "You are G.R.I.D AI's compliance assistant. Help with ISO 27001, "
            "SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, ISO 42001. "
            f"Be concise and practical. Context: {json.dumps(context or {})}"
        ),
        max_tokens=800,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Checklist parser (Excel / CSV)
# ═════════════════════════════════════════════════════════════════════════════

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
    # First column numeric in first data row → ID column
    if data_rows and len(data_rows) > 0:
        first_val = str(data_rows[0][0] if data_rows[0] else "")
        if first_val.isdigit():
            idx.setdefault("id", 0)
    return idx


def _extract_rows_from_excel(file_bytes: bytes) -> list:
    """Extract rows from Excel file using openpyxl."""
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
    """Extract rows from CSV/TXT file."""
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
    """Send batches of 40 rows to Claude for risk scoring."""
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
            # Fallback: assign Medium risk
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
    """
    Main entry point: parse a checklist file (Excel, CSV, TXT) and optionally
    score risks via AI in batches.
    """
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
        raise RuntimeError("PDF checklists not supported — export to Excel or CSV.")
    else:
        raise RuntimeError(f'Unsupported file type "{ext}". Upload .xlsx, .xls, or .csv')

    if not rows:
        raise RuntimeError("No data rows found. Check that the file has a header row and data.")

    # Filter not-applicable rows
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
