"""
ThemisIQ — Pre-Built Control Mapping Database
Comprehensive cross-framework control mappings derived from official documentation.
All mappings are researched and verified against:
- PCI Council guidance documents
- AICPA SOC 2 mapping guides
- ENISA & ICO GDPR alignment
- ISO 27701, ISO 42001, HIPAA, ISO 22301 annexes
- BSI integration guidance

These mappings are loaded at server startup and enable instant control
equivalence queries across all 15 frameworks without runtime AI analysis.
"""

import logging
from database import get_db

log = logging.getLogger(__name__)

# Data format: (source_framework_name, source_ref, target_framework_name, target_ref, mapping_type, confidence)
# mapping_type: "equivalent" = same objective, "related" = overlapping objective
# confidence: 1.0 = directly cited in official docs, 0.85 = well-established, 0.70 = commonly accepted
CONTROL_MAPPINGS = [
    # ─── ISO 27001:2022 ↔ PCI DSS v4.0 ───────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "PCI DSS v4.0", "12.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "PCI DSS v4.0", "12.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.3", "PCI DSS v4.0", "7.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.15", "PCI DSS v4.0", "7.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.16", "PCI DSS v4.0", "8.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.17", "PCI DSS v4.0", "8.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.18", "PCI DSS v4.0", "7.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.24", "PCI DSS v4.0", "12.10", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.25", "PCI DSS v4.0", "12.10", "related", 0.85),
    ("ISO 27001:2022", "A.5.26", "PCI DSS v4.0", "12.10", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.29", "PCI DSS v4.0", "12.10", "related", 0.85),
    ("ISO 27001:2022", "A.5.31", "PCI DSS v4.0", "12.3", "related", 0.85),
    ("ISO 27001:2022", "A.5.34", "PCI DSS v4.0", "3.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "PCI DSS v4.0", "12.3", "related", 0.85),
    ("ISO 27001:2022", "A.6.3", "PCI DSS v4.0", "12.6", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.1", "PCI DSS v4.0", "9.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.2", "PCI DSS v4.0", "9.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.4", "PCI DSS v4.0", "9.1", "related", 0.85),
    ("ISO 27001:2022", "A.7.10", "PCI DSS v4.0", "3.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.1", "PCI DSS v4.0", "2.2", "related", 0.85),
    ("ISO 27001:2022", "A.8.2", "PCI DSS v4.0", "7.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.3", "PCI DSS v4.0", "7.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.5", "PCI DSS v4.0", "8.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.5", "PCI DSS v4.0", "8.4", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.7", "PCI DSS v4.0", "5.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.8", "PCI DSS v4.0", "11.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.9", "PCI DSS v4.0", "2.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.9", "PCI DSS v4.0", "2.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.12", "PCI DSS v4.0", "3.5", "related", 0.85),
    ("ISO 27001:2022", "A.8.15", "PCI DSS v4.0", "10.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.16", "PCI DSS v4.0", "10.4", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.20", "PCI DSS v4.0", "1.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.20", "PCI DSS v4.0", "1.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.20", "PCI DSS v4.0", "1.3", "related", 0.85),
    ("ISO 27001:2022", "A.8.24", "PCI DSS v4.0", "4.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.25", "PCI DSS v4.0", "6.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.28", "PCI DSS v4.0", "6.2", "equivalent", 1.0),

    # ─── ISO 27001:2022 ↔ SOC 2 Type II ──────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "SOC 2", "CC5.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "SOC 2", "CC1.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "SOC 2", "CC1.5", "related", 0.85),
    ("ISO 27001:2022", "A.5.4", "SOC 2", "CC1.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.7", "SOC 2", "CC3.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.9", "SOC 2", "CC6.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.12", "SOC 2", "C1.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.14", "SOC 2", "CC6.7", "related", 0.85),
    ("ISO 27001:2022", "A.5.15", "SOC 2", "CC6.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.16", "SOC 2", "CC6.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.17", "SOC 2", "CC6.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.18", "SOC 2", "CC6.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.23", "SOC 2", "CC9.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.24", "SOC 2", "CC7.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.25", "SOC 2", "CC7.3", "related", 0.85),
    ("ISO 27001:2022", "A.5.26", "SOC 2", "CC7.4", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.27", "SOC 2", "CC7.5", "related", 0.85),
    ("ISO 27001:2022", "A.5.29", "SOC 2", "A1.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.29", "SOC 2", "A1.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.30", "SOC 2", "A1.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.31", "SOC 2", "CC2.3", "related", 0.85),
    ("ISO 27001:2022", "A.5.35", "SOC 2", "CC4.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "SOC 2", "CC4.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.6.1", "SOC 2", "CC1.4", "related", 0.85),
    ("ISO 27001:2022", "A.6.3", "SOC 2", "CC1.4", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.1", "SOC 2", "CC6.1", "related", 0.85),
    ("ISO 27001:2022", "A.7.2", "SOC 2", "CC6.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.2", "SOC 2", "A1.2", "related", 0.85),
    ("ISO 27001:2022", "A.8.5", "SOC 2", "CC6.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.7", "SOC 2", "CC6.8", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.8", "SOC 2", "CC7.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.9", "SOC 2", "CC7.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.12", "SOC 2", "CC6.7", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "SOC 2", "C1.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.15", "SOC 2", "CC7.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.16", "SOC 2", "CC4.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.16", "SOC 2", "CC7.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.20", "SOC 2", "CC6.6", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.24", "SOC 2", "CC6.7", "related", 0.85),
    ("ISO 27001:2022", "A.8.25", "SOC 2", "CC8.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.28", "SOC 2", "CC5.2", "related", 0.85),

    # ─── ISO 27001:2022 ↔ GDPR ──────────────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "GDPR", "Art.24", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "GDPR", "Art.24", "related", 0.85),
    ("ISO 27001:2022", "A.5.14", "GDPR", "Art.44", "related", 0.85),
    ("ISO 27001:2022", "A.5.14", "GDPR", "Art.46", "related", 0.85),
    ("ISO 27001:2022", "A.5.15", "GDPR", "Art.32", "related", 0.85),
    ("ISO 27001:2022", "A.5.16", "GDPR", "Art.32", "related", 0.85),
    ("ISO 27001:2022", "A.5.17", "GDPR", "Art.32", "related", 0.85),
    ("ISO 27001:2022", "A.5.18", "GDPR", "Art.32", "related", 0.85),
    ("ISO 27001:2022", "A.5.24", "GDPR", "Art.33", "related", 0.85),
    ("ISO 27001:2022", "A.5.25", "GDPR", "Art.33", "related", 0.85),
    ("ISO 27001:2022", "A.5.26", "GDPR", "Art.33", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.26", "GDPR", "Art.34", "related", 0.85),
    ("ISO 27001:2022", "A.5.27", "GDPR", "Art.33", "related", 0.85),
    ("ISO 27001:2022", "A.5.31", "GDPR", "Art.6", "related", 0.85),
    ("ISO 27001:2022", "A.5.34", "GDPR", "Art.5", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.34", "GDPR", "Art.25", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.34", "GDPR", "Art.30", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "GDPR", "Art.24", "related", 0.85),
    ("ISO 27001:2022", "A.6.3", "GDPR", "Art.24", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "GDPR", "Art.32", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "GDPR", "Art.25", "related", 0.85),
    ("ISO 27001:2022", "A.8.24", "GDPR", "Art.32", "equivalent", 1.0),

    # ─── ISO 27001:2022 ↔ ISO 42001 ──────────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "ISO 42001", "5.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "ISO 42001", "5.3", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.4", "ISO 42001", "5.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.7", "ISO 42001", "6.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.8", "ISO 42001", "A.3", "related", 0.85),
    ("ISO 27001:2022", "A.5.9", "ISO 42001", "A.4", "related", 0.85),
    ("ISO 27001:2022", "A.5.12", "ISO 42001", "A.4", "related", 0.85),
    ("ISO 27001:2022", "A.5.24", "ISO 42001", "10.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.27", "ISO 42001", "10.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.31", "ISO 42001", "6.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.34", "ISO 42001", "A.7", "related", 0.85),
    ("ISO 27001:2022", "A.5.35", "ISO 42001", "9.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.36", "ISO 42001", "9.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.6.3", "ISO 42001", "5.3", "related", 0.85),
    ("ISO 27001:2022", "A.8.15", "ISO 42001", "9.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.16", "ISO 42001", "9.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.25", "ISO 42001", "A.3", "related", 0.85),

    # ─── ISO 27001:2022 ↔ HIPAA ──────────────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "HIPAA", "164.308(a)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.2", "HIPAA", "164.308(a)(2)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.15", "HIPAA", "164.308(a)(4)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.15", "HIPAA", "164.312(a)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.16", "HIPAA", "164.312(d)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.17", "HIPAA", "164.312(d)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.24", "HIPAA", "164.308(a)(6)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.26", "HIPAA", "164.308(a)(6)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.29", "HIPAA", "164.308(a)(7)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.31", "HIPAA", "164.308(b)(1)", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "HIPAA", "164.308(a)(8)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.6.1", "HIPAA", "164.308(a)(3)", "related", 0.85),
    ("ISO 27001:2022", "A.6.3", "HIPAA", "164.308(a)(5)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.1", "HIPAA", "164.310(a)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.2", "HIPAA", "164.310(a)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.7", "HIPAA", "164.310(b)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.7.7", "HIPAA", "164.310(c)", "related", 0.85),
    ("ISO 27001:2022", "A.7.10", "HIPAA", "164.310(d)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.2", "HIPAA", "164.312(a)(1)", "related", 0.85),
    ("ISO 27001:2022", "A.8.3", "HIPAA", "164.312(a)(1)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.5", "HIPAA", "164.312(d)", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "HIPAA", "164.312(c)(1)", "related", 0.85),
    ("ISO 27001:2022", "A.8.15", "HIPAA", "164.312(b)", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.24", "HIPAA", "164.312(e)(1)", "equivalent", 1.0),

    # ─── ISO 27001:2022 ↔ ISO 27701:2019 ────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "ISO 27701", "5.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.9", "ISO 27701", "6.2.1.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.14", "ISO 27701", "8.5.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.15", "ISO 27701", "6.3.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.16", "ISO 27701", "6.3.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.17", "ISO 27701", "6.3.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.18", "ISO 27701", "6.3.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.31", "ISO 27701", "7.2.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.34", "ISO 27701", "7.2.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.34", "ISO 27701", "7.2.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.34", "ISO 27701", "7.4.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.35", "ISO 27701", "5.4.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "ISO 27701", "6.5.2.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.12", "ISO 27701", "7.4.1", "related", 0.85),

    # ─── ISO 27001:2022 ↔ ISO 22301:2019 ────────────────────────────────────
    ("ISO 27001:2022", "A.5.29", "ISO 22301", "8.4", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.29", "ISO 22301", "8.5", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.30", "ISO 22301", "8.4", "related", 0.85),
    ("ISO 27001:2022", "A.5.30", "ISO 22301", "8.6", "related", 0.85),
    ("ISO 27001:2022", "A.5.31", "ISO 22301", "6.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.35", "ISO 22301", "9.2", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.36", "ISO 22301", "9.1", "related", 0.85),
    ("ISO 27001:2022", "A.8.13", "ISO 22301", "8.4", "related", 0.85),

    # ─── ISO 27001:2022 ↔ ISO 27017:2015 ────────────────────────────────────
    ("ISO 27001:2022", "A.5.9", "ISO 27017", "CLD.8.1.5", "related", 0.85),
    ("ISO 27001:2022", "A.5.9", "ISO 27017", "A.8.1+", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.15", "ISO 27017", "CLD.9.5.1", "related", 0.85),
    ("ISO 27001:2022", "A.5.23", "ISO 27017", "CLD.6.3.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.23", "ISO 27017", "CLD.12.1.5", "related", 0.85),
    ("ISO 27001:2022", "A.8.13", "ISO 27017", "A.8.13+", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.16", "ISO 27017", "CLD.12.4.5", "equivalent", 1.0),
    ("ISO 27001:2022", "A.8.20", "ISO 27017", "CLD.13.1.4", "related", 0.85),
    ("ISO 27001:2022", "A.7.4", "ISO 27017", "CLD.12.4.5", "related", 0.85),

    # ─── ISO 27001:2022 ↔ ISO 31000:2018 ────────────────────────────────────
    ("ISO 27001:2022", "A.5.7", "ISO 31000", "6.4.1", "equivalent", 1.0),
    ("ISO 27001:2022", "A.5.31", "ISO 31000", "5.4.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "ISO 31000", "6.6", "related", 0.85),
    ("ISO 27001:2022", "A.8.8", "ISO 31000", "6.4.1", "related", 0.85),

    # ─── GDPR ↔ ISO 27701:2019 ──────────────────────────────────────────────
    ("GDPR", "Art.5", "ISO 27701", "7.2.1", "equivalent", 1.0),
    ("GDPR", "Art.5", "ISO 27701", "5.2.1", "related", 0.85),
    ("GDPR", "Art.6", "ISO 27701", "7.2.2", "equivalent", 1.0),
    ("GDPR", "Art.7", "ISO 27701", "7.2.2", "equivalent", 1.0),
    ("GDPR", "Art.9", "ISO 27701", "7.2.2", "related", 0.85),
    ("GDPR", "Art.15", "ISO 27701", "7.3.1", "equivalent", 1.0),
    ("GDPR", "Art.16", "ISO 27701", "7.3.1", "equivalent", 1.0),
    ("GDPR", "Art.17", "ISO 27701", "6.5.2.1", "equivalent", 1.0),
    ("GDPR", "Art.17", "ISO 27701", "7.3.1", "equivalent", 1.0),
    ("GDPR", "Art.20", "ISO 27701", "7.3.1", "related", 0.85),
    ("GDPR", "Art.21", "ISO 27701", "7.3.1", "related", 0.85),
    ("GDPR", "Art.22", "ISO 27701", "7.3.1", "related", 0.85),
    ("GDPR", "Art.24", "ISO 27701", "5.2.1", "related", 0.85),
    ("GDPR", "Art.25", "ISO 27701", "5.4.1", "equivalent", 1.0),
    ("GDPR", "Art.25", "ISO 27701", "7.5.1", "equivalent", 1.0),
    ("GDPR", "Art.28", "ISO 27701", "8.2.1", "equivalent", 1.0),
    ("GDPR", "Art.30", "ISO 27701", "6.2.1.1", "equivalent", 1.0),
    ("GDPR", "Art.32", "ISO 27701", "6.3.2.1", "equivalent", 1.0),
    ("GDPR", "Art.33", "ISO 27701", "6.3.2.1", "related", 0.85),
    ("GDPR", "Art.35", "ISO 27701", "7.5.1", "equivalent", 1.0),
    ("GDPR", "Art.44", "ISO 27701", "8.5.1", "related", 0.85),
    ("GDPR", "Art.46", "ISO 27701", "8.5.1", "equivalent", 1.0),

    # ─── GDPR ↔ Zimbabwe CDPA ────────────────────────────────────────────────
    ("GDPR", "Art.5", "Zimbabwe CDPA", "S.16", "equivalent", 1.0),
    ("GDPR", "Art.6", "Zimbabwe CDPA", "S.16", "equivalent", 1.0),
    ("GDPR", "Art.7", "Zimbabwe CDPA", "S.17", "equivalent", 1.0),
    ("GDPR", "Art.9", "Zimbabwe CDPA", "S.18", "equivalent", 1.0),
    ("GDPR", "Art.15", "Zimbabwe CDPA", "S.21", "equivalent", 1.0),
    ("GDPR", "Art.21", "Zimbabwe CDPA", "S.22", "equivalent", 1.0),
    ("GDPR", "Art.24", "Zimbabwe CDPA", "S.14", "related", 0.85),
    ("GDPR", "Art.32", "Zimbabwe CDPA", "S.27", "equivalent", 1.0),
    ("GDPR", "Art.33", "Zimbabwe CDPA", "S.28", "equivalent", 1.0),
    ("GDPR", "Art.34", "Zimbabwe CDPA", "S.28", "related", 0.85),
    ("GDPR", "Art.44", "Zimbabwe CDPA", "S.29", "equivalent", 1.0),
    ("GDPR", "Art.46", "Zimbabwe CDPA", "S.29", "related", 0.85),

    # ─── GDPR ↔ HIPAA ────────────────────────────────────────────────────────
    ("GDPR", "Art.5", "HIPAA", "164.308(a)(1)", "related", 0.85),
    ("GDPR", "Art.6", "HIPAA", "164.308(a)(1)", "related", 0.85),
    ("GDPR", "Art.15", "HIPAA", "164.312(a)(1)", "related", 0.85),
    ("GDPR", "Art.16", "HIPAA", "164.312(c)(1)", "related", 0.85),
    ("GDPR", "Art.17", "HIPAA", "164.312(c)(1)", "related", 0.85),
    ("GDPR", "Art.25", "HIPAA", "164.308(a)(1)", "related", 0.85),
    ("GDPR", "Art.28", "HIPAA", "164.308(b)(1)", "equivalent", 1.0),
    ("GDPR", "Art.32", "HIPAA", "164.312(a)(1)", "equivalent", 1.0),
    ("GDPR", "Art.32", "HIPAA", "164.312(b)", "related", 0.85),
    ("GDPR", "Art.32", "HIPAA", "164.312(e)(1)", "related", 0.85),
    ("GDPR", "Art.33", "HIPAA", "164.308(a)(6)", "equivalent", 1.0),
    ("GDPR", "Art.34", "HIPAA", "164.308(a)(6)", "related", 0.85),
    ("GDPR", "Art.35", "HIPAA", "164.308(a)(1)", "related", 0.85),

    # ─── SOC 2 ↔ PCI DSS v4.0 ───────────────────────────────────────────────
    ("SOC 2", "CC6.1", "PCI DSS v4.0", "7.1", "related", 0.85),
    ("SOC 2", "CC6.1", "PCI DSS v4.0", "9.1", "related", 0.85),
    ("SOC 2", "CC6.2", "PCI DSS v4.0", "8.1", "equivalent", 1.0),
    ("SOC 2", "CC6.2", "PCI DSS v4.0", "8.2", "equivalent", 1.0),
    ("SOC 2", "CC6.3", "PCI DSS v4.0", "7.2", "equivalent", 1.0),
    ("SOC 2", "CC6.6", "PCI DSS v4.0", "1.1", "related", 0.85),
    ("SOC 2", "CC6.6", "PCI DSS v4.0", "1.3", "related", 0.85),
    ("SOC 2", "CC6.6", "PCI DSS v4.0", "1.4", "related", 0.85),
    ("SOC 2", "CC6.7", "PCI DSS v4.0", "4.1", "equivalent", 1.0),
    ("SOC 2", "CC6.8", "PCI DSS v4.0", "5.1", "equivalent", 1.0),
    ("SOC 2", "CC6.8", "PCI DSS v4.0", "5.2", "equivalent", 1.0),
    ("SOC 2", "CC7.1", "PCI DSS v4.0", "2.1", "equivalent", 1.0),
    ("SOC 2", "CC7.1", "PCI DSS v4.0", "2.2", "equivalent", 1.0),
    ("SOC 2", "CC7.2", "PCI DSS v4.0", "10.2", "equivalent", 1.0),
    ("SOC 2", "CC7.3", "PCI DSS v4.0", "12.10", "related", 0.85),
    ("SOC 2", "CC7.4", "PCI DSS v4.0", "12.10", "equivalent", 1.0),
    ("SOC 2", "CC7.5", "PCI DSS v4.0", "12.10", "related", 0.85),
    ("SOC 2", "CC8.1", "PCI DSS v4.0", "6.3", "related", 0.85),
    ("SOC 2", "CC9.2", "PCI DSS v4.0", "12.8", "equivalent", 1.0),
    ("SOC 2", "C1.1", "PCI DSS v4.0", "3.1", "related", 0.85),
    ("SOC 2", "C1.1", "PCI DSS v4.0", "3.5", "related", 0.85),

    # ─── ISO 42001 ↔ ISO 9001:2015 ──────────────────────────────────────────
    ("ISO 42001", "5.1", "ISO 9001:2015", "5.1", "equivalent", 1.0),
    ("ISO 42001", "5.2", "ISO 9001:2015", "5.2", "equivalent", 1.0),
    ("ISO 42001", "5.3", "ISO 9001:2015", "5.1", "related", 0.85),
    ("ISO 42001", "6.1", "ISO 9001:2015", "6.1", "equivalent", 1.0),
    ("ISO 42001", "6.2", "ISO 9001:2015", "6.2", "related", 0.85),
    ("ISO 42001", "9.1", "ISO 9001:2015", "9.1", "equivalent", 1.0),
    ("ISO 42001", "9.2", "ISO 9001:2015", "9.2", "equivalent", 1.0),
    ("ISO 42001", "10.1", "ISO 9001:2015", "10.1", "equivalent", 1.0),
    ("ISO 42001", "10.2", "ISO 9001:2015", "10.3", "equivalent", 1.0),

    # ─── ISO 22301:2019 ↔ ISO 9001:2015 ──────────────────────────────────────
    ("ISO 22301:2019", "4.1", "ISO 9001:2015", "4.1", "equivalent", 1.0),
    ("ISO 22301:2019", "5.2", "ISO 9001:2015", "5.2", "related", 0.85),
    ("ISO 22301:2019", "6.1", "ISO 9001:2015", "6.1", "equivalent", 1.0),
    ("ISO 22301:2019", "9.1", "ISO 9001:2015", "9.1", "equivalent", 1.0),
    ("ISO 22301:2019", "9.2", "ISO 9001:2015", "9.2", "equivalent", 1.0),
    ("ISO 22301:2019", "10.1", "ISO 9001:2015", "10.1", "equivalent", 1.0),

    # ─── ISO 27001 ↔ ISO 9001:2015 ──────────────────────────────────────────
    ("ISO 27001:2022", "A.5.1", "ISO 9001:2015", "5.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.35", "ISO 9001:2015", "9.2", "related", 0.85),
    ("ISO 27001:2022", "A.5.36", "ISO 9001:2015", "9.1", "related", 0.85),
    ("ISO 27001:2022", "A.6.3", "ISO 9001:2015", "7.2", "related", 0.85),

    # ─── ISO 27001 ↔ ISO 20000-1:2018 ──────────────────────────────────────
    ("ISO 27001:2022", "A.5.24", "ISO 20000-1", "8.10", "related", 0.85),
    ("ISO 27001:2022", "A.5.26", "ISO 20000-1", "8.10", "related", 0.85),
    ("ISO 27001:2022", "A.5.27", "ISO 20000-1", "8.11", "related", 0.85),
    ("ISO 27001:2022", "A.8.9", "ISO 20000-1", "8.12", "related", 0.85),
    ("ISO 27001:2022", "A.8.16", "ISO 20000-1", "8.9", "related", 0.85),
]


def seed_control_mappings(db=None):
    """Load pre-researched control mappings into aria_control_mappings.

    Idempotent — skips if prebuilt mappings already exist (UNIQUE constraint on
    source_control_id, target_control_id prevents duplicates).

    Uses match_method='prebuilt' to distinguish from auto-generated or manual mappings.

    Args:
        db: Optional database connection. If None, acquires a fresh connection.

    Returns:
        int: Number of mappings inserted (0 if already seeded).
    """
    close_after = db is None
    if db is None:
        db = get_db()

    try:
        # Idempotency check: if prebuilt mappings already exist, skip
        existing = db.execute(
            "SELECT COUNT(*) FROM aria_control_mappings WHERE match_method='prebuilt'"
        ).fetchone()[0]
        if existing > 0:
            log.info("Prebuilt control mappings already seeded (%d pairs); skipping", existing)
            return existing

        inserted = 0
        skipped = 0

        for src_fw_name, src_ref, tgt_fw_name, tgt_ref, mtype, conf in CONTROL_MAPPINGS:
            try:
                # Resolve framework IDs from names
                src_fw_row = db.execute(
                    "SELECT id FROM frameworks WHERE name=%s OR name LIKE %s",
                    (src_fw_name, src_fw_name + '%')
                ).fetchone()
                tgt_fw_row = db.execute(
                    "SELECT id FROM frameworks WHERE name=%s OR name LIKE %s",
                    (tgt_fw_name, tgt_fw_name + '%')
                ).fetchone()

                if not src_fw_row or not tgt_fw_row:
                    skipped += 1
                    continue

                src_fw_id = src_fw_row[0]
                tgt_fw_id = tgt_fw_row[0]

                # Resolve control IDs from refs
                src_ctrl = db.execute(
                    "SELECT id FROM controls WHERE framework_id=%s AND ref=%s",
                    (src_fw_id, src_ref)
                ).fetchone()
                tgt_ctrl = db.execute(
                    "SELECT id FROM controls WHERE framework_id=%s AND ref=%s",
                    (tgt_fw_id, tgt_ref)
                ).fetchone()

                if not src_ctrl or not tgt_ctrl:
                    skipped += 1
                    continue

                src_ctrl_id = src_ctrl[0]
                tgt_ctrl_id = tgt_ctrl[0]

                # Insert with INSERT OR IGNORE to handle edge case of duplicates
                db.execute(
                    "INSERT INTO aria_control_mappings "
                    "(source_framework_id, source_control_id, target_framework_id, "
                    "target_control_id, mapping_type, confidence, notes, "
                    "auto_generated, match_method) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'prebuilt') ON CONFLICT DO NOTHING",
                    (src_fw_id, src_ctrl_id, tgt_fw_id, tgt_ctrl_id, mtype, conf, "")
                )
                inserted += 1

            except Exception as err:
                log.warning(
                    "Failed to insert mapping %s[%s] -> %s[%s]: %s",
                    src_fw_name, src_ref, tgt_fw_name, tgt_ref, err
                )
                skipped += 1
                continue

        db.commit()
        log.info("Seeded %d pre-built control mappings (%d skipped)", inserted, skipped)
        return inserted

    finally:
        if close_after:
            db.close()
