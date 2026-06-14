"""
DPIAforge — Flask application entry point.
"""
import os
import json
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, abort
)
from dotenv import load_dotenv

load_dotenv()

import database as db
from ai_service import ai_research, ai_generate_full_dpia, ai_suggest_risks
from docx_export import generate_docx

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dpiaforge-dev-secret")


# ── init DB on first run ─────────────────────────────────────────────────────
with app.app_context():
    db.init_db()


# ═══════════════════════════════════════════════════════════════════════════════
# DROPDOWN REFERENCE DATA
# ═══════════════════════════════════════════════════════════════════════════════

REGULATIONS = [
    ("GDPR",               "GDPR — EU General Data Protection Regulation"),
    ("Zimbabwe CDPA",      "Zimbabwe Cyber & Data Protection Act"),
    ("South Africa POPIA", "South Africa POPIA"),
    ("UAE PDPL",           "UAE Personal Data Protection Law"),
    ("Saudi PDPL",         "Saudi Personal Data Protection Law"),
    ("Qatar DPL",          "Qatar Data Protection Law"),
]

ACTIVITY_TYPES = [
    "Biometric data processing",
    "CCTV / video surveillance",
    "Children's data processing",
    "Credit scoring / financial profiling",
    "Customer analytics & profiling",
    "Employee monitoring",
    "Fraud detection / prevention",
    "Health data processing",
    "Identity verification (KYC/AML)",
    "IoT / smart device data collection",
    "Location tracking",
    "Marketing & direct communications",
    "Mobile app data collection",
    "Online behavioural advertising",
    "Payroll & HR data processing",
    "Recruitment & background checks",
    "Research & statistical analysis",
    "Social media monitoring",
    "Third-party data sharing",
    "Automated decision-making / AI",
    "Cloud migration of personal data",
    "Cross-border data transfers",
    "Criminal record processing",
    "Loyalty programme management",
    "Other (describe below)",
]

LEGAL_BASES = {
    "GDPR": [
        "Consent — Art. 6(1)(a)",
        "Contract performance — Art. 6(1)(b)",
        "Legal obligation — Art. 6(1)(c)",
        "Vital interests — Art. 6(1)(d)",
        "Public task — Art. 6(1)(e)",
        "Legitimate interests — Art. 6(1)(f)",
    ],
    "Zimbabwe CDPA": [
        "Consent",
        "Contract necessity",
        "Legal obligation",
        "Vital interests",
        "Public interest",
        "Legitimate interests of the controller",
    ],
    "South Africa POPIA": [
        "Consent — Condition 1",
        "Contractual necessity",
        "Legal obligation",
        "Vital interests of the data subject",
        "Public law duty",
        "Legitimate interests of the responsible party",
    ],
    "UAE PDPL": [
        "Explicit consent",
        "Contractual necessity",
        "Legal obligation",
        "Vital interests",
        "Public interest",
        "Legitimate interests",
    ],
    "Saudi PDPL": [
        "Explicit consent",
        "Contractual necessity",
        "Legal obligation",
        "Vital interests",
        "Public interest / official duty",
        "Legitimate interests",
    ],
    "Qatar DPL": [
        "Explicit consent",
        "Contractual necessity",
        "Legal obligation",
        "Vital interests",
        "Public interest",
        "Legitimate interests",
    ],
}

DATA_CATEGORIES = [
    "Name & contact details",
    "National/government ID numbers",
    "Financial information",
    "Employment history & records",
    "Health & medical data",
    "Biometric data",
    "Genetic data",
    "Location & movement data",
    "Online identifiers (IP, cookies)",
    "Communications data",
    "Behavioural & preference data",
    "Political opinions",
    "Religious or philosophical beliefs",
    "Trade union membership",
    "Sexual orientation or sex life",
    "Racial or ethnic origin",
    "Criminal convictions & offences",
    "Children's data",
    "Images & voice recordings",
    "Device & technical data",
]

DATA_SUBJECTS = [
    "Employees / staff",
    "Job applicants / candidates",
    "Customers / clients",
    "Website & app visitors",
    "Children (under 18)",
    "Patients / service users",
    "Students / learners",
    "Research participants",
    "Members of the public",
    "Business partners / vendors",
    "Contractors / freelancers",
    "Investors / shareholders",
]

SUBJECT_COUNTS = [
    "< 100",
    "100 – 1 000",
    "1 000 – 10 000",
    "10 000 – 100 000",
    "100 000 – 1 000 000",
    "> 1 000 000",
    "Unknown",
]

RETENTION_OPTIONS = [
    "30 days",
    "3 months",
    "6 months",
    "1 year",
    "2 years",
    "3 years",
    "5 years",
    "7 years",
    "10 years",
    "Duration of contract",
    "As required by applicable law",
    "Indefinitely (with justification)",
    "Custom — specify in notes",
]

RISK_LEVELS  = ["Low", "Medium", "High", "Very High"]
YES_NO_NA    = ["Yes", "No", "In Progress", "Not Applicable"]
DEPARTMENTS  = [
    "IT / Technology", "Human Resources", "Finance & Accounting",
    "Legal & Compliance", "Marketing", "Operations", "Customer Service",
    "Research & Development", "Sales", "Security / Risk",
    "Executive / Management", "Other",
]
STATUSES = [
    ("draft",      "Draft"),
    ("in_review",  "In Review"),
    ("approved",   "Approved"),
    ("rejected",   "Rejected"),
]


def _form_ctx():
    """Common context for DPIA form pages."""
    return dict(
        regulations=REGULATIONS,
        activity_types=ACTIVITY_TYPES,
        legal_bases=LEGAL_BASES,
        data_categories=DATA_CATEGORIES,
        data_subjects=DATA_SUBJECTS,
        subject_counts=SUBJECT_COUNTS,
        retention_options=RETENTION_OPTIONS,
        risk_levels=RISK_LEVELS,
        yes_no_na=YES_NO_NA,
        departments=DEPARTMENTS,
        statuses=STATUSES,
    )


def _collect_form(form) -> dict:
    """Parse multidict form into a clean dict ready for DB."""
    return {
        "title":          form.get("title", "").strip(),
        "status":         form.get("status", "draft"),
        "regulation":     form.get("regulation", "GDPR"),
        "org_name":       form.get("org_name", "").strip(),
        "department":     form.get("department", "").strip(),
        "controller_name":form.get("controller_name", "").strip(),
        "dpo_name":       form.get("dpo_name", "").strip(),
        "dpo_email":      form.get("dpo_email", "").strip(),
        "activity_type":  form.get("activity_type", "").strip(),
        "activity_desc":  form.get("activity_desc", "").strip(),
        "purpose":        form.get("purpose", "").strip(),
        "legal_basis":    form.get("legal_basis", "").strip(),
        "data_categories":form.getlist("data_categories"),
        "special_cats":   form.getlist("special_cats"),
        "data_subjects":  form.get("data_subjects", "").strip(),
        "subject_count":  form.get("subject_count", "").strip(),
        "retention":      form.get("retention", "").strip(),
        "systems":        form.get("systems", "").strip(),
        "processors":     form.get("processors", "").strip(),
        "intl_transfer":  form.get("intl_transfer", "").strip(),
        "transfer_dest":  form.get("transfer_dest", "").strip(),
        "transfer_mech":  form.get("transfer_mech", "").strip(),
        "necessity":      form.get("necessity", "").strip(),
        "proportionality":form.get("proportionality", "").strip(),
        "risks":          json.loads(form.get("risks_json", "[]")),
        "overall_risk":   form.get("overall_risk", "").strip(),
        "residual_risk":  form.get("residual_risk", "").strip(),
        "dpo_consulted":  form.get("dpo_consulted", "").strip(),
        "auth_consulted": form.get("auth_consulted", "").strip(),
        "subjects_consulted": form.get("subjects_consulted", "").strip(),
        "consult_notes":  form.get("consult_notes", "").strip(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    s = db.stats()
    recent = db.list_dpias(limit=6)
    return render_template("dashboard.html", stats=s, recent=recent)


# ── list ──────────────────────────────────────────────────────────────────────
@app.route("/dpias")
def dpia_list():
    search     = request.args.get("q", "").strip()
    regulation = request.args.get("regulation", "")
    status     = request.args.get("status", "")
    dpias      = db.list_dpias(search=search or None,
                               regulation=regulation or None,
                               status=status or None)
    return render_template("dpia_list.html",
                           dpias=dpias, search=search,
                           regulation=regulation, status=status,
                           regulations=REGULATIONS, statuses=STATUSES)


# ── new ───────────────────────────────────────────────────────────────────────
@app.route("/dpias/new", methods=["GET", "POST"])
def dpia_new():
    ctx = _form_ctx()
    if request.method == "POST":
        data = _collect_form(request.form)
        if not data["title"]:
            flash("Title is required.", "error")
            return render_template("dpia_form.html", mode="new", dpia=data, **ctx)
        new_id = db.create_dpia(data)
        flash("DPIA created successfully.", "success")
        return redirect(url_for("dpia_detail", dpia_id=new_id))
    return render_template("dpia_form.html", mode="new", dpia={}, **ctx)


# ── detail ────────────────────────────────────────────────────────────────────
@app.route("/dpias/<int:dpia_id>")
def dpia_detail(dpia_id):
    dpia = db.get_dpia(dpia_id)
    if not dpia:
        abort(404)
    return render_template("dpia_detail.html", dpia=dpia)


# ── edit ──────────────────────────────────────────────────────────────────────
@app.route("/dpias/<int:dpia_id>/edit", methods=["GET", "POST"])
def dpia_edit(dpia_id):
    dpia = db.get_dpia(dpia_id)
    if not dpia:
        abort(404)
    ctx = _form_ctx()
    if request.method == "POST":
        data = _collect_form(request.form)
        db.update_dpia(dpia_id, data)
        flash("DPIA updated.", "success")
        return redirect(url_for("dpia_detail", dpia_id=dpia_id))
    return render_template("dpia_form.html", mode="edit", dpia=dpia, **ctx)


# ── delete ────────────────────────────────────────────────────────────────────
@app.route("/dpias/<int:dpia_id>/delete", methods=["POST"])
def dpia_delete(dpia_id):
    db.delete_dpia(dpia_id)
    flash("DPIA deleted.", "info")
    return redirect(url_for("dpia_list"))


# ── download Word ─────────────────────────────────────────────────────────────
@app.route("/dpias/<int:dpia_id>/download")
def dpia_download(dpia_id):
    dpia = db.get_dpia(dpia_id)
    if not dpia:
        abort(404)
    buf = generate_docx(dpia)
    filename = f"DPIA_{dpia['ref_number']}.docx"
    return send_file(
        buf, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AI API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/legal-bases/<regulation>")
def api_legal_bases(regulation):
    bases = LEGAL_BASES.get(regulation, LEGAL_BASES["GDPR"])
    return jsonify(bases)


@app.route("/api/ai/research", methods=["POST"])
def api_ai_research():
    body        = request.get_json(force=True, silent=True) or {}
    activity    = body.get("activity_type", "")
    regulation  = body.get("regulation", "GDPR")
    context     = body.get("context", "")
    if not activity:
        return jsonify({"error": "activity_type is required"}), 400
    text, err = ai_research(activity, regulation, context)
    if err:
        return jsonify({"error": err}), 500
    return jsonify({"research": text})


@app.route("/api/ai/research/save/<int:dpia_id>", methods=["POST"])
def api_save_research(dpia_id):
    body = request.get_json(force=True, silent=True) or {}
    db.update_dpia(dpia_id, {"ai_research": body.get("research", "")})
    return jsonify({"ok": True})


@app.route("/api/ai/generate/<int:dpia_id>", methods=["POST"])
def api_ai_generate(dpia_id):
    dpia = db.get_dpia(dpia_id)
    if not dpia:
        return jsonify({"error": "DPIA not found"}), 404
    text, err = ai_generate_full_dpia(dpia)
    if err:
        return jsonify({"error": err}), 500
    db.update_dpia(dpia_id, {"ai_full_dpia": text})
    return jsonify({"content": text})


@app.route("/api/ai/risks", methods=["POST"])
def api_ai_risks():
    body       = request.get_json(force=True, silent=True) or {}
    activity   = body.get("activity_type", "")
    regulation = body.get("regulation", "GDPR")
    categories = body.get("data_categories", [])
    if not activity:
        return jsonify({"error": "activity_type is required"}), 400
    risks, err = ai_suggest_risks(activity, regulation, categories)
    if err:
        return jsonify({"error": err}), 500
    return jsonify({"risks": risks})


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE FILTERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.template_filter("status_label")
def status_label(s):
    return s.replace("_", " ").title() if s else "—"


@app.template_filter("fmt_date")
def fmt_date(s):
    if not s:
        return "—"
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return s[:10]


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=5000)
