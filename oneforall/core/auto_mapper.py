"""
ThemisIQ Auto-Mapper
====================
Automatically identifies equivalent and related controls across compliance frameworks.

Three-pass approach:
  Pass 1: Category normalisation — cheap domain grouping reduces candidate pairs by ~95%
  Pass 2: Text similarity — Jaccard + SequenceMatcher on name + description
  Pass 3: AI semantic — only for ambiguous pairs (score 0.35–0.65); async call to Claude/GPT

Usage:
    # In a FastAPI async route:
    from core.auto_mapper import run_auto_mapping, get_ims_status_bulk
    result = await run_auto_mapping([1, 4, 7], user_id=user["id"], db=db)
    statuses = get_ims_status_bulk(controls, all_fw_ids, db)
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from itertools import combinations
from database import IntegrityError, OperationalError
from typing import Optional

log = logging.getLogger("oneforall.auto_mapper")

# ── Stop words for text matching ──────────────────────────────────────────────
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with",
    "is", "are", "shall", "should", "must", "be", "that", "this", "all",
    "by", "from", "as", "at", "its", "it", "not", "no", "any", "each",
    "their", "which", "where", "when", "how", "who", "do", "does", "have",
    "has", "been", "can", "will", "may", "related", "management", "system",
    "process", "procedure", "policy", "control", "controls", "requirement",
    "requirements", "information", "data", "security", "compliance",
}

# ── Canonical domain map for category normalisation ───────────────────────────
_DOMAIN_MAP: dict[str, str] = {
    # Access / Identity
    "access control":           "access_control",
    "access":                   "access_control",
    "authentication":           "access_control",
    "identity":                 "access_control",
    "identity management":      "access_control",
    "logical access":           "access_control",
    "user access":              "access_control",
    "privileged access":        "access_control",
    # Governance / Policy
    "organizational":           "governance",
    "organisational":           "governance",
    "governance":               "governance",
    "information security policies": "governance",
    "policies":                 "governance",
    "leadership":               "governance",
    "management":               "governance",
    "strategy":                 "governance",
    # Risk
    "risk":                     "risk_management",
    "risk management":          "risk_management",
    "risk assessment":          "risk_management",
    "risk treatment":           "risk_management",
    "risk analysis":            "risk_management",
    # Incident
    "incident":                 "incident_management",
    "incident management":      "incident_management",
    "incident response":        "incident_management",
    "security incident":        "incident_management",
    "event":                    "incident_management",
    # Asset
    "asset":                    "asset_management",
    "asset management":         "asset_management",
    "inventory":                "asset_management",
    "configuration":            "asset_management",
    # Human Resources / People
    "human resources":          "people",
    "people":                   "people",
    "personnel":                "people",
    "hr":                       "people",
    "workforce":                "people",
    "staff":                    "people",
    # Training / Awareness
    "awareness":                "training",
    "training":                 "training",
    "education":                "training",
    "competence":               "training",
    # Cryptography / Encryption
    "cryptography":             "cryptography",
    "encryption":               "cryptography",
    "key management":           "cryptography",
    "cryptographic":            "cryptography",
    # Data Protection / Privacy
    "data protection":          "data_protection",
    "privacy":                  "data_protection",
    "data":                     "data_protection",
    "personal data":            "data_protection",
    "consent":                  "data_protection",
    # Network
    "network":                  "network_security",
    "network security":         "network_security",
    "firewall":                 "network_security",
    "communications":           "network_security",
    "telecommunications":       "network_security",
    # Logging / Monitoring
    "logging":                  "logging_monitoring",
    "monitoring":               "logging_monitoring",
    "audit logging":            "logging_monitoring",
    "log":                      "logging_monitoring",
    "detection":                "logging_monitoring",
    # Vulnerability / Patching
    "vulnerability":            "vulnerability_management",
    "patch":                    "vulnerability_management",
    "patching":                 "vulnerability_management",
    "scanning":                 "vulnerability_management",
    # Physical
    "physical":                 "physical_security",
    "physical security":        "physical_security",
    "environmental":            "physical_security",
    "facilities":               "physical_security",
    # Continuity
    "continuity":               "continuity",
    "resilience":               "continuity",
    "recovery":                 "continuity",
    "disaster recovery":        "continuity",
    "business continuity":      "continuity",
    "backup":                   "continuity",
    # Supplier / Third Party
    "supplier":                 "supplier_management",
    "third party":              "supplier_management",
    "vendor":                   "supplier_management",
    "supply chain":             "supplier_management",
    "outsourcing":              "supplier_management",
    # Audit / Compliance
    "audit":                    "audit_compliance",
    "compliance":               "audit_compliance",
    "internal audit":           "audit_compliance",
    "review":                   "audit_compliance",
    # Development / Change
    "development":              "development",
    "change management":        "development",
    "software development":     "development",
    "sdlc":                     "development",
    "secure development":       "development",
    # Protect Data (PCI-specific)
    "protect data":             "data_protection",
    "cardholder data":          "data_protection",
    "card data":                "data_protection",
    # ISO 42001 / AI-specific categories
    "core":                     "governance",        # ISO 42001 "Core" = governance
    "leadership":               "governance",        # ISO 42001 Leadership = governance
    "planning":                 "risk_management",   # ISO 42001 Planning = risk-related
    "performance":              "audit_compliance",  # ISO 42001 Performance = audit
    "improvement":              "audit_compliance",  # ISO 42001 Improvement = CAPA/audit
    "support":                  "people",            # ISO 42001 Support = people/resources
    "operation":                "governance",        # ISO 42001 Operation
    "context":                  "governance",        # ISO 42001 Context of the org
    # ISO 9001 / Quality
    "quality management":       "audit_compliance",
    "product":                  "asset_management",
    "customer":                 "audit_compliance",
    # ISO 22301 / BCM
    "business impact":          "continuity",
    "recovery strategy":        "continuity",
    "exercise":                 "continuity",
    # NIST CSF categories
    "identify":                 "risk_management",
    "protect":                  "access_control",
    "detect":                   "logging_monitoring",
    "respond":                  "incident_management",
    "recover":                  "continuity",
    # HIPAA
    "administrative":           "governance",
    "technical safeguards":     "access_control",
    "physical safeguards":      "physical_security",
    # SOC 2
    "availability":             "continuity",
    "confidentiality":          "data_protection",
    "processing integrity":     "audit_compliance",
}


def _normalise_domain(category: str) -> str:
    """Map a raw category string to a canonical domain name."""
    if not category:
        return "general"
    key = category.lower().strip()
    # Direct match
    if key in _DOMAIN_MAP:
        return _DOMAIN_MAP[key]
    # Partial match — find first key that appears in category
    for k, v in _DOMAIN_MAP.items():
        if k in key or key in k:
            return v
    return "general"


def _tokenise(text: str) -> set[str]:
    """Lowercase, remove punctuation, split to words, remove stop words."""
    text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return {w for w in text.split() if w and w not in _STOP_WORDS and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _seq_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def control_similarity(ctrl_a: dict, ctrl_b: dict) -> float:
    """Return a combined similarity score in [0.0, 1.0] between two controls.

    Weights:
      - 65% name similarity  (Jaccard 55% + SequenceMatcher 45%)
      - 35% description similarity (same formula)
    """
    name_tok_a = _tokenise(ctrl_a.get("name", ""))
    name_tok_b = _tokenise(ctrl_b.get("name", ""))
    name_jacc  = _jaccard(name_tok_a, name_tok_b)
    name_seq   = _seq_ratio(ctrl_a.get("name", ""), ctrl_b.get("name", ""))
    name_score = 0.55 * name_jacc + 0.45 * name_seq

    desc_tok_a = _tokenise(ctrl_a.get("description", ""))
    desc_tok_b = _tokenise(ctrl_b.get("description", ""))
    desc_jacc  = _jaccard(desc_tok_a, desc_tok_b)
    desc_seq   = _seq_ratio(ctrl_a.get("description", ""), ctrl_b.get("description", ""))
    desc_score = 0.55 * desc_jacc + 0.45 * desc_seq

    return 0.65 * name_score + 0.35 * desc_score


async def _ai_classify_pair(ctrl_a: dict, ctrl_b: dict) -> tuple[str, float]:
    """Ask the AI to classify two ambiguous controls.

    Returns (mapping_type, confidence) where mapping_type ∈ {'equivalent','related','none'}.
    Falls back to ('none', 0.0) on any error.
    """
    try:
        from modules.sentinel.ai_service import call_ai
        system = (
            "You are a senior GRC compliance expert with deep knowledge of ISO 27001, "
            "PCI DSS, NIST CSF, SOC 2, GDPR, and other frameworks. "
            "Your task is to compare two controls from different frameworks and classify "
            "their relationship. Return ONLY valid JSON with no markdown, no explanation."
        )
        user = (
            f'Control A — {ctrl_a.get("framework","?")} [{ctrl_a.get("ref","")}]: '
            f'"{ctrl_a.get("name","")}" — {ctrl_a.get("description","")}\n\n'
            f'Control B — {ctrl_b.get("framework","?")} [{ctrl_b.get("ref","")}]: '
            f'"{ctrl_b.get("name","")}" — {ctrl_b.get("description","")}\n\n'
            'Return exactly: {"match":"equivalent"|"related"|"none","confidence":0.0-1.0}'
        )
        text, err = await call_ai(system, user, max_tokens=120)
        if err or not text:
            return "none", 0.0
        # Extract JSON robustly
        text = text.strip()
        # Strip markdown fences if present
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        match = data.get("match", "none")
        confidence = float(data.get("confidence", 0.5))
        if match not in ("equivalent", "related", "none"):
            return "none", 0.0
        return match, confidence
    except Exception as exc:
        log.debug("AI classify failed: %s", exc)
        return "none", 0.0


async def run_auto_mapping(
    framework_ids: list[int],
    user_id: int,
    db: sqlite3.Connection,
    use_ai: bool = False,
) -> dict:
    """
    Auto-generate aria_control_mappings for all control pairs across the given frameworks.

    Algorithm:
      1. Load all controls for each framework
      2. Group by normalised domain (category)
      3. For each cross-framework pair within the same domain:
         - Skip if mapping already exists
         - If text_similarity >= 0.65 → equivalent (insert)
         - If 0.35 <= text_similarity < 0.65 → AI classify (async, optional)
         - If text_similarity < 0.35 → skip
      4. Bulk insert all new mappings

    Returns:
        {"created": int, "skipped": int, "ai_calls": int, "errors": list}
    """
    if len(framework_ids) < 2:
        return {"created": 0, "skipped": 0, "ai_calls": 0, "errors": ["Need at least 2 frameworks"]}

    # Cap for performance
    if len(framework_ids) > 6:
        framework_ids = framework_ids[:6]
        log.warning("auto_mapper: capped to first 6 frameworks")

    # ── Load controls ─────────────────────────────────────────────────────────
    placeholders = ",".join(["%s"] * len(framework_ids))
    rows = db.execute(
        f"SELECT c.id, c.framework_id, c.ref, c.name, c.description, c.category, "
        f"       f.name AS fw_name "
        f"FROM controls c JOIN frameworks f ON f.id=c.framework_id "
        f"WHERE c.framework_id IN ({placeholders}) ORDER BY c.framework_id, c.ref",
        framework_ids,
    ).fetchall()

    # Group by framework
    by_fw: dict[int, list[dict]] = {}
    for r in rows:
        ctrl = {
            "id": r["id"], "framework_id": r["framework_id"],
            "ref": r["ref"], "name": r["name"] or "",
            "description": r["description"] or "",
            "category": r["category"] or "",
            "framework": r["fw_name"] or "",
        }
        by_fw.setdefault(r["framework_id"], []).append(ctrl)

    # ── Load existing mappings to skip ────────────────────────────────────────
    existing_pairs: set[tuple[int, int]] = set()
    existing_rows = db.execute(
        "SELECT source_control_id, target_control_id FROM aria_control_mappings"
    ).fetchall()
    for row in existing_rows:
        a, b = row[0], row[1]
        existing_pairs.add((min(a, b), max(a, b)))

    # ── Compare across framework pairs ────────────────────────────────────────
    to_insert: list[dict] = []
    ai_calls = 0
    skipped = 0

    fw_pairs = list(combinations(framework_ids, 2))
    for fw_a_id, fw_b_id in fw_pairs:
        ctrls_a = by_fw.get(fw_a_id, [])
        ctrls_b = by_fw.get(fw_b_id, [])

        # Index ctrls_b by domain for fast lookup
        domain_b: dict[str, list[dict]] = {}
        for c in ctrls_b:
            d = _normalise_domain(c["category"])
            domain_b.setdefault(d, []).append(c)

        # Detect whether the two frameworks share ANY canonical domains.
        # If they have zero overlap (e.g. ISO 27001 "Organizational" vs ISO 42001 "Core"),
        # fall back to comparing all controls (domain grouping isn't helping).
        domains_a = {_normalise_domain(c["category"]) for c in ctrls_a} - {"general"}
        domains_in_b = set(domain_b.keys()) - {"general"}
        no_domain_overlap = not (domains_a & domains_in_b)

        for ctrl_a in ctrls_a:
            domain = _normalise_domain(ctrl_a["category"])

            if no_domain_overlap:
                # No shared domains — compare against ALL fw_b controls
                candidates = ctrls_b
            else:
                candidates = domain_b.get(domain, []) + domain_b.get("general", [])
                if not candidates:
                    # Domain exists in fw_a but not in fw_b — broaden to all
                    candidates = ctrls_b

            if not candidates:
                continue

            # Pre-score all candidates to prioritise AI calls on the best matches
            # Secondary sort key is ctrl ID (stable, avoids dict comparison error)
            scored = sorted(
                ((control_similarity(ctrl_a, c), c["id"], c) for c in candidates),
                reverse=True,
            )

            # For AI mode: only evaluate the top-3 scoring candidates per control.
            # This keeps AI call count manageable (max_per_fw_pair ≈ fw_a_size × 3).
            ai_budget = 3 if use_ai else 0
            ai_used_this_ctrl = 0

            for score, _ctrl_id, ctrl_b in scored:
                pair_key = (min(ctrl_a["id"], ctrl_b["id"]), max(ctrl_a["id"], ctrl_b["id"]))
                if pair_key in existing_pairs:
                    skipped += 1
                    continue

                if score >= 0.60:
                    mapping_type = "equivalent"
                    confidence = min(score, 0.99)
                    method = "text"
                elif use_ai and score >= 0.15 and ai_used_this_ctrl < ai_budget:
                    # Ambiguous — let AI decide
                    mapping_type, confidence = await _ai_classify_pair(ctrl_a, ctrl_b)
                    ai_calls += 1
                    ai_used_this_ctrl += 1
                    method = "ai"
                    if mapping_type == "none":
                        skipped += 1
                        continue
                else:
                    skipped += 1
                    continue

                to_insert.append({
                    "source_framework_id": ctrl_a["framework_id"],
                    "source_control_id":   ctrl_a["id"],
                    "target_framework_id": ctrl_b["framework_id"],
                    "target_control_id":   ctrl_b["id"],
                    "mapping_type":        mapping_type,
                    "confidence":          round(confidence, 3),
                    "auto_generated":      1,
                    "match_method":        method,
                    "created_by":          user_id,
                })
                existing_pairs.add(pair_key)

    # ── Bulk insert ───────────────────────────────────────────────────────────
    # Check which optional columns actually exist (handles fresh DB before migration)
    _has_extra_cols = True
    try:
        db.execute("SELECT auto_generated, match_method FROM aria_control_mappings LIMIT 0")
    except OperationalError:
        _has_extra_cols = False
        log.warning("auto_mapper: auto_generated/match_method columns missing — using minimal INSERT")

    created = 0
    for m in to_insert:
        try:
            if _has_extra_cols:
                db.execute(
                    "INSERT INTO aria_control_mappings "
                    "(source_framework_id, source_control_id, target_framework_id, target_control_id, "
                    " mapping_type, confidence, notes, auto_generated, match_method, created_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (m["source_framework_id"], m["source_control_id"],
                     m["target_framework_id"], m["target_control_id"],
                     m["mapping_type"], m["confidence"], "",
                     m["auto_generated"], m["match_method"], m["created_by"]),
                )
            else:
                # Fallback: insert without the new metadata columns
                db.execute(
                    "INSERT INTO aria_control_mappings "
                    "(source_framework_id, source_control_id, target_framework_id, target_control_id, "
                    " mapping_type, confidence, notes, created_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (m["source_framework_id"], m["source_control_id"],
                     m["target_framework_id"], m["target_control_id"],
                     m["mapping_type"], m["confidence"], "", m["created_by"]),
                )
            created += 1
        except IntegrityError:
            skipped += 1
    db.commit()

    log.info(
        "auto_mapper: frameworks=%s created=%d skipped=%d ai_calls=%d",
        framework_ids, created, skipped, ai_calls,
    )
    return {"created": created, "skipped": skipped, "ai_calls": ai_calls, "errors": []}


def get_ims_status_bulk(
    controls: list[dict],
    all_framework_ids: list[int],
    db: sqlite3.Connection,
) -> dict[int, dict]:
    """
    For each control in `controls`, determine its IMS classification relative to
    the set of selected frameworks.

    Returns:
        {ctrl_id: {"status": "integrated"|"partial"|"unique",
                   "mapped_fw_ids": [fw_id, ...],
                   "mapped_fw_names": [fw_name, ...]}}
    """
    if not controls or len(all_framework_ids) <= 1:
        return {c["id"]: {"status": "unique", "mapped_fw_ids": [], "mapped_fw_names": []} for c in controls}

    ctrl_ids = [c["id"] for c in controls]
    ctrl_fw_map = {c["id"]: c.get("framework_id") for c in controls}

    placeholders = ",".join(["%s"] * len(ctrl_ids))

    # Single query: for each control, get all the framework IDs it is mapped to
    mapping_rows = db.execute(f"""
        SELECT
            c_own.id         AS own_ctrl_id,
            c_own.framework_id AS own_fw_id,
            CASE
                WHEN m.source_control_id = c_own.id THEN m.target_framework_id
                ELSE m.source_framework_id
            END AS mapped_fw_id,
            CASE
                WHEN m.source_control_id = c_own.id THEN tf.name
                ELSE sf.name
            END AS mapped_fw_name
        FROM controls c_own
        LEFT JOIN aria_control_mappings m
            ON (m.source_control_id = c_own.id OR m.target_control_id = c_own.id)
            AND m.mapping_type IN ('equivalent', 'related', 'ims_equivalent')
        LEFT JOIN frameworks sf ON sf.id = m.source_framework_id
        LEFT JOIN frameworks tf ON tf.id = m.target_framework_id
        WHERE c_own.id IN ({placeholders})
    """, ctrl_ids).fetchall()

    # Group by own_ctrl_id
    result: dict[int, dict] = {}
    for r in mapping_rows:
        oid = r["own_ctrl_id"]
        if oid not in result:
            result[oid] = {"status": "unique", "mapped_fw_ids": set(), "mapped_fw_names": set()}
        if r["mapped_fw_id"] and r["mapped_fw_id"] in all_framework_ids:
            result[oid]["mapped_fw_ids"].add(r["mapped_fw_id"])
            if r["mapped_fw_name"]:
                result[oid]["mapped_fw_names"].add(r["mapped_fw_name"])

    # Ensure every control has an entry
    for ctrl in controls:
        if ctrl["id"] not in result:
            result[ctrl["id"]] = {"status": "unique", "mapped_fw_ids": set(), "mapped_fw_names": set()}

    # Classify
    for ctrl in controls:
        oid = ctrl["id"]
        own_fw = ctrl_fw_map[oid]
        other_fws = set(all_framework_ids) - {own_fw}
        covered = result[oid]["mapped_fw_ids"] & other_fws
        if len(covered) >= len(other_fws):
            result[oid]["status"] = "integrated"
        elif len(covered) > 0:
            result[oid]["status"] = "partial"
        else:
            result[oid]["status"] = "unique"
        # Convert sets to sorted lists for JSON serialisation
        result[oid]["mapped_fw_ids"]   = sorted(result[oid]["mapped_fw_ids"])
        result[oid]["mapped_fw_names"] = sorted(result[oid]["mapped_fw_names"])

    return result
