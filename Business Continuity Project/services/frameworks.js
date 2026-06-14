// Built-in baseline framework catalogs. These are used to seed a tenant's
// compliance register on first visit so they have a working starting point.

const ISO_22301 = [
  { clause: '4.1', title: 'Understanding the organization and its context',
    description: 'Determine internal and external issues relevant to the BCMS and its objectives.' },
  { clause: '4.2', title: 'Needs and expectations of interested parties',
    description: 'Identify stakeholders, legal / regulatory obligations, and their requirements.' },
  { clause: '4.3', title: 'Determining scope of the BCMS',
    description: 'Define and document the scope of the business continuity management system.' },
  { clause: '4.4', title: 'Business continuity management system',
    description: 'Establish, implement, maintain and continually improve the BCMS.' },
  { clause: '5.1', title: 'Leadership and commitment',
    description: 'Top management demonstrates leadership and commitment to the BCMS.' },
  { clause: '5.2', title: 'Policy',
    description: 'Documented business continuity policy communicated and available.' },
  { clause: '5.3', title: 'Roles, responsibilities and authorities',
    description: 'Assign responsibility and authority for roles relevant to the BCMS.' },
  { clause: '6.1', title: 'Actions to address risks and opportunities',
    description: 'Determine risks and opportunities and plan actions to address them.' },
  { clause: '6.2', title: 'Business continuity objectives',
    description: 'Establish measurable BC objectives at relevant functions and levels.' },
  { clause: '6.3', title: 'Planning changes to the BCMS',
    description: 'Changes to the BCMS are carried out in a planned manner.' },
  { clause: '7.1', title: 'Resources',
    description: 'Provide the resources needed for the establishment and operation of the BCMS.' },
  { clause: '7.2', title: 'Competence',
    description: 'Determine necessary competence and ensure people are competent.' },
  { clause: '7.3', title: 'Awareness',
    description: 'Ensure people are aware of the BC policy, their contribution, and implications of non-conformance.' },
  { clause: '7.4', title: 'Communication',
    description: 'Determine internal and external communications relevant to the BCMS.' },
  { clause: '7.5', title: 'Documented information',
    description: 'Create, update and control documented information required by the BCMS.' },
  { clause: '8.1', title: 'Operational planning and control',
    description: 'Plan, implement and control processes needed to meet requirements.' },
  { clause: '8.2', title: 'Business impact analysis and risk assessment',
    description: 'Perform a BIA and risk assessment; prioritize activities based on impact.' },
  { clause: '8.3', title: 'Business continuity strategies and solutions',
    description: 'Determine and select strategies and solutions based on BIA and risk outputs.' },
  { clause: '8.4', title: 'Business continuity plans and procedures',
    description: 'Document response structure, warning & communication, BC plans, and recovery.' },
  { clause: '8.5', title: 'Exercise programme',
    description: 'Exercise and test continuity plans to validate effectiveness.' },
  { clause: '8.6', title: 'Evaluation of business continuity documentation and capabilities',
    description: 'Periodically evaluate the suitability, adequacy, and effectiveness of BCMS.' },
  { clause: '9.1', title: 'Monitoring, measurement, analysis and evaluation',
    description: 'Determine what, how, and when to monitor and measure BCMS performance.' },
  { clause: '9.2', title: 'Internal audit',
    description: 'Conduct planned internal audits of the BCMS.' },
  { clause: '9.3', title: 'Management review',
    description: 'Top management reviews the BCMS at planned intervals.' },
  { clause: '10.1', title: 'Nonconformity and corrective action',
    description: 'React to nonconformities and take action to eliminate causes.' },
  { clause: '10.2', title: 'Continual improvement',
    description: 'Continually improve the suitability, adequacy, and effectiveness of the BCMS.' }
];

const FRAMEWORKS = {
  'ISO 22301': ISO_22301
};

module.exports = { FRAMEWORKS };
