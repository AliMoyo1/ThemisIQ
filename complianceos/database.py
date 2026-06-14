import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = "aria.db"

FRAMEWORKS = {
    "ISO 27001": {
        "color": "#1E3A5F",
        "description": "Information Security Management System",
        "controls": [
            ("4.1","Context of the Organisation","Understanding org and its context","Policy","Clause 4"),
            ("4.2","Interested Parties","Understanding needs of interested parties","Policy","Clause 4"),
            ("4.3","Scope","Determining ISMS scope","Policy","Clause 4"),
            ("5.1","Leadership & Commitment","Management leadership and commitment","Policy","Clause 5"),
            ("5.2","Information Security Policy","Policy establishment","Policy","Clause 5"),
            ("5.3","Roles & Responsibilities","Org roles, responsibilities, authorities","Policy","Clause 5"),
            ("6.1.2","Risk Assessment","Information security risk assessment process","Procedure","Clause 6"),
            ("6.1.3","Risk Treatment","Information security risk treatment plan","Procedure","Clause 6"),
            ("6.2","Security Objectives","Information security objectives and planning","Policy","Clause 6"),
            ("7.2","Competence","Competence requirements and records","Procedure","Clause 7"),
            ("7.3","Awareness","Security awareness programme","Procedure","Clause 7"),
            ("7.5","Documented Information","Document and record control procedure","Procedure","Clause 7"),
            ("8.1","Operational Planning","Operational planning and control","Procedure","Clause 8"),
            ("9.1","Performance Evaluation","Monitoring, measurement and analysis","Procedure","Clause 9"),
            ("9.2","Internal Audit","Internal audit programme","Procedure","Clause 9"),
            ("9.3","Management Review","Management review procedure","Policy","Clause 9"),
            ("10.2","Corrective Action","Nonconformity and corrective action","Procedure","Clause 10"),
            ("A.5.1","Information Security Policies","Information security policies document","Policy","Annex A - Org"),
            ("A.5.9","Asset Inventory","Inventory of information and assets","Procedure","Annex A - Org"),
            ("A.5.10","Acceptable Use","Acceptable use of information and assets","Policy","Annex A - Org"),
            ("A.5.12","Data Classification","Classification of information policy","Policy","Annex A - Org"),
            ("A.5.15","Access Control","Access control policy","Policy","Annex A - Org"),
            ("A.5.19","Supplier Security","Information security in supplier relationships","Policy","Annex A - Org"),
            ("A.5.24","Incident Management","Information security incident management plan","Procedure","Annex A - Org"),
            ("A.5.29","Business Continuity","Information security during disruption","Policy","Annex A - Org"),
            ("A.5.34","Privacy & PII","Privacy and protection of PII policy","Policy","Annex A - Org"),
            ("A.6.1","Screening","Personnel screening procedure","Procedure","Annex A - People"),
            ("A.6.3","Security Training","Security awareness and training programme","Procedure","Annex A - People"),
            ("A.6.5","Offboarding","Responsibilities after termination procedure","Procedure","Annex A - People"),
            ("A.6.7","Remote Working","Remote working security policy","Policy","Annex A - People"),
            ("A.7.1","Physical Perimeters","Physical security perimeters policy","Policy","Annex A - Physical"),
            ("A.7.7","Clear Desk","Clear desk and clear screen policy","Policy","Annex A - Physical"),
            ("A.7.10","Storage Media","Storage media management policy","Policy","Annex A - Physical"),
            ("A.7.14","Secure Disposal","Secure disposal or re-use of equipment","Procedure","Annex A - Physical"),
            ("A.8.1","User Endpoints","User endpoint devices policy","Policy","Annex A - Tech"),
            ("A.8.2","Privileged Access","Privileged access rights management","Policy","Annex A - Tech"),
            ("A.8.5","Secure Authentication","Secure authentication policy","Policy","Annex A - Tech"),
            ("A.8.7","Malware Protection","Protection against malware policy","Policy","Annex A - Tech"),
            ("A.8.8","Vulnerability Management","Management of technical vulnerabilities","Procedure","Annex A - Tech"),
            ("A.8.12","DLP","Data leakage prevention policy","Policy","Annex A - Tech"),
            ("A.8.13","Backup","Information backup policy","Policy","Annex A - Tech"),
            ("A.8.15","Logging","Logging and monitoring policy","Policy","Annex A - Tech"),
            ("A.8.20","Network Security","Network security policy","Policy","Annex A - Tech"),
            ("A.8.24","Cryptography","Use of cryptography policy","Policy","Annex A - Tech"),
            ("A.8.25","Secure Development","Secure development lifecycle policy","Policy","Annex A - Tech"),
            ("A.8.28","Secure Coding","Secure coding standards","Policy","Annex A - Tech"),
            ("A.8.32","Change Management","Change management procedure","Procedure","Annex A - Tech"),
        ]
    },
    "ISO 42001": {
        "color": "#6A0572",
        "description": "Artificial Intelligence Management System",
        "controls": [
            ("4.1","AI Context","Understanding the organisation's AI context","Policy","Clause 4"),
            ("4.2","AI Stakeholders","Needs and expectations of interested parties","Policy","Clause 4"),
            ("4.3","AI Scope","Determining the AIMS scope","Policy","Clause 4"),
            ("5.2","AI Policy","Establishing the AI policy","Policy","Clause 5"),
            ("5.3","AI Roles","AI-specific roles and responsibilities","Policy","Clause 5"),
            ("6.1","AI Risk Actions","Actions to address AI risks and opportunities","Procedure","Clause 6"),
            ("6.1.2","AI Impact Assessment","AI system impact assessment procedure","Procedure","Clause 6"),
            ("6.2","AI Objectives","AI management objectives","Policy","Clause 6"),
            ("7.2","AI Competence","AI competency requirements","Procedure","Clause 7"),
            ("7.3","AI Awareness","AI awareness programme","Procedure","Clause 7"),
            ("8.4","AI System Development","AI system development and acquisition","Procedure","Clause 8"),
            ("8.5","AI Data Management","AI data management procedure","Procedure","Clause 8"),
            ("8.6","AI Output Management","AI system output management","Procedure","Clause 8"),
            ("8.7","Third-Party AI","Third-party AI system management","Policy","Clause 8"),
            ("9.1","AI Performance","AI performance evaluation","Procedure","Clause 9"),
            ("9.2","AI Internal Audit","AI management system internal audit","Procedure","Clause 9"),
            ("10.2","AI Nonconformity","AI nonconformity and corrective action","Procedure","Clause 10"),
            ("A.2.2","Responsible AI Roles","Roles for responsible AI use","Policy","Annex A"),
            ("A.3.2","AI Use Policy","Acceptable AI use policy","Policy","Annex A"),
            ("A.4.3","AI Risk Framework","Risks and opportunities from AI systems","Procedure","Annex A"),
            ("A.5.2","Human Oversight","Human oversight of AI systems","Policy","Annex A"),
            ("A.6.1","Data Specification","Specification of data for AI","Procedure","Annex A"),
            ("A.6.2","Data Collection","Data collection for AI systems","Procedure","Annex A"),
            ("A.6.3","AI Data Quality","Data quality management for AI","Procedure","Annex A"),
            ("A.7.2","AI System Design","AI system design procedure","Procedure","Annex A"),
            ("A.8.2","AI Output Logging","AI system output logging","Procedure","Annex A"),
            ("A.9.2","AI Incident Management","AI incident management procedure","Procedure","Annex A"),
            ("A.10.2","Bias Management","AI bias assessment and mitigation","Procedure","Annex A"),
        ]
    },
    "SOC 2 Type II": {
        "color": "#0B5345",
        "description": "Service Organization Control 2",
        "controls": [
            ("CC1.1","Control Environment","Commitment to integrity and ethical values","Policy","CC1 - Control Env"),
            ("CC1.2","Board Oversight","Board oversight of internal controls","Policy","CC1 - Control Env"),
            ("CC1.3","Management Structure","Organisational structure and authority","Policy","CC1 - Control Env"),
            ("CC1.4","Competence","Commitment to attract and develop competent individuals","Procedure","CC1 - Control Env"),
            ("CC1.5","Accountability","Accountability for internal control responsibilities","Policy","CC1 - Control Env"),
            ("CC2.1","Internal Communication","Internal communication of control objectives","Procedure","CC2 - Communication"),
            ("CC2.2","External Communication","External communication policy","Policy","CC2 - Communication"),
            ("CC3.1","Risk Objectives","Specification of suitable objectives","Policy","CC3 - Risk Assessment"),
            ("CC3.2","Risk Identification","Identifying and analysing relevant risks","Procedure","CC3 - Risk Assessment"),
            ("CC3.3","Fraud Risk","Assessing fraud risk","Procedure","CC3 - Risk Assessment"),
            ("CC4.1","Ongoing Monitoring","Ongoing and/or separate evaluations","Procedure","CC4 - Monitoring"),
            ("CC4.2","Deficiency Remediation","Evaluating and communicating deficiencies","Procedure","CC4 - Monitoring"),
            ("CC5.1","Control Selection","Selecting and developing control activities","Procedure","CC5 - Control Activities"),
            ("CC5.2","Technology Controls","Technology general control activities","Procedure","CC5 - Control Activities"),
            ("CC5.3","Policy Deployment","Deploying control activities through policies","Policy","CC5 - Control Activities"),
            ("CC6.1","Logical Access Security","Logical access security software","Policy","CC6 - Logical Access"),
            ("CC6.2","Authentication","Prior to issuing system credentials","Procedure","CC6 - Logical Access"),
            ("CC6.3","Authorization","Role-based access and authorization","Procedure","CC6 - Logical Access"),
            ("CC6.4","Access Restriction","Restricting access to authorised users","Procedure","CC6 - Logical Access"),
            ("CC6.5","Access Removal","Removal of access on employment change","Procedure","CC6 - Logical Access"),
            ("CC6.6","External Threats","Logical access security measures for external threats","Policy","CC6 - Logical Access"),
            ("CC6.7","Transmission Encryption","Encryption of data in transit","Policy","CC6 - Logical Access"),
            ("CC6.8","Malware Prevention","Controls to prevent or detect malware","Policy","CC6 - Logical Access"),
            ("CC7.1","Vulnerability Detection","Detecting vulnerabilities","Procedure","CC7 - System Ops"),
            ("CC7.2","Anomaly Monitoring","Monitoring for anomalies and security events","Procedure","CC7 - System Ops"),
            ("CC7.3","Incident Evaluation","Evaluating security incidents","Procedure","CC7 - System Ops"),
            ("CC7.4","Incident Response","Responding to security incidents","Procedure","CC7 - System Ops"),
            ("CC8.1","Change Management","Infrastructure and software changes","Procedure","CC8 - Change Mgmt"),
            ("CC9.1","Risk Mitigation","Identifying, selecting and developing risk mitigation","Procedure","CC9 - Risk Mitigation"),
            ("CC9.2","Vendor Risk","Assessing and managing risks from vendors","Policy","CC9 - Risk Mitigation"),
            ("A1.1","Availability Objectives","Availability performance objectives","Policy","Availability"),
            ("A1.2","Environmental Threats","Environmental threat protection","Policy","Availability"),
            ("A1.3","Recovery Testing","Recovery plan testing","Procedure","Availability"),
            ("C1.1","Confidential Info ID","Identifying confidential information","Procedure","Confidentiality"),
            ("C1.2","Confidential Disposal","Disposing of confidential information","Procedure","Confidentiality"),
            ("P1.1","Privacy Notice","Privacy notice and communication","Policy","Privacy"),
            ("P2.1","Consent","Choice and consent management","Procedure","Privacy"),
            ("P3.1","Data Collection","Collection of personal information","Policy","Privacy"),
            ("P4.1","Data Retention","Use, retention and disposal policy","Policy","Privacy"),
            ("P5.1","Data Access","Access to personal information","Procedure","Privacy"),
        ]
    },
    "PCI DSS": {
        "color": "#7D6608",
        "description": "Payment Card Industry Data Security Standard v4.0",
        "controls": [
            ("1.2","Network Security Controls","Network security controls procedure","Procedure","Req 1 - Network"),
            ("1.3","Network Access","Restricting inbound and outbound traffic","Policy","Req 1 - Network"),
            ("2.1","Configuration Standards","Secure configuration processes and mechanisms","Procedure","Req 2 - Config"),
            ("2.2","System Configuration","Developing secure configuration standards","Policy","Req 2 - Config"),
            ("3.1","CHD Processes","Processes and mechanisms for protecting stored CHD","Policy","Req 3 - CHD"),
            ("3.2","CHD Storage","Protection of stored account data","Policy","Req 3 - CHD"),
            ("3.4","PAN Rendering","Rendering PAN unreadable anywhere it is stored","Procedure","Req 3 - CHD"),
            ("3.5","Key Management","Cryptographic key management procedures","Procedure","Req 3 - CHD"),
            ("4.1","Transmission Security","Processes for protecting data in transmission","Policy","Req 4 - Transmission"),
            ("4.2","Encryption in Transit","Strong cryptography for data in transit","Policy","Req 4 - Transmission"),
            ("5.1","Malware Processes","Processes and mechanisms for malware protection","Procedure","Req 5 - Malware"),
            ("5.2","Malware Detection","Deploying anti-malware solutions","Policy","Req 5 - Malware"),
            ("5.4","Phishing Protection","Protecting personnel against phishing attacks","Policy","Req 5 - Malware"),
            ("6.1","Secure Development","Processes for developing and maintaining secure systems","Policy","Req 6 - Vulnerabilities"),
            ("6.3","Vulnerability Management","Identifying security vulnerabilities and protecting systems","Policy","Req 6 - Vulnerabilities"),
            ("6.4","Web App Protection","Public-facing web applications protection","Policy","Req 6 - Vulnerabilities"),
            ("6.5","Change Control","Processes and procedures for all changes","Procedure","Req 6 - Vulnerabilities"),
            ("7.1","Access Control","Processes and mechanisms for restricting access","Policy","Req 7 - Access"),
            ("7.2","System Access","Manage access to system components and cardholder data","Procedure","Req 7 - Access"),
            ("8.1","User ID Processes","Processes and mechanisms for identifying users","Policy","Req 8 - Identity"),
            ("8.2","User ID Management","User identification and related accounts management","Procedure","Req 8 - Identity"),
            ("8.3","Authentication","Authentication policies and procedures","Policy","Req 8 - Identity"),
            ("8.4","MFA","Multi-factor authentication implementation","Policy","Req 8 - Identity"),
            ("9.1","Physical Security","Processes and mechanisms for physical security controls","Policy","Req 9 - Physical"),
            ("9.2","Physical Access","Controls for physical access to CDE","Procedure","Req 9 - Physical"),
            ("9.5","POI Device Security","Protection of point-of-interaction devices","Policy","Req 9 - Physical"),
            ("10.1","Audit Log Processes","Processes and mechanisms for logging and monitoring","Policy","Req 10 - Logging"),
            ("10.2","Audit Log Generation","Implementing audit logs","Procedure","Req 10 - Logging"),
            ("10.3","Audit Log Protection","Protecting audit logs from destruction","Policy","Req 10 - Logging"),
            ("10.4","Log Review","Reviewing audit logs to identify anomalies","Procedure","Req 10 - Logging"),
            ("10.5","Log Retention","Retaining audit log history","Policy","Req 10 - Logging"),
            ("11.3","Vulnerability Scanning","External and internal vulnerability scanning","Procedure","Req 11 - Testing"),
            ("11.4","Penetration Testing","External and internal penetration testing","Policy","Req 11 - Testing"),
            ("11.5","IDS/IPS","Intrusion-detection and/or intrusion-prevention techniques","Policy","Req 11 - Testing"),
            ("12.1","Security Policy","Overall information security policy","Policy","Req 12 - Policies"),
            ("12.3","CDE Risk Assessment","Targeted risk analysis for the CDE","Procedure","Req 12 - Policies"),
            ("12.6","Security Awareness","Security awareness education programme","Procedure","Req 12 - Policies"),
            ("12.8","Third-Party Risk","Managing security of third-party service providers","Policy","Req 12 - Policies"),
            ("12.10","Incident Response","Incident response plan","Procedure","Req 12 - Policies"),
        ]
    },
    "GDPR": {
        "color": "#154360",
        "description": "General Data Protection Regulation (EU) 2016/679",
        "controls": [
            ("Art.5","Processing Principles","Principles relating to processing of personal data","Policy","Chapter 2 - Principles"),
            ("Art.6","Lawful Basis","Lawfulness of processing register","Policy","Chapter 2 - Principles"),
            ("Art.7","Consent Conditions","Conditions for consent management","Policy","Chapter 2 - Principles"),
            ("Art.9","Special Category Data","Processing of special categories of data","Policy","Chapter 2 - Principles"),
            ("Art.12","Transparency","Transparent information and communication","Policy","Chapter 3 - Rights"),
            ("Art.13","Privacy Notice","Information to be provided at point of collection","Policy","Chapter 3 - Rights"),
            ("Art.15","Right of Access","Right of access by the data subject (SAR)","Procedure","Chapter 3 - Rights"),
            ("Art.16","Right to Rectification","Right to rectification procedure","Procedure","Chapter 3 - Rights"),
            ("Art.17","Right to Erasure","Right to erasure (right to be forgotten)","Procedure","Chapter 3 - Rights"),
            ("Art.18","Right to Restriction","Right to restriction of processing","Procedure","Chapter 3 - Rights"),
            ("Art.20","Data Portability","Right to data portability procedure","Procedure","Chapter 3 - Rights"),
            ("Art.21","Right to Object","Right to object to processing","Procedure","Chapter 3 - Rights"),
            ("Art.22","Automated Decisions","Automated individual decision-making policy","Policy","Chapter 3 - Rights"),
            ("Art.24","Controller Responsibility","Responsibility of the controller","Policy","Chapter 4 - Controller"),
            ("Art.25","Privacy by Design","Data protection by design and by default","Policy","Chapter 4 - Controller"),
            ("Art.28","Processor Agreements","Processor data processing agreements","Procedure","Chapter 4 - Controller"),
            ("Art.30","ROPA","Records of processing activities (ROPA)","Procedure","Chapter 4 - Controller"),
            ("Art.32","Security of Processing","Security measures for processing","Policy","Chapter 4 - Controller"),
            ("Art.33","Breach to SA","Personal data breach notification to supervisory authority","Procedure","Chapter 4 - Controller"),
            ("Art.34","Breach to DS","Communication of breach to data subjects","Procedure","Chapter 4 - Controller"),
            ("Art.35","DPIA","Data protection impact assessment procedure","Procedure","Chapter 4 - Controller"),
            ("Art.37","DPO Appointment","Designation of data protection officer","Policy","Chapter 4 - Controller"),
            ("Art.38","DPO Position","Position of the data protection officer","Policy","Chapter 4 - Controller"),
            ("Art.39","DPO Tasks","Tasks of the data protection officer","Policy","Chapter 4 - Controller"),
            ("Art.44","Transfer Principle","General principle for international transfers","Policy","Chapter 5 - Transfers"),
            ("Art.46","Transfer Safeguards","Transfers subject to appropriate safeguards (SCCs)","Procedure","Chapter 5 - Transfers"),
        ]
    },
    "Zimbabwe CDPA": {
        "color": "#145A32",
        "description": "Cyber and Data Protection Act [Chapter 12:07]",
        "controls": [
            ("S.4","Responsible Party Obligations","Obligations of the responsible party","Policy","Part II - Principles"),
            ("S.5","Accountability","Accountability principle","Policy","Part II - Principles"),
            ("S.6","Processing Conditions","Conditions for lawful processing","Policy","Part II - Principles"),
            ("S.7","Purpose Limitation","Purpose limitation principle","Policy","Part II - Principles"),
            ("S.9","Information Quality","Data quality and accuracy","Policy","Part II - Principles"),
            ("S.10","Openness","Openness and transparency","Policy","Part II - Principles"),
            ("S.11","Security Safeguards","Security safeguards for personal information","Policy","Part II - Principles"),
            ("S.12","Breach Notification","Data breach notification procedure","Procedure","Part II - Principles"),
            ("S.14","Consent","Conditions for consent","Procedure","Part III - Consent"),
            ("S.15","Legitimate Interest","Legitimate interest assessment","Procedure","Part III - Consent"),
            ("S.16","Special Personal Information","Processing of special personal information","Policy","Part III - Consent"),
            ("S.17","Children's Data","Personal information of children","Policy","Part III - Consent"),
            ("S.18","Operator Requirements","Requirements for operators (processors)","Policy","Part IV - Operators"),
            ("S.19","Operator Contracts","Contracts with data operators","Procedure","Part IV - Operators"),
            ("S.20","Transfer Abroad","Transfer of personal information outside Zimbabwe","Policy","Part V - Transfers"),
            ("S.21","Transfer Conditions","Conditions for cross-border transfers","Procedure","Part V - Transfers"),
            ("S.22","Registration","Registration with the Authority","Procedure","Part VI - Registration"),
            ("S.23","DPO Appointment","Appointment of data protection officer","Policy","Part VI - Registration"),
            ("S.24","DPO Duties","Duties of the data protection officer","Policy","Part VI - Registration"),
            ("S.25","Data Subject Rights","Rights of data subjects framework","Policy","Part VII - Rights"),
            ("S.26","Right of Access","Right of access to personal information","Procedure","Part VII - Rights"),
            ("S.27","Right to Correction","Right to correction of personal information","Procedure","Part VII - Rights"),
            ("S.28","Right to Deletion","Right to deletion of personal information","Procedure","Part VII - Rights"),
            ("S.29","Right to Object","Right to object to processing","Procedure","Part VII - Rights"),
            ("S.30","Automated Decisions","Automated decision-making controls","Policy","Part VII - Rights"),
            ("S.31","Direct Marketing","Direct marketing opt-out procedure","Procedure","Part VII - Rights"),
            ("S.32","Complaints","Complaints to the Authority procedure","Procedure","Part VIII - Enforcement"),
        ]
    },
    "HIPAA": {
        "color": "#6E2F03",
        "description": "Health Insurance Portability and Accountability Act",
        "controls": [
            ("164.502","Uses and Disclosures","Permitted uses and disclosures of PHI","Policy","Privacy Rule"),
            ("164.506","TPO Disclosures","Treatment, payment, and operations disclosures","Policy","Privacy Rule"),
            ("164.508","Authorisations","Authorisation for uses and disclosures","Procedure","Privacy Rule"),
            ("164.514","De-identification","De-identification of protected health information","Policy","Privacy Rule"),
            ("164.520","Privacy Notice","Notice of privacy practices","Policy","Privacy Rule"),
            ("164.522","PHI Restrictions","Right to request restrictions on PHI","Procedure","Privacy Rule"),
            ("164.524","Patient Access","Access of individuals to protected health information","Procedure","Privacy Rule"),
            ("164.526","PHI Amendment","Amendment of protected health information","Procedure","Privacy Rule"),
            ("164.528","Disclosure Accounting","Accounting of disclosures of PHI","Procedure","Privacy Rule"),
            ("164.530","Admin Requirements","Administrative requirements for privacy","Policy","Privacy Rule"),
            ("164.308(a)(1)","Security Management","Risk analysis and risk management process","Procedure","Security Rule - Admin"),
            ("164.308(a)(2)","Security Responsibility","Assignment of security responsibility","Policy","Security Rule - Admin"),
            ("164.308(a)(3)","Workforce Security","Workforce security policy","Policy","Security Rule - Admin"),
            ("164.308(a)(4)","Access Management","Information access management for PHI","Policy","Security Rule - Admin"),
            ("164.308(a)(5)","Security Training","Security awareness and training programme","Procedure","Security Rule - Admin"),
            ("164.308(a)(6)","Security Incidents","Security incident procedures","Procedure","Security Rule - Admin"),
            ("164.308(a)(7)","Contingency Plan","Contingency plan for PHI systems","Procedure","Security Rule - Admin"),
            ("164.308(a)(8)","Security Evaluation","Periodic technical and non-technical evaluation","Procedure","Security Rule - Admin"),
            ("164.308(b)","Business Associates","Written contracts with business associates","Policy","Security Rule - Admin"),
            ("164.310(a)","Facility Access","Facility access controls","Policy","Security Rule - Physical"),
            ("164.310(b)","Workstation Use","Workstation use policy","Policy","Security Rule - Physical"),
            ("164.310(c)","Workstation Security","Workstation security procedure","Procedure","Security Rule - Physical"),
            ("164.310(d)","Device Controls","Device and media controls","Procedure","Security Rule - Physical"),
            ("164.312(a)","Technical Access","Technical access control policy","Policy","Security Rule - Technical"),
            ("164.312(b)","Audit Controls","Audit controls for PHI systems","Procedure","Security Rule - Technical"),
            ("164.312(c)","ePHI Integrity","Mechanism to authenticate ePHI integrity","Policy","Security Rule - Technical"),
            ("164.312(d)","Authentication","Person or entity authentication policy","Policy","Security Rule - Technical"),
            ("164.312(e)","Transmission Security","Transmission security for ePHI","Policy","Security Rule - Technical"),
            ("164.404","Individual Breach Notice","Notification to individuals of breach","Procedure","Breach Notification"),
            ("164.406","Media Breach Notice","Notification to media of breach","Procedure","Breach Notification"),
            ("164.408","HHS Notification","Notification to HHS of breach","Procedure","Breach Notification"),
            ("164.410","BA Breach Notice","Business associate breach notification","Procedure","Breach Notification"),
        ]
    }
}

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'viewer',          -- legacy, kept for back-compat
            active INTEGER DEFAULT 1,
            must_change_password INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL,
            role_key TEXT NOT NULL,
            granted_by INTEGER,
            granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, role_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_key);

        CREATE TABLE IF NOT EXISTS frameworks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            color TEXT DEFAULT '#1A2744',
            total_controls INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS controls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id INTEGER NOT NULL,
            ref TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            doc_type TEXT DEFAULT 'Policy',
            category TEXT,
            status TEXT DEFAULT 'Not Started',
            priority TEXT DEFAULT 'High',
            owner TEXT DEFAULT '',
            document_title TEXT DEFAULT '',
            version TEXT DEFAULT '1.0',
            target_date TEXT,
            review_date TEXT,
            last_updated TEXT,
            notes TEXT DEFAULT '',
            evidence_ref TEXT DEFAULT '',
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE NOT NULL,
            framework TEXT NOT NULL,
            control_ref TEXT,
            title TEXT NOT NULL,
            doc_type TEXT DEFAULT 'Policy',
            version TEXT DEFAULT '1.0',
            status TEXT DEFAULT 'Draft',
            owner TEXT DEFAULT '',
            approver TEXT DEFAULT '',
            effective_date TEXT,
            review_date TEXT,
            location TEXT DEFAULT '',
            comments TEXT DEFAULT '',
            body TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_id TEXT UNIQUE NOT NULL,
            framework TEXT NOT NULL,
            control_ref TEXT,
            description TEXT NOT NULL,
            category TEXT,
            likelihood INTEGER DEFAULT 3,
            impact INTEGER DEFAULT 3,
            owner TEXT DEFAULT '',
            mitigation TEXT DEFAULT '',
            status TEXT DEFAULT 'Open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_id TEXT UNIQUE NOT NULL,
            framework TEXT NOT NULL,
            control_ref TEXT,
            description TEXT NOT NULL,
            evidence_type TEXT,
            collected_by TEXT DEFAULT '',
            collection_date TEXT,
            storage_location TEXT DEFAULT '',
            expiry_date TEXT,
            audit_cycle TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            old_value TEXT,
            new_value TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Lightweight migrations for existing installs
    def _ensure_col(table, col, ddl):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    _ensure_col("documents", "body", "body TEXT DEFAULT ''")
    _ensure_col("users",     "active",               "active INTEGER DEFAULT 1")
    _ensure_col("users",     "must_change_password", "must_change_password INTEGER DEFAULT 0")

    # Seed admin user
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("""INSERT INTO users (username, email, full_name, password_hash, role)
                     VALUES (?, ?, ?, ?, ?)""",
                  ('admin', 'admin@aria.local', 'System Administrator',
                   hash_password('Admin@123!'), 'admin'))
        c.execute("""INSERT INTO users (username, email, full_name, password_hash, role)
                     VALUES (?, ?, ?, ?, ?)""",
                  ('auditor', 'auditor@aria.local', 'Lead Auditor',
                   hash_password('Audit@123!'), 'auditor'))
        c.execute("""INSERT INTO users (username, email, full_name, password_hash, role)
                     VALUES (?, ?, ?, ?, ?)""",
                  ('viewer', 'viewer@aria.local', 'Compliance Viewer',
                   hash_password('View@123!'), 'viewer'))

    # ── Migrate legacy single-role users into user_roles ──────────────────────
    # For any user with no rows in user_roles, map their `role` column via the
    # legacy mapping (admin→admin, auditor→external_auditor, viewer→employee).
    # This is idempotent: runs only for users missing a role assignment.
    try:
        from roles import migrate_legacy_role  # local import to avoid cycles
    except Exception:
        migrate_legacy_role = None

    if migrate_legacy_role is not None:
        unrolled = c.execute("""
            SELECT u.id, u.role FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            WHERE ur.user_id IS NULL
        """).fetchall()
        for uid, legacy_role in unrolled:
            for rk in migrate_legacy_role(legacy_role):
                c.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_key) VALUES (?, ?)",
                    (uid, rk),
                )

    # Seed frameworks and controls
    for fw_name, fw_data in FRAMEWORKS.items():
        c.execute("SELECT id FROM frameworks WHERE name=?", (fw_name,))
        row = c.fetchone()
        if not row:
            c.execute("""INSERT INTO frameworks (name, description, color, total_controls)
                         VALUES (?, ?, ?, ?)""",
                      (fw_name, fw_data["description"], fw_data["color"], len(fw_data["controls"])))
            fw_id = c.lastrowid
        else:
            fw_id = row[0]
            c.execute("SELECT COUNT(*) FROM controls WHERE framework_id=?", (fw_id,))
            if c.fetchone()[0] > 0:
                continue

        for ctrl in fw_data["controls"]:
            ref, name, desc, doc_type, category = ctrl
            c.execute("""INSERT INTO controls
                (framework_id, ref, name, description, doc_type, category,
                 status, priority, document_title, version)
                VALUES (?, ?, ?, ?, ?, ?, 'Not Started', 'High', ?, '1.0')""",
                (fw_id, ref, name, desc, doc_type, category,
                 f"{fw_name} - {name} {doc_type}"))

    conn.commit()
    conn.close()
    print("✅ Database initialised successfully")

if __name__ == "__main__":
    init_db()
