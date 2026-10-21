(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const icons = ["pulse","shield","file","layers"];
  const views = {
    overview: {
      name:"Overview",eyebrow:"Enterprise command view",title:["Clarity across","every control."],
      description:"A considered view of the work, exposure, and evidence that shape your organisation's position.",
      score:81,trend:"+6 this quarter",chartTitle:"Assurance momentum",chartSub:"A quieter way to read the trajectory.",
      chart:[54,57,55,60,63,61,67,65,69,73,72,76,75,78,81],
      metrics:[["Open exposures",24,"","4 resolved this month","good"],["Evidence readiness",82,"%","Up 6 points","good"],["Controls on track",91,"%","Across 7 domains","good"],["Decisions due",7,"","3 need attention","warn"]],
      signals:[["Critical risk treatment","Decision due this week","ERM"],["Policy attestation","12 responses outstanding","ARIA"],["Continuity exercise","Review sign-off pending","BCM"]],
      domains:[["Risk",78],["Assurance",86],["Continuity",72],["Evidence",84]],
      activity:[["Risk treatment approved","ERM · sample update","09:42","good"],["New evidence linked","Evidence vault · sample update","Yesterday",""],["Exercise review requested","BCM · sample update","2 days ago","warn"]]
    },
    risk: {
      name:"Risk intelligence",eyebrow:"Enterprise risk management",title:["See exposure","before it spreads."],
      description:"Give owners a sharper view of changing risk, treatments, and decisions waiting for attention.",
      score:76,trend:"+4 this quarter",chartTitle:"Risk posture",chartSub:"Illustrative improvement in treatment coverage.",
      chart:[47,49,52,51,55,57,56,61,63,62,67,70,69,73,76],
      metrics:[["Active risks",48,"","8 elevated","warn"],["Treatments on track",76,"%","Up 4 points","good"],["Overdue reviews",5,"","2 escalated","warn"],["Owners engaged",93,"%","Across 6 units","good"]],
      signals:[["Treatment owner required","Third-party exposure","ERM"],["Quarterly review overdue","Technology risk register","ERM"],["Board decision pending","Strategic risk appetite","ERM"]],
      domains:[["Strategic",72],["Operational",84],["Technology",69],["Third-party",78]],
      activity:[["Treatment updated","ERM · sample update","10:18","good"],["Review escalated","ERM · sample update","Yesterday","warn"],["Risk accepted","ERM · sample update","2 days ago",""]]
    },
    assurance: {
      name:"Assurance",eyebrow:"Governance and controls",title:["Proof where it","matters most."],
      description:"Connect policy, controls, ownership, and evidence into one legible assurance story.",
      score:86,trend:"+8 this quarter",chartTitle:"Control confidence",chartSub:"Illustrative progress across mapped frameworks.",
      chart:[57,60,59,64,63,67,69,68,73,75,76,79,81,83,86],
      metrics:[["Controls mapped",312,"","Across 9 frameworks","good"],["Testing complete",86,"%","Up 8 points","good"],["Exceptions open",12,"","3 need review","warn"],["Policy coverage",94,"%","Current cycle","good"]],
      signals:[["Control evidence gap","Access reviews","ARIA"],["Policy review due","Information security","ARIA"],["Exception approval","Data retention","ARIA"]],
      domains:[["Governance",92],["Controls",86],["Policy",94],["Testing",78]],
      activity:[["Control test completed","ARIA · sample update","11:05","good"],["Policy version approved","ARIA · sample update","Yesterday",""],["Exception logged","ARIA · sample update","2 days ago","warn"]]
    },
    continuity: {
      name:"Continuity",eyebrow:"Business continuity",title:["Readiness you","can rely on."],
      description:"Make recovery plans, exercises, and critical dependencies visible in one calm view.",
      score:72,trend:"+5 this quarter",chartTitle:"Continuity readiness",chartSub:"Illustrative exercise and plan completion.",
      chart:[43,46,45,50,54,53,56,59,58,63,65,64,68,70,72],
      metrics:[["Plans current",68,"%","12 need review","warn"],["Exercises complete",14,"","4 this quarter","good"],["Actions open",19,"","7 high priority","warn"],["Critical services",31,"","Mapped to plans","good"]],
      signals:[["Exercise sign-off","Regional recovery test","BCM"],["Plan review due","Payments operation","BCM"],["Corrective action","Alternate site readiness","BCM"]],
      domains:[["Plans",68],["Exercises",74],["Dependencies",81],["Recovery",65]],
      activity:[["Exercise reviewed","BCM · sample update","08:30","good"],["Action assigned","BCM · sample update","Yesterday",""],["Plan review flagged","BCM · sample update","3 days ago","warn"]]
    },
    evidence: {
      name:"Evidence vault",eyebrow:"Evidence and traceability",title:["Every answer,","with its proof."],
      description:"Find the right record faster, understand its status, and keep the audit trail close.",
      score:84,trend:"+7 this quarter",chartTitle:"Evidence readiness",chartSub:"Illustrative coverage across the current cycle.",
      chart:[51,53,58,56,60,64,63,66,68,72,71,75,78,81,84],
      metrics:[["Items current",274,"","Across 7 domains","good"],["Coverage",84,"%","Up 7 points","good"],["Awaiting review",16,"","5 assigned today","warn"],["Linked controls",188,"","Traceable records","good"]],
      signals:[["Review waiting","Supplier evidence pack","Evidence"],["Expiring record","Resilience test","Evidence"],["Link control","Access certification","Evidence"]],
      domains:[["Risk",80],["Policy",90],["Continuity",75],["Third-party",84]],
      activity:[["Evidence accepted","Vault · sample update","12:12","good"],["Record replaced","Vault · sample update","Yesterday",""],["Review requested","Vault · sample update","2 days ago","warn"]]
    }
  };
  Object.assign(views, {
    platform:{...views.overview,name:"Command Centre",caption:"assurance pulse"},
    aria:{...views.assurance,name:"Governance",eyebrow:"Policy and compliance",caption:"control confidence",
      metrics:[["Policies current",94,"%","Current cycle","good"],["Controls mapped",312,"","Across 9 frameworks","good"],["Attestations due",12,"","3 need review","warn"],["Testing complete",86,"%","Up 8 points","good"]],
      signals:[["Policy attestation","12 responses outstanding","ARIA"],["Control evidence gap","Access reviews","ARIA"],["Exception approval","Data retention","ARIA"]]},
    bcm:{...views.continuity,name:"Resilience",caption:"readiness pulse"},
    erm:{...views.risk,name:"Enterprise Risk",caption:"risk posture"},
    evidence:{...views.evidence,name:"Evidence Vault",caption:"evidence health"}
  }, window.TIQ_MOCK_EXTRA_VIEWS);
  for(const alias of ["overview","risk","assurance","continuity"])delete views[alias];
  const state = {scope:"platform",range:30,index:null,motion:true};
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const motionAllowed = () => state.motion && !reduced.matches;
  const setText = (id,value) => { $(id).textContent=String(value); };
  function applyPalette(scope) {
    const palette=window.TIQ_MOCK_PALETTE[scope];
    const dark=document.documentElement.dataset.theme==="dusk";
    const color=dark?palette.dark:palette.base;
    const channels=color.match(/[a-f0-9]{2}/gi).map(part=>parseInt(part,16)).join(",");
    const style=document.documentElement.style;
    style.setProperty("--accent",color);
    style.setProperty("--accent-text",dark?color:palette.control);
    style.setProperty("--accent-control",dark?color:palette.control);
    style.setProperty("--accent-rgb",channels);
    style.setProperty("--accent-soft","rgba("+channels+","+(dark?".17":".10")+")");
    style.setProperty("--glow","rgba("+channels+","+(dark?".20":".14")+")");
    style.setProperty("--ambient-a","rgba("+channels+","+(dark?".18":".14")+")");
    style.setProperty("--chart",color);
    style.setProperty("--chart-fill","rgba("+channels+","+(dark?".16":".13")+")");
    document.documentElement.dataset.module=scope;
    setText("paletteLabel",palette.label);
    setText("paletteHex",palette.base.toUpperCase()+" | "+palette.source);
  }
  let toastTimer;
  function toast(message) {
    const el=$("toast"); el.textContent=message; el.classList.add("show");
    clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove("show"),2800);
  }
  function icon(name) {
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    const use=document.createElementNS("http://www.w3.org/2000/svg","use");
    svg.setAttribute("class","icon"); svg.setAttribute("aria-hidden","true");
    use.setAttribute("href","#"+name); svg.append(use); return svg;
  }
  function openDetail(kicker,title,description,facts) {
    setText("dialogKicker",kicker); setText("dialogTitle",title);
    setText("dialogDescription",description);
    const wrap=$("dialogFacts"); wrap.replaceChildren();
    facts.forEach(([label,value])=>{
      const row=document.createElement("div");row.className="dialog-fact";
      const heading=document.createElement("strong");heading.textContent=label;
      row.append(heading,document.createTextNode(value));wrap.append(row);
    });
    $("detailDialog").showModal();
  }
  const rangeShift = () => state.range===7?-2:state.range===90?3:0;
  function metricNumber(base,unit,index) {
    if(unit==="%")return Math.min(99,Math.max(1,base+rangeShift()));
    return Math.max(0,base+rangeShift()*(index===0?-1:1));
  }
  function animateNumber(el,target,unit) {
    if(!motionAllowed()){el.textContent=target+unit;return;}
    const startAt=performance.now(),duration=500;
    function frame(now) {
      const p=Math.min(1,(now-startAt)/duration),ease=1-Math.pow(1-p,3);
      el.textContent=Math.round(target*ease)+unit;
      if(p<1)requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  function renderMetrics(view) {
    const wrap=$("metrics");wrap.replaceChildren();
    view.metrics.forEach(([label,value,unit,foot,tone],index)=>{
      const card=document.createElement("article");card.className="metric glass";
      const top=document.createElement("div");top.className="metric-top";
      const title=document.createElement("span");title.textContent=label;top.append(title,icon(icons[index]));
      const number=document.createElement("div");number.className="metric-value";number.textContent="0"+unit;
      const footer=document.createElement("div");footer.className="metric-foot";
      const detail=document.createElement("span");detail.textContent=foot;
      const delta=document.createElement("span");delta.className="delta"+(tone==="warn"?" warn":"");
      delta.textContent=tone==="warn"?"Review needed":"On course";
      footer.append(detail,delta);card.append(top,number,footer);wrap.append(card);
      animateNumber(number,metricNumber(value,unit,index),unit);
    });
  }
  function valuesForRange(series) {
    return series.map((value,index)=>Math.max(25,Math.min(98,value+rangeShift()+Math.sin(index*1.6+state.range)*1.4)));
  }
  function plotPoint(value,index,count) {
    return {x:10+index*580/(count-1),y:176-(value-25)*1.75};
  }
  function showPoint(index) {
    const values=valuesForRange(views[state.scope].chart);
    const i=Math.max(0,Math.min(values.length-1,index)),point=plotPoint(values[i],i,values.length);
    state.index=i;
    $("chartHoverline").setAttribute("x1",point.x);
    $("chartHoverline").setAttribute("x2",point.x);
    $("chartHoverline").setAttribute("visibility","visible");
    $("chartMarker").setAttribute("cx",point.x);
    $("chartMarker").setAttribute("cy",point.y);
    $("chartMarker").setAttribute("visibility","visible");
    const tip=$("chartTooltip");tip.textContent="Point "+(i+1)+" · "+Math.round(values[i])+" / 100";
    tip.style.left=(point.x/600*100)+"%";tip.style.top=(point.y/200*100)+"%";tip.classList.add("show");
    setText("chartCurrent","Point "+(i+1)+": "+Math.round(values[i])+" / 100");
  }
  function hidePoint() {
    state.index=null;$("chartHoverline").setAttribute("visibility","hidden");
    $("chartMarker").setAttribute("visibility","hidden");$("chartTooltip").classList.remove("show");
    const values=valuesForRange(views[state.scope].chart);
    setText("chartCurrent","Latest "+Math.round(values.at(-1))+" / 100");
  }
  function renderChart(view) {
    const series=valuesForRange(view.chart);
    const points=series.map((value,index)=>plotPoint(value,index,series.length));
    const line=points.map((p,index)=>(index?"L":"M")+p.x.toFixed(1)+" "+p.y.toFixed(1)).join(" ");
    $("chartLine").setAttribute("d",line);
    $("chartArea").setAttribute("d",line+" L 590 192 L 10 192 Z");
    $("trendChart").setAttribute("aria-label",view.chartTitle+". Latest illustrative value "+Math.round(series.at(-1))+" out of 100. Focus and use arrow keys to inspect points.");
    setText("chartTitle",view.chartTitle);setText("chartSub",view.chartSub);
    setText("chartSummary",state.range+"-day view");
    setText("chartSummarySub","Sample trend · hover or use arrow keys");
    hidePoint();
    const labels=[state.range===7?"Past week":state.range===90?"Past quarter":"Past month","Midpoint","Today"];
    $("chartAxis").replaceChildren(...labels.map(label=>{const span=document.createElement("span");span.textContent=label;return span;}));
  }
  function renderSignals(view) {
    const wrap=$("signalList");wrap.replaceChildren();
    view.signals.forEach(([title,subtitle,module],index)=>{
      const button=document.createElement("button");button.type="button";button.className="signal-button";
      const iconWrap=document.createElement("span");iconWrap.className="signal-icon";
      iconWrap.append(icon(index===0?"pulse":index===1?"file":"layers"));
      const content=document.createElement("span");content.className="signal-content";
      const strong=document.createElement("strong");strong.textContent=title;
      const small=document.createElement("small");small.textContent=subtitle+" · "+module;
      content.append(strong,small);const arrow=icon("arrow");arrow.classList.add("signal-arrow");
      button.append(iconWrap,content,arrow);
      button.addEventListener("click",()=>openDetail(module+" priority",title,
        "A focused detail surface could show owner, due date, context, evidence, and the next decision. This preview uses sample data.",
        [["Context",subtitle],["Workspace",module],["Suggested next step","Review the source record and assign the next action."]]));
      wrap.append(button);
    });
  }
  function renderDomains(view) {
    const wrap=$("domainList");wrap.replaceChildren();
    view.domains.forEach(([name,value])=>{
      const row=document.createElement("div");row.className="domain-row";
      const label=document.createElement("span");label.textContent=name;
      const track=document.createElement("div");track.className="domain-track";
      const fill=document.createElement("div");fill.className="domain-fill";fill.style.width=value+"%";track.append(fill);
      const score=document.createElement("strong");score.textContent=value+"%";
      row.append(label,track,score);wrap.append(row);
    });
  }
  function renderActivity(view) {
    const wrap=$("activityList");wrap.replaceChildren();
    view.activity.forEach(([title,subtitle,time,tone])=>{
      const row=document.createElement("div");row.className="activity-row";
      const dot=document.createElement("span");dot.className="activity-dot "+tone;
      const copy=document.createElement("div");const heading=document.createElement("strong");
      heading.textContent=title;const small=document.createElement("small");small.textContent=subtitle;
      copy.append(heading,small);const timestamp=document.createElement("span");
      timestamp.className="activity-time";timestamp.textContent=time;
      row.append(dot,copy,timestamp);wrap.append(row);
    });
  }
  function selectScope(scope) {
    const view=views[scope];if(!view)return;state.scope=scope;applyPalette(scope);
    document.querySelectorAll(".nav-btn").forEach(button=>
      button.dataset.scope===scope?button.setAttribute("aria-current","page"):button.removeAttribute("aria-current"));
    setText("crumbCurrent",view.name);setText("modulePillText",view.name);setText("heroEyebrow",view.eyebrow);
    const hero=$("heroTitle");hero.replaceChildren(
      document.createTextNode(view.title[0]),document.createElement("br"),
      document.createTextNode(view.title[1]));
    setText("heroDesc",view.description);
    const score=view.score+rangeShift();
    setText("haloScore",score);setText("haloTrend",view.trend);
    setText("haloCaption",view.caption||"assurance pulse");
    document.querySelector(".halo").style.background=
      "conic-gradient(from 205deg,var(--accent) 0 "+score+"%,rgba(var(--surface-rgb),.35) "+score+"% 100%)";
    document.querySelector(".hero-visual").setAttribute("aria-label",
      "Illustrative "+view.name.toLowerCase()+" score, "+score+" out of 100");
    setText("metricKicker",view.name+" · sample values");
    renderMetrics(view);renderChart(view);renderSignals(view);renderDomains(view);renderActivity(view);
  }
  document.querySelectorAll(".nav-btn").forEach(button=>
    button.addEventListener("click",()=>selectScope(button.dataset.scope)));
  document.querySelectorAll(".period-button").forEach(button=>
    button.addEventListener("click",()=>{
      state.range=Number(button.dataset.range);
      document.querySelectorAll(".period-button").forEach(other=>
        other.setAttribute("aria-pressed",String(other===button)));
      selectScope(state.scope);
    }));
  document.querySelectorAll(".theme-button").forEach(button=>
    button.addEventListener("click",()=>{
      document.documentElement.dataset.theme=button.dataset.theme;applyPalette(state.scope);
      document.querySelectorAll(".theme-button").forEach(other=>
        other.setAttribute("aria-pressed",String(other===button)));
    }));
  $("glassRange").addEventListener("input",event=>{
    const value=Number(event.target.value);
    document.documentElement.style.setProperty("--glass-alpha",(value/100).toFixed(2));
    document.documentElement.style.setProperty("--blur",(12+(value-40)*.45).toFixed(1)+"px");
    setText("glassValue",value);
  });
  $("motionButton").addEventListener("click",()=>{
    state.motion=!state.motion;
    document.documentElement.classList.toggle("reduce-motion",!state.motion);
    $("motionButton").setAttribute("aria-pressed",String(state.motion));
    setText("motionLabel",state.motion?"Motion on":"Motion off");
  });
  $("trendChart").addEventListener("pointermove",event=>{
    const bounds=event.currentTarget.getBoundingClientRect();
    showPoint(Math.round(((event.clientX-bounds.left)/bounds.width)*14));
  });
  $("trendChart").addEventListener("pointerleave",hidePoint);
  $("trendChart").addEventListener("keydown",event=>{
    if(event.key==="ArrowRight"||event.key==="ArrowLeft"){
      event.preventDefault();
      showPoint((state.index??(event.key==="ArrowRight"?-1:15))+
        (event.key==="ArrowRight"?1:-1));
    }
    if(event.key==="Escape")hidePoint();
  });
  $("briefButton").addEventListener("click",()=>{
    const view=views[state.scope];
    openDetail("Board brief · sample",view.name+" at a glance",
      "A board-facing layer could turn dashboard signals into a concise narrative, with the underlying evidence one step away.",
      [[view.caption||"Module pulse",(view.score+rangeShift())+" / 100"],
       ["Focus",view.signals[0][0]],["Presentation","Narrative first, drill-down on demand"]]);
  });
  $("prioritiesButton").addEventListener("click",()=>
    $("signalsTitle").scrollIntoView({behavior:motionAllowed()?"smooth":"auto",block:"center"}));
  $("allPrioritiesButton").addEventListener("click",()=>
    openDetail("Priorities · sample","Decisions in focus",
      "A full priority view could combine urgency, owner, due date, and provenance across workspaces.",
      views[state.scope].signals.map(item=>[item[2],item[0]+" — "+item[1]])));
  $("chartInfoButton").addEventListener("click",()=>
    openDetail("Trend design","A legible signal over time",
      "The plotted values are illustrative. In the product, this view should state its measure, time window, last update, and source.",
      [["Interaction","Hover or focus the chart and use arrow keys"],
       ["Motion","Turns off with Motion control or reduced-motion preference"]]));
  $("signalInfoButton").addEventListener("click",()=>
    openDetail("Priority design","Calm, actionable cards",
      "These rows show why an item matters and open a focused detail view instead of forcing users to scan a dense table.",
      [["Grouping","Urgent decisions first"],["Source","Each item links to its workspace in the full product"]]));
  $("activityInfoButton").addEventListener("click",()=>
    openDetail("Activity design","Only meaningful movement",
      "A production feed would include verified timestamps, ownership, and an audit link for each event.",
      [["Preview state","Illustrative entries"],["Design intent","Traceability without overwhelming the page"]]));
  $("detailClose").addEventListener("click",()=>$("detailDialog").close());
  $("detailDone").addEventListener("click",()=>$("detailDialog").close());
  $("notificationButton").addEventListener("click",()=>{
    const open=$("notificationPopover").classList.toggle("open");
    $("notificationButton").setAttribute("aria-expanded",String(open));
  });
  document.addEventListener("pointerdown",event=>{
    if(!event.target.closest(".popover-anchor")){
      $("notificationPopover").classList.remove("open");
      $("notificationButton").setAttribute("aria-expanded","false");
    }
  });
  $("refreshButton").addEventListener("click",()=>{
    selectScope(state.scope);toast("Sample dashboard refreshed");
  });
  const searchItems=[
    ["Command Centre","platform"],["Governance","aria"],["Audit","grid"],
    ["Resilience","bcm"],["Privacy","sentinel"],["Enterprise Risk","erm"],
    ["Operations Risk","orm"],["Evidence Vault","evidence"],
    ["Evidence Campaigns","evidence_campaigns"],["Data Readiness","readiness"],
    ["Saved Views","saved_views"],["Governance Settings","governance"]
  ];
  function renderSearch(query=""){
    const wrap=$("searchResults");wrap.replaceChildren();
    const matches=searchItems.filter(([label])=>label.toLowerCase().includes(query.toLowerCase()));
    if(!matches.length){const empty=document.createElement("p");empty.textContent="No preview areas match.";wrap.append(empty);return;}
    matches.forEach(([label,scope])=>{
      const button=document.createElement("button");button.className="search-result";button.type="button";
      button.append(document.createTextNode(label),icon("arrow"));
      button.addEventListener("click",()=>{selectScope(scope);$("searchDialog").close();});
      wrap.append(button);
    });
  }
  function openSearch(){renderSearch();$("searchInput").value="";$("searchDialog").showModal();$("searchInput").focus();}
  $("searchButton").addEventListener("click",openSearch);
  $("searchClose").addEventListener("click",()=>$("searchDialog").close());
  $("searchInput").addEventListener("input",event=>renderSearch(event.target.value));
  document.addEventListener("keydown",event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){
      event.preventDefault();if(!$("searchDialog").open)openSearch();
    }
    if(event.key==="Escape"&&$("notificationPopover").classList.contains("open")){
      $("notificationPopover").classList.remove("open");
      $("notificationButton").setAttribute("aria-expanded","false");
      $("notificationButton").focus();
    }
  });
  document.querySelector(".shell").addEventListener("pointermove",event=>{
    if(!motionAllowed())return;
    const card=event.target.closest(".glass");if(!card)return;
    const rect=card.getBoundingClientRect();
    card.style.setProperty("--mx",((event.clientX-rect.left)/rect.width*100).toFixed(1)+"%");
    card.style.setProperty("--my",((event.clientY-rect.top)/rect.height*100).toFixed(1)+"%");
  });
  selectScope("platform");
})();
