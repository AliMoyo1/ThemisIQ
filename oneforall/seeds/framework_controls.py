"""
One For All — Framework control seed data.

Pre-populates all 15 supported frameworks with their key controls.
Called from seed.py or can be run standalone.
"""
import logging
from core.framework_service import list_frameworks, bulk_create_controls, list_controls

log = logging.getLogger("oneforall.seed.controls")

# ═══════════════════════════════════════════════════════════════════════════════
# ISO 27001:2022 — Information Security Management (93 controls in Annex A)
# Top-level control groupings with representative controls
# ═══════════════════════════════════════════════════════════════════════════════
ISO_27001 = [
    {"ref": "A.5.1", "name": "Policies for information security", "category": "Organizational", "description": "Management direction for information security through policies"},
    {"ref": "A.5.2", "name": "Information security roles and responsibilities", "category": "Organizational", "description": "Define and allocate information security roles"},
    {"ref": "A.5.3", "name": "Segregation of duties", "category": "Organizational", "description": "Conflicting duties shall be segregated"},
    {"ref": "A.5.4", "name": "Management responsibilities", "category": "Organizational", "description": "Management shall require compliance with security policies"},
    {"ref": "A.5.5", "name": "Contact with authorities", "category": "Organizational", "description": "Maintain contact with relevant authorities"},
    {"ref": "A.5.6", "name": "Contact with special interest groups", "category": "Organizational", "description": "Maintain contact with security forums and associations"},
    {"ref": "A.5.7", "name": "Threat intelligence", "category": "Organizational", "description": "Collect and analyse threat intelligence"},
    {"ref": "A.5.8", "name": "Information security in project management", "category": "Organizational", "description": "Integrate security into project management"},
    {"ref": "A.5.9", "name": "Inventory of information and other associated assets", "category": "Organizational", "description": "Identify and maintain inventory of assets"},
    {"ref": "A.5.10", "name": "Acceptable use of information and other associated assets", "category": "Organizational", "description": "Rules for acceptable use of assets"},
    {"ref": "A.5.11", "name": "Return of assets", "category": "Organizational", "description": "Return assets on termination of employment"},
    {"ref": "A.5.12", "name": "Classification of information", "category": "Organizational", "description": "Classify information according to needs"},
    {"ref": "A.5.13", "name": "Labelling of information", "category": "Organizational", "description": "Label information in accordance with classification"},
    {"ref": "A.5.14", "name": "Information transfer", "category": "Organizational", "description": "Rules and procedures for information transfer"},
    {"ref": "A.5.15", "name": "Access control", "category": "Organizational", "description": "Rules for controlling access to information"},
    {"ref": "A.5.16", "name": "Identity management", "category": "Organizational", "description": "Full lifecycle of identities shall be managed"},
    {"ref": "A.5.17", "name": "Authentication information", "category": "Organizational", "description": "Manage allocation of authentication information"},
    {"ref": "A.5.18", "name": "Access rights", "category": "Organizational", "description": "Provision, review, and remove access rights"},
    {"ref": "A.5.23", "name": "Information security for use of cloud services", "category": "Organizational", "description": "Manage security for cloud service usage"},
    {"ref": "A.5.24", "name": "Information security incident management planning", "category": "Organizational", "description": "Plan and prepare for incident management"},
    {"ref": "A.5.25", "name": "Assessment and decision on information security events", "category": "Organizational", "description": "Assess and decide on security events"},
    {"ref": "A.5.26", "name": "Response to information security incidents", "category": "Organizational", "description": "Respond to incidents in accordance with procedures"},
    {"ref": "A.5.27", "name": "Learning from information security incidents", "category": "Organizational", "description": "Knowledge gained shall be used to strengthen controls"},
    {"ref": "A.5.29", "name": "Information security during disruption", "category": "Organizational", "description": "Maintain security during adverse conditions"},
    {"ref": "A.5.30", "name": "ICT readiness for business continuity", "category": "Organizational", "description": "ICT continuity plans shall be established"},
    {"ref": "A.5.31", "name": "Legal, statutory, regulatory and contractual requirements", "category": "Organizational", "description": "Identify and document compliance requirements"},
    {"ref": "A.5.34", "name": "Privacy and protection of PII", "category": "Organizational", "description": "Ensure privacy and PII protection per legislation"},
    {"ref": "A.5.35", "name": "Independent review of information security", "category": "Organizational", "description": "Independent review at planned intervals"},
    {"ref": "A.5.36", "name": "Compliance with policies, rules and standards", "category": "Organizational", "description": "Ensure compliance is regularly reviewed"},
    {"ref": "A.6.1", "name": "Screening", "category": "People", "description": "Background verification checks on candidates"},
    {"ref": "A.6.2", "name": "Terms and conditions of employment", "category": "People", "description": "Employment contracts shall state security responsibilities"},
    {"ref": "A.6.3", "name": "Information security awareness, education and training", "category": "People", "description": "Awareness programme for all personnel"},
    {"ref": "A.6.4", "name": "Disciplinary process", "category": "People", "description": "Formal disciplinary process for security violations"},
    {"ref": "A.6.5", "name": "Responsibilities after termination or change of employment", "category": "People", "description": "Security responsibilities that remain valid after employment"},
    {"ref": "A.6.7", "name": "Remote working", "category": "People", "description": "Security measures for remote working"},
    {"ref": "A.6.8", "name": "Information security event reporting", "category": "People", "description": "Personnel shall report security events"},
    {"ref": "A.7.1", "name": "Physical security perimeters", "category": "Physical", "description": "Security perimeters to protect areas with information"},
    {"ref": "A.7.2", "name": "Physical entry", "category": "Physical", "description": "Secure areas shall be protected by entry controls"},
    {"ref": "A.7.4", "name": "Physical security monitoring", "category": "Physical", "description": "Premises shall be continuously monitored"},
    {"ref": "A.7.7", "name": "Clear desk and clear screen", "category": "Physical", "description": "Clear desk and clear screen policy"},
    {"ref": "A.7.10", "name": "Storage media", "category": "Physical", "description": "Manage storage media through lifecycle"},
    {"ref": "A.8.1", "name": "User endpoint devices", "category": "Technological", "description": "Protect information on user endpoint devices"},
    {"ref": "A.8.2", "name": "Privileged access rights", "category": "Technological", "description": "Restrict and manage privileged access"},
    {"ref": "A.8.3", "name": "Information access restriction", "category": "Technological", "description": "Restrict access in accordance with access control policy"},
    {"ref": "A.8.5", "name": "Secure authentication", "category": "Technological", "description": "Secure authentication technologies and procedures"},
    {"ref": "A.8.7", "name": "Protection against malware", "category": "Technological", "description": "Protection against malware shall be implemented"},
    {"ref": "A.8.8", "name": "Management of technical vulnerabilities", "category": "Technological", "description": "Obtain information about technical vulnerabilities"},
    {"ref": "A.8.9", "name": "Configuration management", "category": "Technological", "description": "Configurations shall be established and managed"},
    {"ref": "A.8.12", "name": "Data leakage prevention", "category": "Technological", "description": "Apply data leakage prevention measures"},
    {"ref": "A.8.13", "name": "Information backup", "category": "Technological", "description": "Maintain backup copies of information and software"},
    {"ref": "A.8.15", "name": "Logging", "category": "Technological", "description": "Logs recording activities shall be produced and stored"},
    {"ref": "A.8.16", "name": "Monitoring activities", "category": "Technological", "description": "Networks, systems and applications shall be monitored"},
    {"ref": "A.8.20", "name": "Networks security", "category": "Technological", "description": "Secure, manage and control networks"},
    {"ref": "A.8.24", "name": "Use of cryptography", "category": "Technological", "description": "Rules for effective use of cryptography"},
    {"ref": "A.8.25", "name": "Secure development life cycle", "category": "Technological", "description": "Rules for secure development shall be established"},
    {"ref": "A.8.28", "name": "Secure coding", "category": "Technological", "description": "Secure coding principles shall be applied"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# ISO 42001 — AI Management System
# ═══════════════════════════════════════════════════════════════════════════════
ISO_42001 = [
    {"ref": "5.1", "name": "Leadership and commitment", "category": "Leadership", "description": "Top management shall demonstrate leadership for AI management"},
    {"ref": "5.2", "name": "AI policy", "category": "Leadership", "description": "Establish AI policy appropriate to the organization"},
    {"ref": "5.3", "name": "Roles, responsibilities and authorities", "category": "Leadership", "description": "Assign AI management roles and responsibilities"},
    {"ref": "6.1", "name": "Actions to address risks and opportunities", "category": "Planning", "description": "Determine risks and opportunities for AI systems"},
    {"ref": "6.2", "name": "AI objectives and planning", "category": "Planning", "description": "Establish measurable AI objectives"},
    {"ref": "A.2", "name": "AI impact assessment", "category": "Core", "description": "Conduct impact assessments for AI systems"},
    {"ref": "A.3", "name": "AI system lifecycle", "category": "Core", "description": "Manage AI systems through their entire lifecycle"},
    {"ref": "A.4", "name": "Data management", "category": "Core", "description": "Manage data quality, bias, and provenance for AI"},
    {"ref": "A.5", "name": "AI transparency", "category": "Core", "description": "Ensure transparency in AI decision-making"},
    {"ref": "A.6", "name": "AI explainability", "category": "Core", "description": "Provide explanations for AI system outputs"},
    {"ref": "A.7", "name": "Bias and fairness", "category": "Core", "description": "Identify, assess and mitigate AI bias"},
    {"ref": "A.8", "name": "Human oversight", "category": "Core", "description": "Ensure appropriate human oversight of AI systems"},
    {"ref": "A.9", "name": "AI security", "category": "Core", "description": "Protect AI systems from adversarial attacks"},
    {"ref": "A.10", "name": "Third-party AI", "category": "Core", "description": "Manage risks from third-party AI components"},
    {"ref": "9.1", "name": "Monitoring, measurement, analysis and evaluation", "category": "Performance", "description": "Monitor and measure AI system performance"},
    {"ref": "9.2", "name": "Internal audit", "category": "Performance", "description": "Conduct internal audits of AI management system"},
    {"ref": "10.1", "name": "Nonconformity and corrective action", "category": "Improvement", "description": "Address nonconformities in AI management"},
    {"ref": "10.2", "name": "Continual improvement", "category": "Improvement", "description": "Continually improve AI management system"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# SOC 2 Type II — Trust Services Criteria
# ═══════════════════════════════════════════════════════════════════════════════
SOC2 = [
    {"ref": "CC1.1", "name": "COSO Principle 1: Integrity and Ethical Values", "category": "Common Criteria", "description": "Demonstrate commitment to integrity and ethical values"},
    {"ref": "CC1.2", "name": "COSO Principle 2: Board Oversight", "category": "Common Criteria", "description": "Board exercises oversight of internal controls"},
    {"ref": "CC1.3", "name": "COSO Principle 3: Management Structure", "category": "Common Criteria", "description": "Establish structure, authority and responsibility"},
    {"ref": "CC1.4", "name": "COSO Principle 4: Competence", "category": "Common Criteria", "description": "Demonstrate commitment to competence"},
    {"ref": "CC1.5", "name": "COSO Principle 5: Accountability", "category": "Common Criteria", "description": "Hold individuals accountable for internal controls"},
    {"ref": "CC2.1", "name": "Internal Information", "category": "Communication", "description": "Generate and use relevant quality information"},
    {"ref": "CC2.2", "name": "Internal Communication", "category": "Communication", "description": "Internally communicate about internal controls"},
    {"ref": "CC2.3", "name": "External Communication", "category": "Communication", "description": "Communicate with external parties about internal controls"},
    {"ref": "CC3.1", "name": "Risk Objectives", "category": "Risk Assessment", "description": "Specify objectives to enable risk identification"},
    {"ref": "CC3.2", "name": "Risk Identification and Analysis", "category": "Risk Assessment", "description": "Identify and analyse risks"},
    {"ref": "CC3.3", "name": "Fraud Risk", "category": "Risk Assessment", "description": "Consider the potential for fraud"},
    {"ref": "CC3.4", "name": "Significant Changes", "category": "Risk Assessment", "description": "Identify and assess changes that could impact controls"},
    {"ref": "CC4.1", "name": "Monitoring Activities", "category": "Monitoring", "description": "Select and develop monitoring activities"},
    {"ref": "CC4.2", "name": "Evaluate and Communicate Deficiencies", "category": "Monitoring", "description": "Evaluate and communicate control deficiencies"},
    {"ref": "CC5.1", "name": "Control Activities for Risks", "category": "Control Activities", "description": "Select and develop control activities to mitigate risks"},
    {"ref": "CC5.2", "name": "Technology General Controls", "category": "Control Activities", "description": "Select and develop technology controls"},
    {"ref": "CC5.3", "name": "Policies and Procedures", "category": "Control Activities", "description": "Deploy controls through policies and procedures"},
    {"ref": "CC6.1", "name": "Logical and Physical Access", "category": "Logical Access", "description": "Implement logical access security over protected assets"},
    {"ref": "CC6.2", "name": "User Registration and Authorization", "category": "Logical Access", "description": "Register and authorize new users"},
    {"ref": "CC6.3", "name": "Role-Based Access", "category": "Logical Access", "description": "Establish role-based access controls"},
    {"ref": "CC6.6", "name": "System Boundary Protection", "category": "Logical Access", "description": "Restrict access at system boundaries"},
    {"ref": "CC6.7", "name": "Data Transmission Restriction", "category": "Logical Access", "description": "Restrict transmission of data to authorized parties"},
    {"ref": "CC6.8", "name": "Malicious Software Prevention", "category": "Logical Access", "description": "Prevent and detect malicious software"},
    {"ref": "CC7.1", "name": "Configuration Management", "category": "System Operations", "description": "Detect and monitor configuration changes"},
    {"ref": "CC7.2", "name": "Security Event Monitoring", "category": "System Operations", "description": "Monitor system components for anomalies"},
    {"ref": "CC7.3", "name": "Security Incident Evaluation", "category": "System Operations", "description": "Evaluate security events as incidents"},
    {"ref": "CC7.4", "name": "Incident Response", "category": "System Operations", "description": "Respond to identified security incidents"},
    {"ref": "CC7.5", "name": "Incident Recovery", "category": "System Operations", "description": "Identify and recover from security incidents"},
    {"ref": "CC8.1", "name": "Change Management", "category": "Change Management", "description": "Authorize, design, test and implement changes"},
    {"ref": "CC9.1", "name": "Risk Mitigation through Business Partners", "category": "Risk Mitigation", "description": "Identify and manage risk from business partners"},
    {"ref": "CC9.2", "name": "Vendor Risk Management", "category": "Risk Mitigation", "description": "Assess and manage vendor and partner risks"},
    {"ref": "A1.1", "name": "Availability Commitment", "category": "Availability", "description": "Maintain capacity to meet availability commitments"},
    {"ref": "A1.2", "name": "Environmental Protections", "category": "Availability", "description": "Protect against environmental threats"},
    {"ref": "A1.3", "name": "Recovery Testing", "category": "Availability", "description": "Test recovery plan procedures"},
    {"ref": "C1.1", "name": "Confidentiality Commitments", "category": "Confidentiality", "description": "Identify and maintain confidential information"},
    {"ref": "C1.2", "name": "Confidential Information Disposal", "category": "Confidentiality", "description": "Dispose of confidential information"},
    {"ref": "PI1.1", "name": "Processing Integrity Definitions", "category": "Processing Integrity", "description": "Define processing specifications"},
    {"ref": "PI1.2", "name": "System Input Controls", "category": "Processing Integrity", "description": "Ensure complete and accurate input processing"},
    {"ref": "P1.1", "name": "Privacy Notice", "category": "Privacy", "description": "Provide notice about privacy practices"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# PCI DSS v4.0
# ═══════════════════════════════════════════════════════════════════════════════
PCI_DSS = [
    {"ref": "1.1", "name": "Network security controls defined", "category": "Network Security", "description": "Processes and mechanisms for network security controls"},
    {"ref": "1.2", "name": "Network security controls configured", "category": "Network Security", "description": "NSCs are configured and maintained"},
    {"ref": "1.3", "name": "Network access restricted", "category": "Network Security", "description": "Restrict network access to and from CDE"},
    {"ref": "1.4", "name": "Trusted/untrusted network connections controlled", "category": "Network Security", "description": "Control connections between trusted and untrusted networks"},
    {"ref": "2.1", "name": "Secure configuration standards", "category": "Secure Configs", "description": "Processes for applying secure configurations"},
    {"ref": "2.2", "name": "System components configured securely", "category": "Secure Configs", "description": "Manage default accounts and settings securely"},
    {"ref": "3.1", "name": "Account data storage minimized", "category": "Protect Data", "description": "Processes for minimizing account data storage"},
    {"ref": "3.2", "name": "Sensitive authentication data not stored", "category": "Protect Data", "description": "SAD not stored after authorization"},
    {"ref": "3.5", "name": "PAN secured wherever stored", "category": "Protect Data", "description": "PAN is secured with strong cryptography"},
    {"ref": "4.1", "name": "Strong cryptography protects data in transit", "category": "Encryption", "description": "Protect cardholder data with strong cryptography during transmission"},
    {"ref": "5.1", "name": "Malware protection deployed", "category": "Malware", "description": "Processes for protecting against malware"},
    {"ref": "5.2", "name": "Malware prevented or detected", "category": "Malware", "description": "Malware is prevented, detected and addressed"},
    {"ref": "5.3", "name": "Anti-malware mechanisms active", "category": "Malware", "description": "Anti-malware mechanisms and programs are active"},
    {"ref": "6.1", "name": "Secure development processes", "category": "Secure Development", "description": "Processes for developing secure systems and software"},
    {"ref": "6.2", "name": "Custom software developed securely", "category": "Secure Development", "description": "Bespoke and custom software developed securely"},
    {"ref": "6.3", "name": "Security vulnerabilities identified and addressed", "category": "Secure Development", "description": "Identify and address vulnerabilities"},
    {"ref": "6.4", "name": "Public-facing web applications protected", "category": "Secure Development", "description": "Protect public-facing web applications from attacks"},
    {"ref": "7.1", "name": "Access limited by business need", "category": "Access Control", "description": "Processes restrict access by need to know"},
    {"ref": "7.2", "name": "Access appropriately defined", "category": "Access Control", "description": "Access to system components is appropriately defined"},
    {"ref": "8.1", "name": "User identification processes", "category": "Authentication", "description": "Processes for identification and authentication"},
    {"ref": "8.2", "name": "User identification enforced", "category": "Authentication", "description": "User identification is managed for users and admins"},
    {"ref": "8.3", "name": "Strong authentication established", "category": "Authentication", "description": "Strong authentication for users and administrators"},
    {"ref": "8.4", "name": "MFA implemented", "category": "Authentication", "description": "Multi-factor authentication implemented"},
    {"ref": "9.1", "name": "Physical access restricted", "category": "Physical Security", "description": "Processes restrict physical access to CHD"},
    {"ref": "10.1", "name": "Audit log processes defined", "category": "Logging", "description": "Processes for logging and monitoring"},
    {"ref": "10.2", "name": "Audit logs implemented", "category": "Logging", "description": "Audit logs capture specified activities"},
    {"ref": "10.4", "name": "Audit logs reviewed", "category": "Logging", "description": "Audit logs are reviewed for anomalies"},
    {"ref": "11.1", "name": "Security testing processes", "category": "Testing", "description": "Processes for regular security testing"},
    {"ref": "11.3", "name": "Vulnerabilities identified and managed", "category": "Testing", "description": "Vulnerability scans and penetration testing"},
    {"ref": "12.1", "name": "Information security policy", "category": "Policy", "description": "Comprehensive information security policy"},
    {"ref": "12.3", "name": "Risk assessment performed", "category": "Policy", "description": "Risks to CDE are formally identified and assessed"},
    {"ref": "12.6", "name": "Security awareness education", "category": "Policy", "description": "Security awareness training programme"},
    {"ref": "12.8", "name": "Third-party service providers managed", "category": "Policy", "description": "Risk from third-party service providers managed"},
    {"ref": "12.10", "name": "Security incident response plan", "category": "Policy", "description": "Incident response plan tested and ready"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# GDPR — Key Articles as Controls
# ═══════════════════════════════════════════════════════════════════════════════
GDPR = [
    {"ref": "Art.5", "name": "Principles of processing", "category": "Principles", "description": "Lawfulness, fairness, transparency, purpose limitation, data minimisation, accuracy, storage limitation, integrity, accountability"},
    {"ref": "Art.6", "name": "Lawfulness of processing", "category": "Legal Basis", "description": "At least one lawful basis must apply for processing"},
    {"ref": "Art.7", "name": "Conditions for consent", "category": "Legal Basis", "description": "Controller shall demonstrate consent; withdrawable"},
    {"ref": "Art.9", "name": "Special categories of personal data", "category": "Legal Basis", "description": "Processing of sensitive data prohibited unless exception applies"},
    {"ref": "Art.12", "name": "Transparent information", "category": "Data Subject Rights", "description": "Provide information in concise, transparent form"},
    {"ref": "Art.13", "name": "Information at collection", "category": "Data Subject Rights", "description": "Provide information when personal data is collected"},
    {"ref": "Art.15", "name": "Right of access", "category": "Data Subject Rights", "description": "Data subject right to access their personal data"},
    {"ref": "Art.16", "name": "Right to rectification", "category": "Data Subject Rights", "description": "Right to have inaccurate personal data rectified"},
    {"ref": "Art.17", "name": "Right to erasure", "category": "Data Subject Rights", "description": "Right to be forgotten under specified conditions"},
    {"ref": "Art.20", "name": "Right to data portability", "category": "Data Subject Rights", "description": "Right to receive personal data in machine-readable format"},
    {"ref": "Art.21", "name": "Right to object", "category": "Data Subject Rights", "description": "Right to object to processing"},
    {"ref": "Art.22", "name": "Automated decision-making", "category": "Data Subject Rights", "description": "Rights related to automated decisions including profiling"},
    {"ref": "Art.24", "name": "Responsibility of the controller", "category": "Accountability", "description": "Implement appropriate technical and organizational measures"},
    {"ref": "Art.25", "name": "Data protection by design and default", "category": "Accountability", "description": "Integrate data protection into processing activities"},
    {"ref": "Art.28", "name": "Processor obligations", "category": "Accountability", "description": "Use only processors with sufficient guarantees"},
    {"ref": "Art.30", "name": "Records of processing activities", "category": "Accountability", "description": "Maintain records of processing activities (RoPA)"},
    {"ref": "Art.32", "name": "Security of processing", "category": "Security", "description": "Implement appropriate security measures"},
    {"ref": "Art.33", "name": "Notification to supervisory authority", "category": "Breach", "description": "Notify authority within 72 hours of breach"},
    {"ref": "Art.34", "name": "Communication to data subject", "category": "Breach", "description": "Communicate breach to data subjects when high risk"},
    {"ref": "Art.35", "name": "Data protection impact assessment", "category": "DPIA", "description": "Conduct DPIA for high-risk processing"},
    {"ref": "Art.37", "name": "Designation of DPO", "category": "DPO", "description": "Designate a Data Protection Officer where required"},
    {"ref": "Art.44", "name": "General principle for transfers", "category": "Transfers", "description": "Transfer of personal data to third countries"},
    {"ref": "Art.46", "name": "Appropriate safeguards", "category": "Transfers", "description": "Safeguards for international transfers (SCCs, BCRs)"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# Zimbabwe CDPA
# ═══════════════════════════════════════════════════════════════════════════════
ZIMBABWE_CDPA = [
    {"ref": "S.4", "name": "Establishment of POTRAZ functions", "category": "Governance", "description": "Authority established for data protection oversight"},
    {"ref": "S.14", "name": "Registration of data controllers", "category": "Registration", "description": "Data controllers must register with the Authority"},
    {"ref": "S.16", "name": "Conditions for processing", "category": "Processing", "description": "Lawful conditions for processing personal data"},
    {"ref": "S.17", "name": "Consent requirements", "category": "Processing", "description": "Consent must be freely given, specific and informed"},
    {"ref": "S.18", "name": "Processing of sensitive data", "category": "Processing", "description": "Special conditions for sensitive personal data"},
    {"ref": "S.21", "name": "Data subject access rights", "category": "Rights", "description": "Right to access and correct personal data"},
    {"ref": "S.22", "name": "Right to object", "category": "Rights", "description": "Right to object to processing of personal data"},
    {"ref": "S.27", "name": "Security safeguards", "category": "Security", "description": "Appropriate technical and organizational measures"},
    {"ref": "S.28", "name": "Breach notification", "category": "Breach", "description": "Notify the Authority and data subjects of breaches"},
    {"ref": "S.29", "name": "Cross-border transfer restrictions", "category": "Transfers", "description": "Restrictions on international data transfers"},
    {"ref": "S.32", "name": "Cybersecurity obligations", "category": "Cyber", "description": "Implement cybersecurity measures for critical infrastructure"},
    {"ref": "S.34", "name": "Computer-related offences", "category": "Cyber", "description": "Criminal offences related to computer misuse"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# HIPAA — Security Rule Safeguards
# ═══════════════════════════════════════════════════════════════════════════════
HIPAA = [
    {"ref": "164.308(a)(1)", "name": "Security management process", "category": "Administrative", "description": "Implement policies to prevent, detect and correct security violations"},
    {"ref": "164.308(a)(2)", "name": "Assigned security responsibility", "category": "Administrative", "description": "Identify security official responsible for policies"},
    {"ref": "164.308(a)(3)", "name": "Workforce security", "category": "Administrative", "description": "Implement policies for workforce access to ePHI"},
    {"ref": "164.308(a)(4)", "name": "Information access management", "category": "Administrative", "description": "Implement policies authorizing access to ePHI"},
    {"ref": "164.308(a)(5)", "name": "Security awareness and training", "category": "Administrative", "description": "Security awareness and training program"},
    {"ref": "164.308(a)(6)", "name": "Security incident procedures", "category": "Administrative", "description": "Policies for reporting and responding to incidents"},
    {"ref": "164.308(a)(7)", "name": "Contingency plan", "category": "Administrative", "description": "Establish and maintain contingency plan"},
    {"ref": "164.308(a)(8)", "name": "Evaluation", "category": "Administrative", "description": "Perform periodic security evaluation"},
    {"ref": "164.308(b)(1)", "name": "Business associate contracts", "category": "Administrative", "description": "BAAs with satisfactory assurances"},
    {"ref": "164.310(a)(1)", "name": "Facility access controls", "category": "Physical", "description": "Limit physical access to ePHI systems"},
    {"ref": "164.310(b)", "name": "Workstation use", "category": "Physical", "description": "Policies for proper workstation use"},
    {"ref": "164.310(c)", "name": "Workstation security", "category": "Physical", "description": "Physical safeguards for workstations"},
    {"ref": "164.310(d)(1)", "name": "Device and media controls", "category": "Physical", "description": "Policies for receipt and removal of hardware/media"},
    {"ref": "164.312(a)(1)", "name": "Access control", "category": "Technical", "description": "Technical policies to limit access to ePHI"},
    {"ref": "164.312(b)", "name": "Audit controls", "category": "Technical", "description": "Hardware/software mechanisms for recording access"},
    {"ref": "164.312(c)(1)", "name": "Integrity controls", "category": "Technical", "description": "Policies to protect ePHI from improper alteration"},
    {"ref": "164.312(d)", "name": "Person or entity authentication", "category": "Technical", "description": "Verify identity of persons seeking access"},
    {"ref": "164.312(e)(1)", "name": "Transmission security", "category": "Technical", "description": "Technical security measures for ePHI transmission"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# Remaining frameworks (condensed representative controls)
# ═══════════════════════════════════════════════════════════════════════════════
ISO_9001 = [
    {"ref": "4.1", "name": "Understanding the organization and its context", "category": "Context", "description": "Determine external and internal issues relevant to QMS"},
    {"ref": "4.2", "name": "Understanding needs of interested parties", "category": "Context", "description": "Determine interested parties and their requirements"},
    {"ref": "5.1", "name": "Leadership and commitment", "category": "Leadership", "description": "Top management demonstrates leadership"},
    {"ref": "5.2", "name": "Quality policy", "category": "Leadership", "description": "Establish and communicate quality policy"},
    {"ref": "6.1", "name": "Actions to address risks and opportunities", "category": "Planning", "description": "Plan actions to address risks and opportunities"},
    {"ref": "7.1", "name": "Resources", "category": "Support", "description": "Determine and provide resources needed"},
    {"ref": "7.2", "name": "Competence", "category": "Support", "description": "Ensure persons are competent"},
    {"ref": "7.5", "name": "Documented information", "category": "Support", "description": "Create and control documented information"},
    {"ref": "8.1", "name": "Operational planning and control", "category": "Operation", "description": "Plan, implement and control processes"},
    {"ref": "8.4", "name": "Control of externally provided processes", "category": "Operation", "description": "Control outsourced processes and products"},
    {"ref": "9.1", "name": "Monitoring, measurement, analysis and evaluation", "category": "Performance", "description": "Determine what, how and when to monitor"},
    {"ref": "9.2", "name": "Internal audit", "category": "Performance", "description": "Conduct internal audits at planned intervals"},
    {"ref": "9.3", "name": "Management review", "category": "Performance", "description": "Management reviews the QMS"},
    {"ref": "10.1", "name": "Nonconformity and corrective action", "category": "Improvement", "description": "React to nonconformities and take corrective action"},
    {"ref": "10.3", "name": "Continual improvement", "category": "Improvement", "description": "Continually improve QMS suitability and effectiveness"},
]

ISO_22301 = [
    {"ref": "4.1", "name": "Understanding the organization", "category": "Context", "description": "Determine issues relevant to BCMS purpose"},
    {"ref": "5.2", "name": "BC policy", "category": "Leadership", "description": "Establish business continuity policy"},
    {"ref": "6.1", "name": "Actions to address risks", "category": "Planning", "description": "Address risks and opportunities to BCMS"},
    {"ref": "8.2", "name": "Business impact analysis", "category": "Operation", "description": "Implement and maintain BIA process"},
    {"ref": "8.3", "name": "Risk assessment", "category": "Operation", "description": "Identify and assess risks of disruption"},
    {"ref": "8.4", "name": "Business continuity strategies", "category": "Operation", "description": "Determine and select BC strategies"},
    {"ref": "8.5", "name": "Business continuity plans", "category": "Operation", "description": "Establish and implement BC plans"},
    {"ref": "8.6", "name": "Exercise and testing", "category": "Operation", "description": "Conduct exercises and tests of BC plans"},
    {"ref": "9.1", "name": "Monitoring and evaluation", "category": "Performance", "description": "Evaluate BCMS performance and effectiveness"},
    {"ref": "9.2", "name": "Internal audit", "category": "Performance", "description": "Conduct internal audits of BCMS"},
    {"ref": "10.1", "name": "Nonconformity and corrective action", "category": "Improvement", "description": "Address nonconformities"},
]

ISO_27701 = [
    {"ref": "5.2.1", "name": "Understanding the organization — privacy", "category": "Context", "description": "Determine PII processing context"},
    {"ref": "5.4.1.2", "name": "Privacy risk assessment", "category": "Planning", "description": "Conduct privacy-specific risk assessment"},
    {"ref": "6.2.1.1", "name": "PII inventory", "category": "Organizational", "description": "Identify and document PII processing activities"},
    {"ref": "6.3.2.1", "name": "PII access control", "category": "Organizational", "description": "Control access to PII"},
    {"ref": "6.5.2.1", "name": "Secure PII disposal", "category": "Technical", "description": "Securely dispose of PII no longer needed"},
    {"ref": "7.2.1", "name": "Identify and document purpose", "category": "PII Controller", "description": "Document the purpose for PII processing"},
    {"ref": "7.2.2", "name": "Identify lawful basis", "category": "PII Controller", "description": "Determine and document lawful basis"},
    {"ref": "7.3.1", "name": "Determine obligations to PII principals", "category": "PII Controller", "description": "Determine and fulfil obligations to data subjects"},
    {"ref": "7.4.1", "name": "Limit collection", "category": "PII Controller", "description": "Limit PII collection to what is needed"},
    {"ref": "7.5.1", "name": "DPIA process", "category": "PII Controller", "description": "Conduct data protection impact assessments"},
    {"ref": "8.2.1", "name": "Customer agreement", "category": "PII Processor", "description": "Ensure appropriate contracts with controllers"},
    {"ref": "8.5.1", "name": "PII transfer", "category": "PII Processor", "description": "Document and control PII transfers"},
]

ISO_20000 = [
    {"ref": "4.1", "name": "Understanding context", "category": "Context", "description": "Determine issues relevant to SMS"},
    {"ref": "5.1", "name": "Leadership", "category": "Leadership", "description": "Top management commitment to SMS"},
    {"ref": "8.2", "name": "Service portfolio", "category": "Service Design", "description": "Manage the service portfolio"},
    {"ref": "8.3", "name": "Relationship management", "category": "Relationship", "description": "Manage relationships with customers and suppliers"},
    {"ref": "8.5", "name": "Service level management", "category": "Service Design", "description": "Agree and manage service levels"},
    {"ref": "8.6", "name": "Service reporting", "category": "Service Design", "description": "Produce and deliver service reports"},
    {"ref": "8.7", "name": "Service continuity", "category": "Service Assurance", "description": "Ensure service continuity meets agreed requirements"},
    {"ref": "8.8", "name": "Service availability", "category": "Service Assurance", "description": "Monitor and manage service availability"},
    {"ref": "8.9", "name": "Capacity management", "category": "Service Assurance", "description": "Manage capacity to meet current and future demands"},
    {"ref": "8.10", "name": "Incident management", "category": "Resolution", "description": "Manage incidents to restore services"},
    {"ref": "8.11", "name": "Problem management", "category": "Resolution", "description": "Identify and manage problems"},
    {"ref": "8.12", "name": "Change management", "category": "Control", "description": "Control changes to services and components"},
    {"ref": "8.13", "name": "Release management", "category": "Control", "description": "Manage releases into the live environment"},
]

ISO_27017 = [
    {"ref": "CLD.6.3.1", "name": "Shared roles and responsibilities", "category": "Organization", "description": "Define shared responsibilities between cloud customer and provider"},
    {"ref": "CLD.8.1.5", "name": "Removal of cloud assets", "category": "Asset", "description": "Assets upon termination of cloud agreement"},
    {"ref": "CLD.9.5.1", "name": "Segregation in virtual environments", "category": "Access", "description": "Virtual machine hardening and segregation"},
    {"ref": "CLD.9.5.2", "name": "Virtual machine hardening", "category": "Access", "description": "Secure virtual machine images and configurations"},
    {"ref": "CLD.12.1.5", "name": "Administrator operational security", "category": "Operations", "description": "Cloud service administrator operations procedures"},
    {"ref": "CLD.12.4.5", "name": "Monitoring of cloud services", "category": "Operations", "description": "Cloud customer monitoring capabilities"},
    {"ref": "CLD.13.1.4", "name": "Alignment of security management", "category": "Communications", "description": "Align security management for virtual and physical networks"},
    {"ref": "A.5.15+", "name": "Access control policy for cloud", "category": "Cloud Extended", "description": "Cloud-specific access control requirements"},
    {"ref": "A.8.1+", "name": "Asset inventory for cloud", "category": "Cloud Extended", "description": "Include cloud assets in asset inventory"},
    {"ref": "A.8.13+", "name": "Backup of cloud data", "category": "Cloud Extended", "description": "Backup procedures for cloud-stored information"},
]

ISO_31000 = [
    {"ref": "5.2", "name": "Leadership and commitment", "category": "Framework", "description": "Management commitment to risk management"},
    {"ref": "5.4.1", "name": "Understanding the organization", "category": "Framework", "description": "Understand the organization and its context"},
    {"ref": "5.4.2", "name": "Risk management policy", "category": "Framework", "description": "Articulate risk management policy"},
    {"ref": "5.5", "name": "Integration", "category": "Framework", "description": "Integrate risk management into organizational activities"},
    {"ref": "6.3", "name": "Scope, context and criteria", "category": "Process", "description": "Define scope and risk criteria"},
    {"ref": "6.4.1", "name": "Risk identification", "category": "Process", "description": "Find, recognize and describe risks"},
    {"ref": "6.4.2", "name": "Risk analysis", "category": "Process", "description": "Comprehend the nature and level of risk"},
    {"ref": "6.4.3", "name": "Risk evaluation", "category": "Process", "description": "Compare analysis results with risk criteria"},
    {"ref": "6.5", "name": "Risk treatment", "category": "Process", "description": "Select and implement risk treatment options"},
    {"ref": "6.6", "name": "Monitoring and review", "category": "Process", "description": "Monitor and review the risk management process"},
    {"ref": "6.7", "name": "Recording and reporting", "category": "Process", "description": "Document and communicate risk management activities"},
]

ISO_14001 = [
    {"ref": "4.1", "name": "Understanding the organization", "category": "Context", "description": "Determine issues relevant to EMS"},
    {"ref": "4.3", "name": "Scope of the EMS", "category": "Context", "description": "Determine scope of environmental management system"},
    {"ref": "5.2", "name": "Environmental policy", "category": "Leadership", "description": "Establish environmental policy"},
    {"ref": "6.1.2", "name": "Environmental aspects", "category": "Planning", "description": "Determine environmental aspects and impacts"},
    {"ref": "6.1.3", "name": "Compliance obligations", "category": "Planning", "description": "Determine compliance obligations"},
    {"ref": "6.2", "name": "Environmental objectives", "category": "Planning", "description": "Establish environmental objectives and plans"},
    {"ref": "7.2", "name": "Competence", "category": "Support", "description": "Ensure competence of persons affecting environmental performance"},
    {"ref": "8.1", "name": "Operational planning and control", "category": "Operation", "description": "Plan and control environmental processes"},
    {"ref": "8.2", "name": "Emergency preparedness and response", "category": "Operation", "description": "Prepare for and respond to emergency situations"},
    {"ref": "9.1.2", "name": "Evaluation of compliance", "category": "Performance", "description": "Evaluate compliance with legal obligations"},
    {"ref": "9.2", "name": "Internal audit", "category": "Performance", "description": "Conduct internal audits of EMS"},
    {"ref": "10.2", "name": "Continual improvement", "category": "Improvement", "description": "Continually improve EMS effectiveness"},
]

ISO_50001 = [
    {"ref": "4.1", "name": "Understanding the organization", "category": "Context", "description": "Determine issues relevant to EnMS"},
    {"ref": "5.2", "name": "Energy policy", "category": "Leadership", "description": "Establish energy policy"},
    {"ref": "6.1", "name": "Actions to address risks", "category": "Planning", "description": "Address risks and opportunities"},
    {"ref": "6.2", "name": "Energy objectives and targets", "category": "Planning", "description": "Establish energy objectives and action plans"},
    {"ref": "6.3", "name": "Energy review", "category": "Planning", "description": "Analyse energy use and consumption"},
    {"ref": "6.4", "name": "Energy performance indicators", "category": "Planning", "description": "Determine EnPIs for energy performance"},
    {"ref": "6.5", "name": "Energy baseline", "category": "Planning", "description": "Establish energy baselines"},
    {"ref": "6.6", "name": "Energy data collection", "category": "Planning", "description": "Plan for collection of energy data"},
    {"ref": "8.1", "name": "Operational planning and control", "category": "Operation", "description": "Plan and control energy-related processes"},
    {"ref": "8.2", "name": "Design", "category": "Operation", "description": "Consider energy performance in design"},
    {"ref": "8.3", "name": "Procurement", "category": "Operation", "description": "Consider energy performance in procurement"},
    {"ref": "9.1", "name": "Monitoring and measurement", "category": "Performance", "description": "Monitor, measure and analyse energy performance"},
]

# ═══════════════════════════════════════════════════════════════════════════════
# ISO 45001:2018 — Occupational Health and Safety Management System
# ═══════════════════════════════════════════════════════════════════════════════
ISO_45001 = [
    {"ref": "4.1", "name": "Understanding the organization and its context", "category": "Context", "description": "Determine external and internal issues relevant to OH&S outcomes"},
    {"ref": "4.2", "name": "Understanding needs of workers and interested parties", "category": "Context", "description": "Determine interested parties, including workers, and their OH&S requirements"},
    {"ref": "4.3", "name": "Determining the scope of the OH&S management system", "category": "Context", "description": "Determine boundaries and applicability of the OH&S management system"},
    {"ref": "5.1", "name": "Leadership and commitment", "category": "Leadership", "description": "Top management demonstrates leadership and commitment to the OH&S management system"},
    {"ref": "5.2", "name": "OH&S policy", "category": "Leadership", "description": "Establish, implement and maintain an OH&S policy with commitment to safe and healthy working conditions"},
    {"ref": "5.3", "name": "Organizational roles, responsibilities and authorities", "category": "Leadership", "description": "Assign and communicate roles, responsibilities and authorities for the OH&S system"},
    {"ref": "5.4", "name": "Consultation and participation of workers", "category": "Leadership", "description": "Establish processes for consultation and participation of workers at all levels"},
    {"ref": "6.1.1", "name": "Actions to address risks and opportunities (general)", "category": "Planning", "description": "Plan actions to address OH&S risks, opportunities, legal requirements and emergency preparedness"},
    {"ref": "6.1.2", "name": "Hazard identification and assessment of risks", "category": "Planning", "description": "Establish processes for ongoing hazard identification considering routine and non-routine activities, human factors, and past incidents"},
    {"ref": "6.1.3", "name": "Determination of legal and other requirements", "category": "Planning", "description": "Determine and access applicable legal requirements and other OH&S obligations"},
    {"ref": "6.1.4", "name": "Planning action", "category": "Planning", "description": "Plan actions to address risks, opportunities, legal requirements, and prepare for emergencies"},
    {"ref": "6.2", "name": "OH&S objectives and planning to achieve them", "category": "Planning", "description": "Establish measurable OH&S objectives consistent with the OH&S policy"},
    {"ref": "7.1", "name": "Resources", "category": "Support", "description": "Determine and provide resources needed for the OH&S management system"},
    {"ref": "7.2", "name": "Competence", "category": "Support", "description": "Determine competence of workers that affects OH&S performance, ensure training and qualifications"},
    {"ref": "7.3", "name": "Awareness", "category": "Support", "description": "Workers shall be aware of the OH&S policy, hazards, and their right to remove themselves from danger"},
    {"ref": "7.4", "name": "Communication", "category": "Support", "description": "Determine internal and external communications relevant to the OH&S management system"},
    {"ref": "7.5", "name": "Documented information", "category": "Support", "description": "Create, update and control documented information required by the OH&S system"},
    {"ref": "8.1.1", "name": "Operational planning and control (general)", "category": "Operation", "description": "Plan, implement, control and maintain processes to meet OH&S requirements"},
    {"ref": "8.1.2", "name": "Eliminating hazards and reducing OH&S risks", "category": "Operation", "description": "Eliminate hazards and reduce risks using the hierarchy of controls: eliminate, substitute, engineer, administer, PPE"},
    {"ref": "8.1.3", "name": "Management of change", "category": "Operation", "description": "Manage planned and unplanned changes that impact OH&S performance"},
    {"ref": "8.1.4", "name": "Procurement and contractors", "category": "Operation", "description": "Control procurement processes and coordinate with contractors to ensure OH&S requirements are met"},
    {"ref": "8.2", "name": "Emergency preparedness and response", "category": "Operation", "description": "Establish processes for emergency preparedness including planned response, first aid, drills and post-incident evaluation"},
    {"ref": "9.1.1", "name": "Monitoring, measurement, analysis and evaluation", "category": "Performance", "description": "Determine what to monitor and measure, methods of analysis, and criteria for evaluating OH&S performance"},
    {"ref": "9.1.2", "name": "Evaluation of compliance", "category": "Performance", "description": "Establish processes to evaluate fulfilment of legal requirements and other obligations"},
    {"ref": "9.2", "name": "Internal audit", "category": "Performance", "description": "Conduct internal audits at planned intervals to verify the OH&S system conforms and is effective"},
    {"ref": "9.3", "name": "Management review", "category": "Performance", "description": "Top management reviews the OH&S system including trends in incidents, risks, and consultation outcomes"},
    {"ref": "10.2", "name": "Incident, nonconformity and corrective action", "category": "Improvement", "description": "React to incidents and nonconformities, investigate root causes, and take corrective action to prevent recurrence"},
    {"ref": "10.3", "name": "Continual improvement", "category": "Improvement", "description": "Continually improve the suitability, adequacy and effectiveness of the OH&S management system"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# Mapping: framework name → controls list
# ═══════════════════════════════════════════════════════════════════════════════
FRAMEWORK_CONTROLS = {
    "ISO 27001:2022": ISO_27001,
    "ISO 42001": ISO_42001,
    "SOC 2 Type II": SOC2,
    "PCI DSS v4.0": PCI_DSS,
    "GDPR": GDPR,
    "Zimbabwe CDPA": ZIMBABWE_CDPA,
    "HIPAA": HIPAA,
    "ISO 9001:2015": ISO_9001,
    "ISO 22301:2019": ISO_22301,
    "ISO 27701:2019": ISO_27701,
    "ISO 20000-1:2018": ISO_20000,
    "ISO 27017:2015": ISO_27017,
    "ISO 31000:2018": ISO_31000,
    "ISO 14001:2015": ISO_14001,
    "ISO 50001:2018": ISO_50001,
    "ISO 45001:2018": ISO_45001,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Curated cross-framework control mappings
# Based on official standard annexes (e.g. ISO 42001 Annex B mapping to ISO 27001)
# Key: (fw_name_a, fw_name_b)  Value: list of (ref_a, ref_b) pairs
# ═══════════════════════════════════════════════════════════════════════════════
CURATED_MAPPINGS = {
    # ── ISO 27001 <-> ISO 42001 (Annex B official mapping) ───────────────────
    ("ISO 27001:2022", "ISO 42001"): [
        ("A.5.1",  "5.2"),   ("A.5.2",  "5.3"),   ("A.5.4",  "5.1"),
        ("A.5.7",  "6.1"),   ("A.5.8",  "6.2"),   ("A.5.12", "A.4"),
        ("A.5.14", "A.4"),   ("A.5.15", "A.8"),   ("A.5.23", "A.10"),
        ("A.5.31", "A.2"),   ("A.5.34", "A.2"),   ("A.5.35", "9.2"),
        ("A.5.36", "10.1"),  ("A.6.3",  "A.5"),   ("A.6.3",  "A.6"),
        ("A.8.5",  "A.9"),   ("A.8.7",  "A.9"),   ("A.8.8",  "A.9"),
        ("A.8.9",  "A.3"),   ("A.8.16", "9.1"),   ("A.8.25", "A.3"),
        ("A.8.28", "A.3"),   ("A.5.24", "A.2"),   ("A.5.9",  "A.4"),
        ("A.5.10", "A.4"),   ("A.5.25", "A.7"),   ("A.5.29", "A.3"),
        ("A.5.30", "A.3"),   ("A.8.12", "A.4"),   ("A.8.13", "A.3"),
        ("A.8.15", "9.1"),   ("A.8.20", "A.9"),   ("A.8.24", "A.9"),
    ],

    # ── ISO 27001 <-> SOC 2 (AICPA TSC mapping) ─────────────────────────────
    ("ISO 27001:2022", "SOC 2 Type II"): [
        ("A.5.1",  "CC5.3"),  ("A.5.2",  "CC1.3"),  ("A.5.4",  "CC1.1"),
        ("A.5.3",  "CC1.5"),  ("A.5.7",  "CC3.2"),  ("A.5.12", "C1.1"),
        ("A.5.14", "CC6.7"),  ("A.5.15", "CC6.1"),  ("A.5.16", "CC6.2"),
        ("A.5.18", "CC6.3"),  ("A.5.23", "CC9.2"),  ("A.5.24", "CC7.3"),
        ("A.5.25", "CC7.3"),  ("A.5.26", "CC7.4"),  ("A.5.27", "CC7.5"),
        ("A.5.29", "A1.1"),   ("A.5.30", "A1.3"),   ("A.5.31", "CC3.1"),
        ("A.5.34", "P1.1"),   ("A.5.35", "CC4.1"),  ("A.5.36", "CC4.2"),
        ("A.6.1",  "CC1.4"),  ("A.6.3",  "CC1.4"),  ("A.7.1",  "CC6.1"),
        ("A.8.5",  "CC6.2"),  ("A.8.7",  "CC6.8"),  ("A.8.8",  "CC7.1"),
        ("A.8.9",  "CC7.1"),  ("A.8.12", "C1.1"),   ("A.8.13", "A1.1"),
        ("A.8.15", "CC7.2"),  ("A.8.16", "CC4.1"),  ("A.8.20", "CC6.6"),
        ("A.8.24", "CC6.7"),  ("A.8.25", "CC8.1"),
    ],

    # ── ISO 27001 <-> PCI DSS v4.0 ──────────────────────────────────────────
    ("ISO 27001:2022", "PCI DSS v4.0"): [
        ("A.5.1",  "12.1"),  ("A.5.7",  "12.3"),  ("A.5.15", "7.1"),
        ("A.5.16", "8.1"),   ("A.5.17", "8.3"),   ("A.5.18", "7.2"),
        ("A.5.23", "12.8"),  ("A.5.24", "12.10"), ("A.5.26", "12.10"),
        ("A.6.3",  "12.6"),  ("A.7.1",  "9.1"),   ("A.8.2",  "8.2"),
        ("A.8.5",  "8.3"),   ("A.8.7",  "5.1"),   ("A.8.8",  "6.3"),
        ("A.8.9",  "2.1"),   ("A.8.12", "3.1"),   ("A.8.15", "10.2"),
        ("A.8.16", "10.4"),  ("A.8.20", "1.1"),   ("A.8.24", "4.1"),
        ("A.8.25", "6.1"),   ("A.8.28", "6.2"),   ("A.5.14", "4.1"),
    ],

    # ── ISO 27001 <-> GDPR ───────────────────────────────────────────────────
    ("ISO 27001:2022", "GDPR"): [
        ("A.5.1",  "Art.24"),  ("A.5.12", "Art.9"),   ("A.5.14", "Art.44"),
        ("A.5.15", "Art.32"),  ("A.5.24", "Art.33"),  ("A.5.26", "Art.33"),
        ("A.5.31", "Art.5"),   ("A.5.34", "Art.25"),  ("A.5.35", "Art.35"),
        ("A.6.3",  "Art.24"),  ("A.8.12", "Art.32"),  ("A.8.24", "Art.32"),
        ("A.5.9",  "Art.30"),  ("A.5.18", "Art.32"),  ("A.6.8",  "Art.33"),
    ],

    # ── ISO 27001 <-> HIPAA ──────────────────────────────────────────────────
    ("ISO 27001:2022", "HIPAA"): [
        ("A.5.1",  "164.308(a)(1)"),  ("A.5.2",  "164.308(a)(2)"),
        ("A.5.15", "164.312(a)(1)"),  ("A.5.17", "164.312(d)"),
        ("A.5.18", "164.308(a)(4)"),  ("A.5.24", "164.308(a)(6)"),
        ("A.5.29", "164.308(a)(7)"),  ("A.5.35", "164.308(a)(8)"),
        ("A.6.1",  "164.308(a)(3)"),  ("A.6.3",  "164.308(a)(5)"),
        ("A.7.1",  "164.310(a)(1)"),  ("A.8.1",  "164.310(b)"),
        ("A.8.5",  "164.312(d)"),     ("A.8.15", "164.312(b)"),
        ("A.8.24", "164.312(e)(1)"),  ("A.5.23", "164.308(b)(1)"),
        ("A.7.10", "164.310(d)(1)"),
    ],

    # ── ISO 27001 <-> ISO 27701 (privacy extension) ─────────────────────────
    ("ISO 27001:2022", "ISO 27701:2019"): [
        ("A.5.15", "6.3.2.1"),  ("A.5.34", "7.2.1"),
        ("A.5.31", "7.2.2"),    ("A.5.12", "6.2.1.1"),
        ("A.5.9",  "6.2.1.1"),  ("A.5.14", "8.5.1"),
        ("A.5.23", "8.2.1"),    ("A.5.35", "7.5.1"),
    ],

    # ── ISO 27001 <-> ISO 27017 (cloud security) ────────────────────────────
    ("ISO 27001:2022", "ISO 27017:2015"): [
        ("A.5.2",  "CLD.6.3.1"),   ("A.5.15", "A.5.15+"),
        ("A.5.23", "CLD.9.5.1"),   ("A.8.1",  "A.8.1+"),
        ("A.8.13", "A.8.13+"),     ("A.8.16", "CLD.12.4.5"),
        ("A.8.9",  "CLD.9.5.2"),   ("A.8.20", "CLD.13.1.4"),
        ("A.8.15", "CLD.12.1.5"),
    ],

    # ── ISO 27001 <-> ISO 22301 (business continuity) ────────────────────────
    ("ISO 27001:2022", "ISO 22301:2019"): [
        ("A.5.29", "8.5"),   ("A.5.30", "8.4"),   ("A.5.30", "8.6"),
        ("A.5.7",  "8.3"),   ("A.5.31", "6.1"),   ("A.5.35", "9.2"),
        ("A.5.36", "10.1"),  ("A.5.24", "8.5"),
    ],

    # ── ISO 27001 <-> ISO 9001 (quality, Annex SL overlap) ──────────────────
    ("ISO 27001:2022", "ISO 9001:2015"): [
        ("A.5.1",  "5.2"),   ("A.5.2",  "5.1"),   ("A.5.31", "4.2"),
        ("A.5.35", "9.2"),   ("A.5.36", "10.1"),  ("A.6.3",  "7.2"),
        ("A.5.23", "8.4"),   ("A.8.16", "9.1"),
    ],

    # ── ISO 27001 <-> ISO 20000-1 (IT service management) ───────────────────
    ("ISO 27001:2022", "ISO 20000-1:2018"): [
        ("A.5.2",  "5.1"),    ("A.5.24", "8.10"),  ("A.5.26", "8.10"),
        ("A.5.29", "8.7"),    ("A.5.30", "8.7"),   ("A.8.8",  "8.11"),
        ("A.8.9",  "8.12"),   ("A.8.25", "8.13"),  ("A.8.16", "8.6"),
    ],

    # ── ISO 27001 <-> ISO 31000 (risk management) ────────────────────────────
    ("ISO 27001:2022", "ISO 31000:2018"): [
        ("A.5.7",  "6.4.1"),  ("A.5.31", "6.3"),   ("A.5.35", "6.6"),
        ("A.5.1",  "5.4.2"),  ("A.5.4",  "5.2"),
    ],

    # ── GDPR <-> Zimbabwe CDPA (parallel data protection laws) ───────────────
    ("GDPR", "Zimbabwe CDPA"): [
        ("Art.5",  "S.16"),  ("Art.6",  "S.16"),  ("Art.7",  "S.17"),
        ("Art.9",  "S.18"),  ("Art.15", "S.21"),  ("Art.21", "S.22"),
        ("Art.32", "S.27"),  ("Art.33", "S.28"),  ("Art.34", "S.28"),
        ("Art.44", "S.29"),  ("Art.37", "S.4"),   ("Art.25", "S.32"),
    ],

    # ── GDPR <-> ISO 27701 (privacy management) ─────────────────────────────
    ("GDPR", "ISO 27701:2019"): [
        ("Art.5",  "7.2.1"),   ("Art.6",  "7.2.2"),  ("Art.7",  "7.4.1"),
        ("Art.15", "7.3.1"),   ("Art.25", "5.4.1.2"),("Art.28", "8.2.1"),
        ("Art.30", "6.2.1.1"), ("Art.32", "6.3.2.1"),("Art.35", "7.5.1"),
        ("Art.44", "8.5.1"),
    ],

    # ── GDPR <-> HIPAA (health data protection overlap) ──────────────────────
    ("GDPR", "HIPAA"): [
        ("Art.5",  "164.308(a)(1)"),  ("Art.32", "164.312(a)(1)"),
        ("Art.33", "164.308(a)(6)"),  ("Art.25", "164.308(a)(1)"),
        ("Art.24", "164.308(a)(2)"),  ("Art.44", "164.312(e)(1)"),
    ],

    # ── SOC 2 <-> PCI DSS ───────────────────────────────────────────────────
    ("SOC 2 Type II", "PCI DSS v4.0"): [
        ("CC5.3",  "12.1"),  ("CC3.2",  "12.3"),  ("CC6.1",  "7.1"),
        ("CC6.2",  "8.1"),   ("CC6.3",  "7.2"),   ("CC6.6",  "1.1"),
        ("CC6.7",  "4.1"),   ("CC6.8",  "5.1"),   ("CC7.1",  "2.1"),
        ("CC7.2",  "10.2"),  ("CC7.4",  "12.10"), ("CC8.1",  "6.1"),
        ("CC9.2",  "12.8"),  ("CC1.4",  "12.6"),  ("A1.2",   "9.1"),
    ],

    # ── SOC 2 <-> HIPAA ─────────────────────────────────────────────────────
    ("SOC 2 Type II", "HIPAA"): [
        ("CC1.3",  "164.308(a)(2)"),  ("CC5.3",  "164.308(a)(1)"),
        ("CC6.1",  "164.312(a)(1)"),  ("CC6.2",  "164.308(a)(4)"),
        ("CC7.2",  "164.312(b)"),     ("CC7.4",  "164.308(a)(6)"),
        ("CC9.2",  "164.308(b)(1)"),  ("A1.1",   "164.308(a)(7)"),
        ("CC1.4",  "164.308(a)(5)"),  ("CC6.8",  "164.308(a)(5)"),
    ],

    # ── Annex SL: ISO 9001 <-> ISO 22301 ────────────────────────────────────
    ("ISO 9001:2015", "ISO 22301:2019"): [
        ("5.1",  "5.2"),   ("6.1",  "6.1"),   ("9.1",  "9.1"),
        ("9.2",  "9.2"),   ("10.1", "10.1"),  ("4.1",  "4.1"),
    ],

    # ── Annex SL: ISO 9001 <-> ISO 14001 ────────────────────────────────────
    ("ISO 9001:2015", "ISO 14001:2015"): [
        ("4.1",  "4.1"),   ("5.1",  "5.2"),   ("6.1",  "6.1.2"),
        ("7.2",  "7.2"),   ("8.1",  "8.1"),   ("9.1",  "9.1.2"),
        ("9.2",  "9.2"),   ("10.1", "10.2"),
    ],

    # ── Annex SL: ISO 9001 <-> ISO 50001 ────────────────────────────────────
    ("ISO 9001:2015", "ISO 50001:2018"): [
        ("4.1",  "4.1"),   ("5.1",  "5.2"),   ("6.1",  "6.1"),
        ("8.1",  "8.1"),   ("9.1",  "9.1"),
    ],

    # ── Annex SL: ISO 22301 <-> ISO 14001 ───────────────────────────────────
    ("ISO 22301:2019", "ISO 14001:2015"): [
        ("4.1",  "4.1"),   ("6.1",  "6.1.2"),  ("9.2",  "9.2"),
        ("10.1", "10.2"),
    ],

    # ── Annex SL: ISO 14001 <-> ISO 50001 ───────────────────────────────────
    ("ISO 14001:2015", "ISO 50001:2018"): [
        ("4.1",  "4.1"),   ("5.2",  "5.2"),   ("6.2",  "6.2"),
        ("8.1",  "8.1"),   ("9.2",  "9.1"),   ("10.2", "9.1"),
    ],

    # ── PCI DSS <-> HIPAA (payment + health data overlap) ────────────────────
    ("PCI DSS v4.0", "HIPAA"): [
        ("7.1",  "164.308(a)(4)"),  ("8.1",  "164.312(d)"),
        ("9.1",  "164.310(a)(1)"),  ("10.2", "164.312(b)"),
        ("12.1", "164.308(a)(1)"),  ("12.6", "164.308(a)(5)"),
        ("12.10","164.308(a)(6)"),  ("4.1",  "164.312(e)(1)"),
    ],

    # ── ISO 45001 <-> ISO 27001 (risk + incident + compliance overlap) ──────
    ("ISO 27001:2022", "ISO 45001:2018"): [
        ("A.5.1",  "5.2"),     ("A.5.2",  "5.3"),     ("A.5.31", "6.1.3"),
        ("A.5.24", "10.2"),    ("A.5.26", "10.2"),     ("A.5.29", "8.2"),
        ("A.5.35", "9.2"),     ("A.5.36", "9.1.2"),    ("A.6.3",  "7.2"),
        ("A.6.8",  "10.2"),
    ],

    # ── Annex SL: ISO 45001 <-> ISO 9001 ────────────────────────────────────
    ("ISO 9001:2015", "ISO 45001:2018"): [
        ("4.1",  "4.1"),   ("4.2",  "4.2"),   ("5.1",  "5.1"),
        ("5.2",  "5.2"),   ("6.1",  "6.1.1"), ("7.1",  "7.1"),
        ("7.2",  "7.2"),   ("7.5",  "7.5"),   ("8.1",  "8.1.1"),
        ("9.1",  "9.1.1"), ("9.2",  "9.2"),   ("9.3",  "9.3"),
        ("10.1", "10.2"),  ("10.3", "10.3"),
    ],

    # ── Annex SL: ISO 45001 <-> ISO 14001 (EMS + OH&S twin standards) ──────
    ("ISO 14001:2015", "ISO 45001:2018"): [
        ("4.1",   "4.1"),     ("4.3",   "4.3"),    ("5.2",   "5.2"),
        ("6.1.2", "6.1.2"),   ("6.1.3", "6.1.3"),  ("6.2",   "6.2"),
        ("7.2",   "7.2"),     ("8.1",   "8.1.1"),  ("8.2",   "8.2"),
        ("9.1.2", "9.1.2"),   ("9.2",   "9.2"),    ("10.2",  "10.3"),
    ],

    # ── Annex SL: ISO 45001 <-> ISO 22301 (continuity + emergency) ──────────
    ("ISO 22301:2019", "ISO 45001:2018"): [
        ("4.1",  "4.1"),   ("5.2",  "5.2"),   ("6.1",  "6.1.1"),
        ("8.5",  "8.2"),   ("9.1",  "9.1.1"), ("9.2",  "9.2"),
        ("10.1", "10.2"),
    ],

    # ── ISO 45001 <-> ISO 31000 (risk management) ───────────────────────────
    ("ISO 31000:2018", "ISO 45001:2018"): [
        ("5.2",   "5.1"),     ("5.4.1", "4.1"),    ("5.4.2", "5.2"),
        ("6.4.1", "6.1.2"),   ("6.4.2", "6.1.2"),  ("6.5",   "6.1.4"),
        ("6.6",   "9.1.1"),   ("6.7",   "7.4"),
    ],

    # ── Annex SL: ISO 45001 <-> ISO 50001 ───────────────────────────────────
    ("ISO 50001:2018", "ISO 45001:2018"): [
        ("4.1",  "4.1"),   ("5.2",  "5.2"),   ("6.1",  "6.1.1"),
        ("8.1",  "8.1.1"), ("9.1",  "9.1.1"),
    ],
}


def seed_curated_mappings():
    """Insert curated cross-framework control mappings that are missing."""
    from database import get_db, insert_returning_id
    db = get_db()
    try:
        for (fw_name_a, fw_name_b), pairs in CURATED_MAPPINGS.items():
            fw_a = db.execute(
                "SELECT id FROM frameworks WHERE name=%s AND is_active=1", (fw_name_a,)
            ).fetchone()
            fw_b = db.execute(
                "SELECT id FROM frameworks WHERE name=%s AND is_active=1", (fw_name_b,)
            ).fetchone()
            if not fw_a or not fw_b:
                continue
            fw_a_id, fw_b_id = fw_a[0], fw_b[0]

            ctrl_a_map = {}
            for r in db.execute(
                "SELECT id, ref FROM controls WHERE framework_id=%s", (fw_a_id,)
            ).fetchall():
                ctrl_a_map[r[1]] = r[0]

            ctrl_b_map = {}
            for r in db.execute(
                "SELECT id, ref FROM controls WHERE framework_id=%s", (fw_b_id,)
            ).fetchall():
                ctrl_b_map[r[1]] = r[0]

            existing = set()
            for r in db.execute(
                "SELECT source_control_id, target_control_id FROM aria_control_mappings"
            ).fetchall():
                existing.add((min(r[0], r[1]), max(r[0], r[1])))

            created = 0
            for ref_a, ref_b in pairs:
                cid_a = ctrl_a_map.get(ref_a)
                cid_b = ctrl_b_map.get(ref_b)
                if not cid_a or not cid_b:
                    continue
                pair_key = (min(cid_a, cid_b), max(cid_a, cid_b))
                if pair_key in existing:
                    continue

                _has_extra = True
                try:
                    db.execute(
                        "SELECT auto_generated FROM aria_control_mappings LIMIT 0"
                    )
                except Exception:
                    _has_extra = False

                if _has_extra:
                    insert_returning_id(db,
                        "INSERT INTO aria_control_mappings "
                        "(source_framework_id, source_control_id, "
                        " target_framework_id, target_control_id, "
                        " mapping_type, confidence, auto_generated, match_method) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (fw_a_id, cid_a, fw_b_id, cid_b,
                         "equivalent", 0.95, 1, "curated"))
                else:
                    insert_returning_id(db,
                        "INSERT INTO aria_control_mappings "
                        "(source_framework_id, source_control_id, "
                        " target_framework_id, target_control_id, "
                        " mapping_type, confidence) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (fw_a_id, cid_a, fw_b_id, cid_b,
                         "equivalent", 0.95))
                existing.add(pair_key)
                created += 1

            if created:
                db.commit()
                log.info("Seeded %d curated mappings for %s <-> %s",
                         created, fw_name_a, fw_name_b)
    finally:
        db.close()


def seed_all_controls():
    """Populate controls for all frameworks that have no controls yet."""
    frameworks = list_frameworks(active_only=False)
    total_inserted = 0

    for fw in frameworks:
        controls_data = FRAMEWORK_CONTROLS.get(fw["name"])
        if not controls_data:
            log.warning("No control data for framework: %s", fw["name"])
            continue

        # Skip if already populated
        existing = list_controls(fw["id"])
        if existing:
            log.info("Framework '%s' already has %d controls — skipping",
                     fw["name"], len(existing))
            continue

        count = bulk_create_controls(fw["id"], controls_data)
        log.info("Seeded %d controls for '%s'", count, fw["name"])
        total_inserted += count

    log.info("Total controls seeded: %d", total_inserted)
    return total_inserted
