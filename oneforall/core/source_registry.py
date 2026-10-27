"""Reviewed public source catalogue shared by the authority consumers.

An entry identifies a publisher and an exact retrieval URL. It does not
assert that the page is law, that its text may be reproduced, or that a
change to the page changes any obligation. Those judgments remain with a
human reviewer in the owning module.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AuthoritySource:
    key: str
    jurisdiction: str
    title: str
    url: str
    content_type: str = "html"
    source_type: str = "authority page"
    rights: str = "link_and_short_excerpt"
    cadence: str = "weekly"
    parser_version: str = "visible-text-v1"
    frameworks: tuple[str, ...] = ()
    publisher: str = ""
    locale: str = "en"
    registry_version: str = "2026-10-27.v1"
    rights_evidence_url: str = ""
    monitored: bool = True

    @property
    def domain(self) -> str:
        return urlsplit(self.url).hostname or ""


# Preserve Sentinel's original keys and pinned URLs so existing captures stay
# verifiable. Rights are deliberately conservative: the public page may be
# cited with a short excerpt; bulk reproduction needs a separate rights review.
SENTINEL_KEYS = (
    "eu_gdpr", "eu_gdpr_obligations", "uk_ico_breach", "uk_duaa_commencement",
    "za_ir_compromise", "za_ir_fact_sheet_pdf", "ke_odpc_breach",
    "ca_opc_breach", "us_ca_ccpa", "au_oaic_ndb", "br_anpd_incidents",
)

SOURCES: dict[str, AuthoritySource] = {
    "eu_gdpr": AuthoritySource("eu_gdpr", "GDPR", "European Commission · EU data-protection legal framework", "https://commission.europa.eu/law/law-topic/data-protection/legal-framework-eu-data-protection_en", source_type="government legal-framework overview", frameworks=("GDPR",)),
    "eu_gdpr_obligations": AuthoritySource("eu_gdpr_obligations", "GDPR", "European Commission · GDPR obligations", "https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations_en", source_type="government obligations guidance", frameworks=("GDPR",)),
    "uk_ico_breach": AuthoritySource("uk_ico_breach", "UK GDPR", "ICO · personal data breaches", "https://ico.org.uk/for-organisations/report-a-breach/personal-data-breach/personal-data-breaches-a-guide/", source_type="regulator guidance", frameworks=("UK GDPR",)),
    "uk_duaa_commencement": AuthoritySource("uk_duaa_commencement", "UK GDPR", "UK Government · Data Use and Access Act commencement updates", "https://www.gov.uk/government/collections/data-use-and-access-act-2025", source_type="government commencement publication", frameworks=("UK GDPR",)),
    "za_ir_compromise": AuthoritySource("za_ir_compromise", "South Africa POPIA", "Information Regulator · security compromises", "https://inforegulator.org.za/2025/08/19/fact-sheet-handling-of-security-compromises/", source_type="regulator guidance", frameworks=("South Africa POPIA",)),
    "za_ir_fact_sheet_pdf": AuthoritySource("za_ir_fact_sheet_pdf", "South Africa POPIA", "Information Regulator · security compromise fact sheet PDF", "https://inforegulator.org.za/wp-content/uploads/2025/08/Fact-Sheet-on-security-compromises-2.pdf", content_type="pdf", source_type="regulator guidance · PDF", parser_version="isolated-pdf-v1", frameworks=("South Africa POPIA",)),
    "ke_odpc_breach": AuthoritySource("ke_odpc_breach", "Kenya DPA", "ODPC · report a data breach", "https://www.odpc.go.ke/report-a-data-breach/", source_type="regulator reporting page", frameworks=("Kenya DPA",)),
    "ca_opc_breach": AuthoritySource("ca_opc_breach", "Canada PIPEDA", "OPC · breach reporting", "https://www.priv.gc.ca/en/privacy-topics/privacy-for-businesses/privacy-breaches-at-your-business/gd_pb_201810/", source_type="regulator guidance", frameworks=("Canada PIPEDA",)),
    "us_ca_ccpa": AuthoritySource("us_ca_ccpa", "USA CCPA/CPRA", "California Attorney General · CCPA", "https://oag.ca.gov/privacy/ccpa", source_type="state attorney-general guidance", frameworks=("USA CCPA/CPRA",)),
    "au_oaic_ndb": AuthoritySource("au_oaic_ndb", "Australia Privacy Act", "OAIC · Notifiable Data Breaches scheme", "https://www.oaic.gov.au/privacy/notifiable-data-breaches/about-the-notifiable-data-breaches-scheme", source_type="regulator guidance", frameworks=("Australia Privacy Act",)),
    "br_anpd_incidents": AuthoritySource("br_anpd_incidents", "Brazil LGPD", "ANPD · comunicação de incidente de segurança", "https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis", source_type="regulator guidance · Portuguese", frameworks=("Brazil LGPD",)),
    # Publication pointers only. They are not legal source subscriptions or
    # permission to ingest licensed standard clauses into a tenant or model.
    "iso_27001_edition": AuthoritySource("iso_27001_edition", "International", "ISO/IEC 27001 edition notice",
        "https://www.iso.org/standard/27001", source_type="standards publication notice",
        rights="metadata_only", frameworks=("ISO/IEC 27001",), publisher="ISO",
        rights_evidence_url="https://www.iso.org/copyright.html", monitored=False),
    "iso_42001_edition": AuthoritySource("iso_42001_edition", "International", "ISO/IEC 42001 edition notice",
        "https://www.iso.org/standard/42001", source_type="standards publication notice",
        rights="metadata_only", frameworks=("ISO/IEC 42001",), publisher="ISO",
        rights_evidence_url="https://www.iso.org/copyright.html", monitored=False),
    "nist_csf_edition": AuthoritySource("nist_csf_edition", "USA", "NIST Cybersecurity Framework publication notice",
        "https://www.nist.gov/cyberframework", source_type="standards publication notice",
        rights="link_only", frameworks=("NIST CSF",), publisher="NIST", monitored=False),
    "pci_dss_edition": AuthoritySource("pci_dss_edition", "International", "PCI SSC document library",
        "https://www.pcisecuritystandards.org/document_library/", source_type="standards publication notice",
        rights="link_only", frameworks=("PCI DSS",), publisher="PCI SSC", monitored=False),
    "eu_gdpr_primary": AuthoritySource("eu_gdpr_primary", "GDPR", "EUR-Lex GDPR primary instrument",
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng/", source_type="primary legislation",
        rights="link_only", frameworks=("GDPR",), publisher="EUR-Lex", monitored=False),
}


def by_url(url: str) -> AuthoritySource:
    for source in SOURCES.values():
        if source.url == url:
            return source
    raise ValueError("Source is not pinned in the authority catalogue")


def citation_domains() -> tuple[str, ...]:
    # A publisher's presence in the catalogue does not grant permission to
    # send its text to a model. ISO's publication notices are pointers only.
    return tuple(sorted({item.domain for item in SOURCES.values()
                         if item.rights in {"link_and_short_excerpt", "public_reuse"}}))


# Horizon search is a lead-finding activity rather than a deterministic legal
# capture. These reviewed publisher domains are intentionally separate from
# the exact-URL catalogue above. Search hits must still pass the provider's
# citation check and remain unreviewed leads in ERM.
HORIZON_DOMAINS = frozenset({
    "iso.org", "weforum.org", "reuters.com", "nist.gov", "cisa.gov",
    "enisa.europa.eu", "csoonline.com", "darkreading.com", "gsma.com",
    "itu.int", "rbz.co.zw", "potraz.gov.zw", "fatf-gafi.org",
})


def horizon_domains(configured: list[str] | None = None) -> tuple[str, ...]:
    requested = set(configured) if configured is not None else HORIZON_DOMAINS
    return tuple(sorted(requested & HORIZON_DOMAINS))
