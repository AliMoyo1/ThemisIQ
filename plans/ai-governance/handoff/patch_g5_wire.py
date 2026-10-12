import pathlib


def patch(path, edits):
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    s = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new in edits:
        assert s.count(old) == 1, (path, old[:70], s.count(old))
        s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print(path, "patched; crlf preserved:", crlf)


PAGE = '''@router.get("/regulatory", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def regulatory_page(request: Request):
    return _page(request, "regulatory.html", "regulatory")


@router.get("/register", response_class=HTMLResponse)'''

API = '''# ── Monitoring, evaluation records, regulatory impact, explanations (plans/ai-governance/08) ──

@router.get("/api/systems/{application_id}/monitoring")
@require_capability("ai_use.view")
async def api_monitoring(request: Request, application_id: int):
    return _read(request, lambda db, user: monitoring.get_monitoring(db, user, application_id))


@router.get("/api/systems/{application_id}/evaluations")
@require_capability("ai_use.view")
async def api_evaluations(request: Request, application_id: int):
    return _read(request, lambda db, user: evaluations.list_runs(db, user, application_id))


@router.post("/api/systems/{application_id}/evaluations")
@require_capability("ai_use.review")
async def api_evaluation_record(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: evaluations.record_run(db, user, application_id, body), 201)


@router.get("/api/evaluations/compare")
@require_capability("ai_use.view")
async def api_evaluation_compare(request: Request):
    q = request.query_params
    try:
        older, newer = int(q.get("older")), int(q.get("newer"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Say which two runs."}, status_code=400)
    return _read(request, lambda db, user: evaluations.compare_runs(db, user, older, newer))


@router.post("/api/evaluations/{run_id}/review")
@require_capability("ai_use.review")
async def api_evaluation_review(request: Request, run_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: evaluations.review_run(db, user, run_id, body.get("outcome"), body.get("note"), body.get("version")))


@router.get("/api/regulatory")
@require_capability("ai_use.view")
async def api_regulatory(request: Request):
    return _read(request, lambda db, user: regulation.list_queue(db, user, request.query_params.get("status") or "candidate"))


@router.post("/api/regulatory/refresh")
@require_capability("ai_use.review")
async def api_regulatory_refresh(request: Request):
    return _transact(request, lambda db, user: regulation.refresh(db, user))


@router.post("/api/regulatory/{impact_id}/review")
@require_capability("ai_use.review")
async def api_regulatory_review(request: Request, impact_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: regulation.review(db, user, impact_id, body.get("decision"), body.get("reason"), body.get("version")))


@router.get("/api/systems/{application_id}/explain")
@require_capability("ai_use.view")
async def api_explain(request: Request, application_id: int):
    from core.middleware import check_ai_rate_limit, record_ai_call
    want_ai = request.query_params.get("ai") == "1"
    note = None
    uid = str(request.state.user["id"])
    if want_ai:
        if check_ai_rate_limit(uid):
            record_ai_call(uid)
        else:
            want_ai, note = False, "You have reached the hourly limit for AI requests, so this account is built from the rules."

    def work(db, user):
        got = explain.explain(db, user, application_id, use_ai=want_ai)
        if got is not None and note and not got["note"]:
            got["note"] = note
        return got
    return _read(request, work)


@router.get("/api/link-kinds")'''

patch("modules/ai_governance/routes.py", [
    ("from modules.ai_governance import assessments, controls, decisions, guidance, handlers, quality, rules, service, workspace  # noqa: F401  (handlers register themselves)",
     "from modules.ai_governance import (assessments, controls, decisions, evaluations, explain, guidance, handlers, monitoring,  # noqa: F401  (handlers register themselves)\n"
     "                                   quality, regulation, rules, service, workspace)"),
    ('@router.get("/register", response_class=HTMLResponse)', PAGE),
    ('@router.get("/api/link-kinds")', API),
])

patch("modules/ai_governance/templates/_ai_sidebar.html", [
    ('''  {% if can_review %}
  <a href="/ai-governance/review" class="nav-item{% if active_section == 'review' %} active{% endif %}">''',
     '''  {% if can_review %}
  <a href="/ai-governance/regulatory" class="nav-item{% if active_section == 'regulatory' %} active{% endif %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>
    Regulatory changes
  </a>
  <a href="/ai-governance/review" class="nav-item{% if active_section == 'review' %} active{% endif %}">'''),
])

patch("modules/ai_governance/workspace.py", [
    ('''    if tab == "monitoring":
        return {"tab": tab, "state": "not_measured", "sections": [_section(
            "Monitoring", [], state="not_measured", note="Nothing is measured for this use yet. Evaluations and incidents will appear here when a source reports them.")]}''',
     '''    if tab == "monitoring":
        from modules.ai_governance import monitoring
        got = monitoring.get_monitoring(db, user, application_id)
        sections = []
        for s in got["sources"]:
            items = [_item(i["title"], i["url"], subtitle=i["detail"], source="AI Governance") for i in s["items"]]
            state = s["state"] if s["state"] in ("not_measured", "no_access", "unavailable") else ("ok" if items else "empty")
            sections.append(_section(s["title"], items, state=state, note=s["note"]))
        return {"tab": tab, "state": "ok", "sections": sections}'''),
])

patch("modules/ai_governance/templates/workspace.html", [
    ('''<script src="/static/js/ai_governance_decisions.js?v=2"></script>
<script src="/static/js/ai_governance_workspace.js?v=3"></script>''',
     '''<script src="/static/js/ai_governance_decisions.js?v=2"></script>
<script src="/static/js/ai_governance_monitoring.js?v=1"></script>
<script src="/static/js/ai_governance_workspace.js?v=4"></script>'''),
])

patch("static/js/ai_governance_workspace.js", [
    ('''      if (tab === 'decisions') {''', '''      if (tab === 'monitoring') {
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        AIGov.monitoringPanel(panel, { applicationId: id });
        return;
      }
      if (tab === 'decisions') {'''),
    ('''    function renderGuidance(host) {
      AIGov.clear(host);''', '''    function renderGuidance(host) {
      AIGov.clear(host);
      host.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Explain this status',
        on: { click: function () { AIGov.explainDialog(id, system.application.name); } } })]));'''),
])

# My Work: regulatory candidates for reviewers, and the signals that reopen an approval
patch("modules/launcher/my_work_service.py", [
    ('''    # intake requests: for the reviewer, waiting; for the author, sent back''', '''    # regulatory changes proposed for a use, for the reviewer
    if has_capability(user, "ai_use.review"):
        for r in db.execute(
                "SELECT i.id, i.business_unit_id, u.title, a.name FROM ai_regulatory_impacts i "
                "JOIN regulatory_updates u ON u.id = i.update_id JOIN applications a ON a.id = i.application_id "
                f"WHERE i.status = 'candidate' AND {app_scope} ORDER BY i.id LIMIT 100", app_params).fetchall():
            add("ai_regulatory_review", r["id"], "review_regulatory_change", f"Review regulatory change: {r['title']} ({r['name']})",
                "/ai-governance/regulatory", "open", unit=r["business_unit_id"])

    # intake requests: for the reviewer, waiting; for the author, sent back'''),
    ('''            "SELECT d.id, d.application_id, d.expires_at, d.profile_fingerprint, d.tier, d.business_unit_id, a.name, a.owner_user_id, "''',
     '''            "SELECT d.id, d.application_id, d.expires_at, d.decided_at, d.profile_fingerprint, d.tier, d.business_unit_id, a.name, a.owner_user_id, "'''),
    ('''        if r["now_fingerprint"] != r["profile_fingerprint"] or tier_now != r["tier"] or expired:''',
     '''        from modules.ai_governance import decisions as _decisions
        if (r["now_fingerprint"] != r["profile_fingerprint"] or tier_now != r["tier"] or expired
                or _decisions.reopening_facts(db, r["application_id"], r["decided_at"])):'''),
])
