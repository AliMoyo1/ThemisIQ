"""
The record of processing activities, field by field.

Built from the supplied registers: the 40 column workbook (activity, purpose, systems, volume, the data tiers each with its own lawful
basis, necessity, further processing, source, collection, evidence, notice, disclosure, recipients, access, transfers, retention,
procedures, security, profiling, automated decisions, risk) and the Article 30 template (controller register 30(1)(a) to (g), processor
register 30(2)(a) to (d), owner, last review, row status, DPIA status). One table holds both registers: `controller_role` says which an
entry belongs to, and a processor entry shows the controller it acts for instead of the controller only fields.

A field with `store="column"` already had a column in `sentinel_ropa`; every other field lives in the `details` JSON column.
"""
from __future__ import annotations

from modules.sentinel.record_profiles.model import Cond, Field, Section

CONTROLLER = Cond("controller_role", "not_in", ("processor",))      # an entry with no role is a controller entry
PROCESSOR = Cond("controller_role", "in", ("processor",))
TRANSFERS = Cond("intl_transfers", "transfers")


def sections() -> tuple:
    return (
        Section("activity", "Activity and owners", (
            Field("processing_name", "Activity name", store="column", required=True, wide=True,
                  help="Name the activity so an outside reviewer understands it without internal acronyms."),
            Field("department", "Business function", store="column", help="The function that runs the activity: Finance, HR, Marketing."),
            Field("controller_role", "Role in this activity", "select", list_name="controller_roles", anchor="controller_identity",
                  help="Whether the organisation acts as a {controller}, a joint {controller} or a {processor} in this activity."),
            Field("description", "Description", "longtext", help="What the activity does, for whom and at what scale."),
            Field("owner", "Business owner", store="column", required=True,
                  help="The role accountable for the activity. Write the role as well as the name."),
            Field("data_owner", "Data owner", help="The role accountable for the data itself."),
            Field("technical_owner", "System or technical owner"),
            Field("status", "Status of this entry", "select", store="column", list_name="ropa_status",
                  help="Mark a superseded entry Obsolete, retained instead of deleting it, so the register shows its own history."),
            Field("last_reviewed", "Last reviewed on", "date"),
            Field("reviewed_by", "Last reviewed by"),
            Field("review_date", "Next review due", "date", store="column"),
            Field("acts_for", "{controller} this activity is carried out for", required=True, when=PROCESSOR, anchor="processor_identity"),
            Field("acts_for_contact", "Contact details of that {controller}", "longtext", when=PROCESSOR, anchor="processor_identity"),
            Field("acts_for_representative", "Representative of that {controller}, if any", when=PROCESSOR, anchor="representative"),
            Field("dpa_reference", "Data processing agreement", when=PROCESSOR, anchor="dpa",
                  help="Contract reference, version and date signed."),
            Field("processing_categories", "Categories of processing carried out", "longtext", required=True, when=PROCESSOR,
                  anchor="processor_categories", help="For example hosting, backup, support access, reporting."),
        )),
        Section("lawfulness", "Purpose and lawfulness", (
            Field("purpose", "Purposes of the processing", "longtext", store="column", required=True, when=CONTROLLER, anchor="purposes"),
            Field("necessity", "Why the processing is necessary for the purpose", "longtext", when=CONTROLLER),
            Field("further_processing", "Further processing for another purpose", "longtext", when=CONTROLLER, anchor="further",
                  help="Write None when the data is used only for the purpose above."),
            Field("legal_basis", "Lawful basis", "select", store="column", list_name="lawful_bases", required=True, when=CONTROLLER,
                  anchor="lawful_basis"),
            Field("legal_basis_evidence", "How the lawful basis is documented", "longtext", when=CONTROLLER,
                  help="Contracts, records of consent, policies or legislation that evidence the basis."),
            Field("legitimate_interest", "Legitimate interest pursued and the balancing test", "longtext",
                  when=Cond("legal_basis", "contains", "legitimate"), anchor="lia"),
            Field("consent_mechanism", "How consent is obtained and withdrawn", "longtext", when=Cond("legal_basis", "contains", "consent")),
            Field("special_condition", "Condition for processing {special_data}", "select", list_name="special_conditions", required=True,
                  when=Cond("special_categories", "nonempty"), anchor="special_condition"),
            Field("criminal_basis", "Basis for criminal conviction and offence data", "longtext", required=True,
                  when=Cond("special_categories", "contains", "criminal"), anchor="criminal_basis"),
            Field("children_basis", "Basis and safeguards for children's data", "longtext", required=True,
                  when=Cond("special_categories", "contains", "child"), anchor="children"),
            Field("confidential_basis", "Basis for confidential or financial data", "longtext", when=Cond("confidential_data", "nonempty")),
        )),
        Section("data", "Data and data subjects", (
            Field("data_subjects", "Categories of {subject}s", store="column", list_name="data_subjects", required=True, when=CONTROLLER,
                  anchor="data_subjects", help="Say which groups are vulnerable, such as children, employees or patients."),
            Field("subject_count", "Approximate number of {subject}s", store="column", when=CONTROLLER),
            Field("data_volume", "Volume of data", "select", list_name="volumes", when=CONTROLLER),
            Field("data_categories", "Categories of personal data", "multiselect", store="column", json_list=True, list_name="data_categories",
                  required=True, when=CONTROLLER, anchor="data_categories", wide=True),
            Field("confidential_data", "Confidential or financial data", "longtext", when=CONTROLLER,
                  help="Data that is not {special_data} but needs care: bank details, tax numbers, performance reviews."),
            Field("special_categories", "{special_data}", "multiselect", store="column", json_list=True, list_name="special_categories",
                  when=CONTROLLER, wide=True, help="Select every kind processed, or leave empty if none. Criminal and children's data are listed here."),
            Field("data_source", "Where the data comes from", "select", list_name="data_sources", when=CONTROLLER),
            Field("collection_method", "How the data is collected", "longtext", when=CONTROLLER),
            Field("notice_compliance", "How {subject}s are told about this processing", "longtext", when=CONTROLLER, anchor="notice"),
        )),
        Section("sharing", "Recipients, access and systems", (
            Field("recipients", "Categories of recipients", "longtext", store="column", required=True, when=CONTROLLER, anchor="recipients",
                  help="Include processors, authorities and any recipient in a third country."),
            Field("regular_disclosure", "Disclosed to recipients on a regular basis", "bool", when=CONTROLLER),
            Field("processors", "{processor}s engaged (named)", "longtext", store="column", anchor="dpa",
                  help="Name each one and what it does. For a processor entry, name the sub-processors and where they are."),
            Field("external_access", "External parties who can access the data", "longtext",
                  help="Consultants, auditors or the support staff of a supplier."),
            Field("systems", "Systems that process the data", "longtext", store="column"),
        )),
        Section("transfers", "Transfers outside {territory}", (
            Field("intl_transfers", "Transfers outside {territory}", store="column", required=True, anchor="transfers",
                  help="Write No, or Yes with the countries. A blank answer is not read as No."),
            Field("transfer_dest", "Countries or international organisations", store="column", required=True, when=TRANSFERS, anchor="transfers"),
            Field("transfer_safeguard", "Transfer mechanism", "select", store="column", list_name="transfer_tools", required=True,
                  when=TRANSFERS, anchor="transfers"),
            Field("transfer_safeguards_ref", "Documented safeguards or transfer risk assessment (reference)", required=True,
                  when=Cond("transfer_safeguard", "contains", "derogation"), anchor="transfers"),
            Field("processor_location", "Where a {processor} hosts or accesses the data outside {territory}", when=TRANSFERS),
            Field("intl_org_transfers", "Transfers to international organisations", when=TRANSFERS),
            Field("transfer_notes", "Notes on the transfers", "longtext", when=TRANSFERS),
        )),
        Section("retention", "Retention and deletion", (
            Field("retention_period", "Retention period", store="column", required=True, when=CONTROLLER, anchor="retention"),
            Field("retention_criteria", "What starts the retention period", when=CONTROLLER, help="For example the end of the contract or the closing of the case."),
            Field("retention_justification", "Why the data is kept that long", "longtext", when=CONTROLLER),
        )),
        Section("security", "Security and automated processing", (
            Field("security_measures", "General description of security measures", "longtext", store="column", required=True, anchor="security"),
            Field("procedures", "Procedures and policies that apply (reference)", "longtext"),
            Field("profiling", "Profiling", "longtext", when=CONTROLLER, anchor="profiling", help="Describe it, or write None."),
            Field("automated_decisions", "Automated decisions with legal or similar effect", "longtext", when=CONTROLLER, anchor="profiling",
                  help="Describe them, or write None."),
        )),
        Section("risk", "Risk and impact assessment", (
            Field("risk_level", "Risk level", "select", store="column", list_name="risk_levels"),
            Field("risk_rationale", "Why this risk level", "longtext"),
            Field("dpia_required", "A DPIA is required", "bool", store="column", anchor="dpia"),
            Field("dpia_status", "DPIA status", "select", list_name="dpia_status", anchor="dpia"),
            Field("notes", "Notes", "longtext", store="column"),
        )),
    )
