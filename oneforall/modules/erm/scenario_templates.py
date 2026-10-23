"""Starter templates for Scenario Studio.

Plain data, not database rows: a template only pre fills the Define step. The person edits it, and nothing here is
stored until they create the scenario. `match` words rank the user's own risks when the studio suggests what a
scenario affects; they never reach the database.
"""

SCENARIO_TYPES = [
    "Cyber attack", "Supplier failure", "Regulatory action", "Data breach", "Market shock",
    "People and skills", "Technology failure", "AI system failure", "Other",
]

TEMPLATES = [
    {"id": "ransomware", "title": "Ransomware attack on core systems", "type": "Cyber attack",
     "description": "Attackers encrypt core business systems and demand payment. Operations stop until systems are restored.",
     "assumptions": "Backups exist but a full restore takes about five days. Customer data may be exposed. "
                    "Regulators must be told within their notification window.",
     "horizon": "12 months", "match": ["cyber", "ransom", "security", "backup", "availability", "data"]},
    {"id": "supplier-failure", "title": "Key supplier fails for an extended period", "type": "Supplier failure",
     "description": "A supplier the business depends on stops delivering because of insolvency, sanctions or its own outage.",
     "assumptions": "No ready alternative supplier. Switching takes about three months. Contracts give limited remedies.",
     "horizon": "6 months", "match": ["supplier", "vendor", "third", "outsourc", "supply", "contract"]},
    {"id": "regulatory-fine", "title": "Regulatory breach and fine", "type": "Regulatory action",
     "description": "A regulator finds a breach of a rule that applies to the organization and imposes a fine and a remediation order.",
     "assumptions": "The finding is upheld. Remediation needs new controls and independent reporting for a year.",
     "horizon": "12 months", "match": ["regulat", "compliance", "licen", "fine", "obligation", "legal"]},
    {"id": "data-breach", "title": "Personal data breach", "type": "Data breach",
     "description": "Personal data of customers or staff is accessed or leaked without authority.",
     "assumptions": "The breach is confirmed, affected people and the regulator are notified, and trust drops for a period.",
     "horizon": "12 months", "match": ["privacy", "data", "breach", "personal", "confidential", "leak"]},
    {"id": "fx-shock", "title": "Currency and market shock", "type": "Market shock",
     "description": "A sharp currency move or market fall raises costs and cuts revenue or funding.",
     "assumptions": "The move lasts at least two quarters. Hedging covers only part of the exposure.",
     "horizon": "12 months", "match": ["market", "currency", "fx", "liquidity", "credit", "financial", "funding"]},
    {"id": "key-person", "title": "Loss of key people", "type": "People and skills",
     "description": "Several people with critical skills or approvals leave or become unavailable at once.",
     "assumptions": "Replacements take six months to hire and train. Key knowledge is not documented.",
     "horizon": "12 months", "match": ["people", "staff", "skill", "talent", "succession", "key person", "hr"]},
    {"id": "ai-failure", "title": "AI system produces harmful or wrong outputs", "type": "AI system failure",
     "description": "An AI system in use gives wrong, biased or unsafe results that reach customers or decisions.",
     "assumptions": "The fault is found after several weeks. Affected decisions must be reviewed and some reversed.",
     "horizon": "6 months", "match": ["ai", "model", "algorithm", "automat", "bias", "machine"]},
    {"id": "extended-outage", "title": "Extended outage of a critical service", "type": "Technology failure",
     "description": "A critical technology service is down for days because of a fault, a failed change or a provider outage.",
     "assumptions": "Recovery objectives are missed. Manual workarounds cover only part of the work.",
     "horizon": "3 months", "match": ["outage", "availability", "system", "infrastructure", "continuity", "recovery", "it"]},
]

_BY_ID = {t["id"]: t for t in TEMPLATES}


def template(template_id):
    return _BY_ID.get(template_id)


def public_templates():
    """The templates as the browser needs them (the ranking words stay on the server)."""
    return [{k: v for k, v in t.items() if k != "match"} for t in TEMPLATES]
