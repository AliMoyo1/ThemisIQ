/*
 * ThemisIQ design-study palette.
 * Main-module base hex values come from oneforall/templates/base_shell.html.
 * Shared utility views inherit the shell default (#1e293b). Governance
 * Settings has a purple rail icon (#6d28d9), but no dedicated theme block.
 * Dusk tints keep those hues readable against a dark surface.
 */
window.TIQ_MOCK_PALETTE = {
  platform:          {base:"#1e3a8a",dark:"#93c5fd",control:"#1e3a8a",label:"Platform blue",source:"shell theme"},
  aria:              {base:"#7d6527",dark:"#e5cb82",control:"#7d6527",label:"Governance gold",source:"shell theme"},
  grid:              {base:"#059669",dark:"#6ee7b7",control:"#047857",label:"Audit green",source:"shell theme"},
  bcm:               {base:"#3d4660",dark:"#aab6d1",control:"#3d4660",label:"Resilience slate",source:"shell theme"},
  sentinel:          {base:"#3b5bdb",dark:"#a1b6ff",control:"#3b5bdb",label:"Privacy indigo",source:"shell theme"},
  erm:               {base:"#881337",dark:"#f19ab4",control:"#881337",label:"Enterprise Risk wine",source:"shell theme"},
  orm:               {base:"#7c3a0a",dark:"#efb17c",control:"#7c3a0a",label:"Operations Risk sienna",source:"shell theme"},
  evidence:          {base:"#1e293b",dark:"#cbd5e1",control:"#1e293b",label:"Evidence neutral",source:"shell default"},
  evidence_campaigns:{base:"#1e293b",dark:"#cbd5e1",control:"#1e293b",label:"Campaigns neutral",source:"shell default"},
  readiness:         {base:"#1e293b",dark:"#cbd5e1",control:"#1e293b",label:"Readiness neutral",source:"shell default"},
  saved_views:       {base:"#1e293b",dark:"#cbd5e1",control:"#1e293b",label:"Saved Views neutral",source:"shell default"},
  governance:        {base:"#6d28d9",dark:"#d0b1ff",control:"#6d28d9",label:"Settings purple",source:"rail icon"}
};
window.TIQ_MOCK_EXTRA_VIEWS = {
  grid:{
    name:"Audit",eyebrow:"Audit management",title:["Confidence in","every finding."],
    description:"See audit work, evidence, and corrective action in one considered operating picture.",
    score:79,trend:"+7 this quarter",caption:"audit confidence",
    chartTitle:"Audit closure momentum",chartSub:"Illustrative progress through the current cycle.",
    chart:[50,51,54,56,55,59,61,64,63,68,70,72,74,77,79],
    metrics:[["Audits in progress",12,"","4 nearing completion","good"],["Findings open",27,"","6 high priority","warn"],["Actions on time",83,"%","Across audit owners","good"],["Evidence accepted",91,"%","Current cycle","good"]],
    signals:[["High finding due","Supplier assurance review","GRID"],["Corrective action","Access control test","GRID"],["Audit sign-off","Quarterly control review","GRID"]],
    domains:[["Plan",90],["Fieldwork",78],["Findings",70],["Closure",81]],
    activity:[["Finding action updated","Audit · sample update","09:52","good"],["Evidence reviewed","Audit · sample update","Yesterday",""],["Sign-off requested","Audit · sample update","2 days ago","warn"]]
  },
  sentinel:{
    name:"Privacy",eyebrow:"Data protection",title:["Privacy with","a clearer pulse."],
    description:"Bring requests, assessments, incidents, and processing obligations into focus.",
    score:84,trend:"+5 this quarter",caption:"privacy posture",
    chartTitle:"Privacy response posture",chartSub:"Illustrative completion and response trend.",
    chart:[56,58,59,57,63,65,64,68,71,70,74,77,78,81,84],
    metrics:[["Requests open",18,"","4 due this week","warn"],["DPIAs current",87,"%","Across active processing","good"],["Incidents in review",3,"","1 requires escalation","warn"],["Records mapped",146,"","Processing inventory","good"]],
    signals:[["DSR response due","Access request review","Sentinel"],["DPIA approval","New processing activity","Sentinel"],["Incident assessment","Supplier disclosure","Sentinel"]],
    domains:[["Requests",82],["DPIAs",87],["Incidents",74],["Records",90]],
    activity:[["DSR response recorded","Privacy · sample update","10:08","good"],["DPIA review requested","Privacy · sample update","Yesterday",""],["Record updated","Privacy · sample update","2 days ago",""]]
  },
  orm:{
    name:"Operations Risk",eyebrow:"Operational risk management",title:["See the signals","behind the event."],
    description:"Connect incidents, controls, and key risk indicators before small issues become systemic.",
    score:75,trend:"+3 this quarter",caption:"operations posture",
    chartTitle:"Operational control trend",chartSub:"Illustrative KRI and treatment movement.",
    chart:[49,50,48,53,56,55,59,58,63,64,66,68,70,72,75],
    metrics:[["Events open",32,"","5 elevated","warn"],["KRIs within range",78,"%","Across 6 processes","good"],["Controls effective",84,"%","Latest assessment","good"],["Loss reviews due",6,"","2 this week","warn"]],
    signals:[["KRI threshold breached","Payment exception volume","ORM"],["Event review due","Service interruption","ORM"],["Control retest","Reconciliation process","ORM"]],
    domains:[["Events",69],["KRIs",78],["Controls",84],["Loss",72]],
    activity:[["Event owner assigned","ORM · sample update","08:44","good"],["KRI moved to amber","ORM · sample update","Yesterday","warn"],["Control retested","ORM · sample update","2 days ago",""]]
  },
  evidence_campaigns:{
    name:"Evidence Campaigns",eyebrow:"Coordinated evidence requests",title:["A cleaner path","to complete evidence."],
    description:"Know who owes what, when it is due, and where every submission stands.",
    score:77,trend:"+9 this cycle",caption:"response pulse",
    chartTitle:"Campaign response trend",chartSub:"Illustrative movement from request to acceptance.",
    chart:[41,43,45,49,50,53,55,59,61,62,67,70,72,74,77],
    metrics:[["Active campaigns",8,"","Across 5 workspaces","good"],["Requests sent",126,"","Current cycle","good"],["Accepted",77,"%","Up 9 points","good"],["Overdue",11,"","Owners notified","warn"]],
    signals:[["Submission overdue","Supplier assurance pack","Campaigns"],["Review waiting","Resilience test evidence","Campaigns"],["Returned response","Policy attestation","Campaigns"]],
    domains:[["Requested",94],["Submitted",83],["In review",76],["Accepted",77]],
    activity:[["Evidence accepted","Campaigns · sample update","12:30","good"],["Reminder sent","Campaigns · sample update","Yesterday",""],["Response returned","Campaigns · sample update","2 days ago","warn"]]
  },
  readiness:{
    name:"Data Readiness",eyebrow:"Read-only data checks",title:["Find friction","before the workflow."],
    description:"Spot records that may block a workflow, with severity and module context made clear.",
    score:73,trend:"+6 this cycle",caption:"data readiness",
    chartTitle:"Finding resolution trend",chartSub:"Illustrative movement in detected issues.",
    chart:[42,44,43,47,51,50,54,57,60,61,65,67,69,71,73],
    metrics:[["Open findings",26,"","4 critical","warn"],["Acknowledged",18,"","Across 6 modules","good"],["Rules evaluated",42,"","Licensed scope only","good"],["Resolved",73,"%","Current cycle","good"]],
    signals:[["Critical missing owner","Governance record","Readiness"],["Invalid dependency","Resilience plan","Readiness"],["Unlinked evidence","Audit record","Readiness"]],
    domains:[["Governance",71],["Audit",79],["Resilience",66],["Evidence",76]],
    activity:[["Finding acknowledged","Readiness · sample update","08:12","good"],["Scan completed","Readiness · sample update","Yesterday",""],["Critical issue detected","Readiness · sample update","2 days ago","warn"]]
  },
  saved_views:{
    name:"Saved Views",eyebrow:"Personal and shared perspectives",title:["The right lens","for each decision."],
    description:"Return to the filters and columns that matter, without changing who can see the records.",
    score:82,trend:"+4 this cycle",caption:"view usefulness",
    chartTitle:"View engagement",chartSub:"Illustrative use of saved perspectives.",
    chart:[55,54,57,58,61,59,64,67,66,70,73,75,77,80,82],
    metrics:[["Saved views",18,"","Across supported lists","good"],["Shared views",7,"","Opt-in organisation scope","good"],["Defaults set",11,"","Personal preferences","good"],["Views to review",2,"","Check filters","warn"]],
    signals:[["Review shared scope","Audit finding view","Saved Views"],["Update default columns","Risk treatment view","Saved Views"],["Rename saved filter","Evidence review view","Saved Views"]],
    domains:[["Risk",79],["Audit",84],["Evidence",82],["Operations",76]],
    activity:[["View saved","Saved Views · sample update","11:22","good"],["Default updated","Saved Views · sample update","Yesterday",""],["Shared view edited","Saved Views · sample update","2 days ago",""]]
  },
  governance:{
    name:"Governance Settings",eyebrow:"Organisation structure",title:["A clear shape","for every entity."],
    description:"Keep business units, processes, applications, and ownership legible across the organisation.",
    score:88,trend:"+3 this cycle",caption:"structure health",
    chartTitle:"Ownership coverage",chartSub:"Illustrative completeness of mapped entities.",
    chart:[62,64,63,67,68,71,70,74,76,78,79,82,84,86,88],
    metrics:[["Business units",6,"","Current structure","good"],["Departments",22,"","Across units","good"],["Processes mapped",37,"","Criticality recorded","good"],["Owners missing",4,"","Assign this week","warn"]],
    signals:[["Process owner missing","Customer onboarding","Governance"],["Application mapping","Core payments service","Governance"],["Data asset review","Sensitive record set","Governance"]],
    domains:[["Units",96],["Processes",84],["Applications",88],["Data assets",82]],
    activity:[["Department updated","Governance · sample update","10:46","good"],["Process mapped","Governance · sample update","Yesterday",""],["Owner change requested","Governance · sample update","2 days ago","warn"]]
  }
};
