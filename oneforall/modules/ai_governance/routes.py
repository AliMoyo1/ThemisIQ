"""
AI governance: pages and JSON APIs for registering an AI use, reviewing requests, the inventory and the workspace.

Pages sit under /ai-governance and the JSON under /ai-governance/api. Capabilities (core/rbac.py): ai_use.submit to
describe a use, ai_use.review to review requests and edit profiles, ai_use.view to read the inventory and workspace,
ai_use.link to link records. Every change runs in one transaction: it is committed only if the whole step worked, then
audited, and its events are delivered.
"""
import json
import logging
import re

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from core.middleware import require_capability
from core.shell_context import shell_ctx
from core.sql_like import ci_like, like_pattern
from database import get_db, tenant_context
from modules.ai_governance import (assessments, assignment, controls, decisions, evaluations, explain, external_responses, guidance, handlers,  # noqa: F401  (handlers register themselves)
                                   import_rules, imports, monitoring, outstanding, oversight, overview, platform_features,
                                   precedents, quality, questions, regulation, review_packs, rules, service, workspace)
from modules.ai_governance.service import ServiceError

log = logging.getLogger("oneforall.ai_governance")

router = APIRouter(prefix="/ai-governance", tags=["ai-governance"])
templates = Jinja2Templates(directory=["modules/ai_governance/templates", "templates"])


def _error(exc: ServiceError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": exc.message, **exc.extra}, status_code=exc.status)


def _public(result: dict) -> dict:
    return {k: v for k, v in (result or {}).items() if k not in ("audit", "events")}


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ServiceError(400, "Send the request as JSON.")
    if not isinstance(body, dict):
        raise ServiceError(400, "Send the request as a JSON object.")
    return body


def _transact(request: Request, work, status_code: int = 200) -> JSONResponse:
    """Run one change: commit it whole or not at all, then audit it and deliver its events."""
    user = request.state.user
    db = get_db()
    try:
        result = work(db, user)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        return _error(exc)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    service.audit(user, result)
    service.deliver(result)
    if isinstance(result, dict) and result.get("created") is False:
        status_code = 200  # the same request again: what it made the first time
    return JSONResponse({"ok": True, **_public(result)}, status_code=status_code)


def _read(request: Request, work) -> JSONResponse:
    db = get_db()
    try:
        data = work(db, request.state.user)
    except ServiceError as exc:
        return _error(exc)
    finally:
        db.close()
    if data is None:
        return JSONResponse({"ok": False, "error": "Not found."}, status_code=404)
    return JSONResponse({"ok": True, **data} if isinstance(data, dict) else {"ok": True, "items": data})


def _private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _page(request: Request, template: str, section: str, **extra) -> HTMLResponse:
    from core.rbac import has_capability
    user = request.state.user
    ctx = shell_ctx(request, active_module="ai-governance", active_section=section)
    ctx.update(can_register=has_capability(user, "ai_use.intake_create"), can_review=has_capability(user, "ai_use.review"),
               can_decide=has_capability(user, "ai_use.decide"),
               can_manage_pack=has_capability(user, "ai_pack.manage"),
               can_receive_pack=has_capability(user, "ai_pack.receive"),
               can_assess=has_capability(user, "ai_assessment.view"),
               can_assess_manage=has_capability(user, "ai_assessment.manage"),
               can_assess_configure=has_capability(user, "ai_assessment.configure"),
               can_platform_ai_manage=has_capability(user, "ai_governance.platform.manage") and bool(user.get("is_super_admin")))
    ctx.update(extra)
    return templates.TemplateResponse(request, template, ctx)


def _pack_access(request: Request, pack_id: int, action: str = "viewed") -> dict:
    """Commit an access log even when opening the pack is refused."""
    db = get_db()
    try:
        result = review_packs.open_pack(db, request.state.user, pack_id, action)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _pack_not_found() -> JSONResponse:
    return JSONResponse({"ok": False, "error": review_packs.NOT_FOUND}, status_code=404,
                        headers={"Cache-Control": "no-store"})


# ── Pages ───────────────────────────────────────────────────────────────────

@router.get("/platform-features", response_class=HTMLResponse)
@require_capability("ai_governance.platform.manage")
async def platform_features_page(request: Request):
    platform_features._require(request.state.user)
    return _private_response(_page(request, "platform_features.html", "platform_features"))


@router.get("/", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def overview_page(request: Request):
    """The first screen: what needs action today (plans/2026-10-governance-rework/01 section 3)."""
    return _page(request, "overview.html", "overview")


@router.get("/systems", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def inventory_page(request: Request):
    return _page(request, "inventory.html", "inventory")


@router.get("/monitoring", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def monitoring_page(request: Request):
    return _page(request, "monitoring.html", "monitoring")


@router.get("/systems/{application_id}", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def workspace_page(request: Request, application_id: int):
    db = get_db()
    try:
        shown = workspace.get_system(db, request.state.user, application_id)
    finally:
        db.close()
    if shown is None:
        return HTMLResponse("Not found", status_code=404)
    return _page(request, "workspace.html", "inventory", application_id=application_id, application_name=shown["application"]["name"])


@router.get("/assessments", response_class=HTMLResponse)
@require_capability("ai_assessment.view")
async def assessments_page(request: Request):
    return _page(request, "assessments.html", "assessments")


@router.get("/assessments/new", response_class=HTMLResponse)
@require_capability("ai_assessment.manage")
async def assessment_new_page(request: Request):
    """A new assessment. Opened from a system it carries the system and starts from its AI profile."""
    system = request.query_params.get("application_id", "")
    return _page(request, "assessment.html", "assessments", assessment_id=0,
                 application_id=int(system) if system.isdigit() and len(system) <= 9 else 0)


@router.get("/assessments/{assessment_id}", response_class=HTMLResponse)
@require_capability("ai_assessment.view")
async def assessment_page(request: Request, assessment_id: int):
    db = get_db()
    try:
        shown = assessments.get_assessment(db, request.state.user, assessment_id)
    finally:
        db.close()
    if shown is None:
        return HTMLResponse("Not found", status_code=404)
    return _page(request, "assessment.html", "assessments", assessment_id=assessment_id, application_id=0)


@router.get("/decisions", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def decisions_page(request: Request):
    return _page(request, "decisions.html", "decisions")


@router.get("/regulatory", response_class=HTMLResponse)
@require_capability("ai_use.view")
async def regulatory_page(request: Request):
    return _page(request, "regulatory.html", "regulatory")


@router.get("/packs", response_class=HTMLResponse)
@require_capability("ai_pack.manage", "ai_pack.receive")
async def packs_page(request: Request):
    chosen = request.query_params.get("application_id") or ""
    response = _page(request, "packs.html", "packs", application_id=int(chosen) if chosen.isdigit() and len(chosen) <= 9 else 0)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/packs/{pack_id}", response_class=HTMLResponse)
@require_capability("ai_pack.manage", "ai_pack.receive")
async def pack_page(request: Request, pack_id: int):
    opened = _pack_access(request, pack_id)
    if "refused" in opened:
        return HTMLResponse(review_packs.NOT_FOUND, status_code=opened["http"], headers={"Cache-Control": "no-store"})
    response = _page(request, "pack_detail.html", "packs", pack=opened["pack"],
                     manifest=opened["manifest"], manager=opened["manager"])
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/register", response_class=HTMLResponse)
@require_capability("ai_use.intake_create")
async def register_page(request: Request):
    """A new request. Started from a vendor or a process that was said to use AI, it carries that source and its name."""
    source = request.query_params.get("source") or ""
    if not re.fullmatch(r"(vendor|process):\d{1,9}", source):
        source = ""
    return _page(request, "intake.html", "register", intake_id=0, source_ref=source,
                 source_name=(request.query_params.get("name") or "")[:120] if source else "")


@router.get("/requests", response_class=HTMLResponse)
@require_capability("ai_use.submit")
async def my_requests_page(request: Request):
    return _page(request, "requests.html", "requests")


@router.get("/requests/{intake_id}", response_class=HTMLResponse)
@require_capability("ai_use.submit", "ai_use.review")
async def intake_page(request: Request, intake_id: int):
    db = get_db()
    try:
        intake = service.get_intake(db, request.state.user, intake_id)
    except ServiceError as exc:
        return HTMLResponse("Not found" if exc.status == 404 else exc.message, status_code=exc.status)
    finally:
        db.close()
    from core.rbac import has_capability
    return _private(_page(request, "intake.html", "requests", intake_id=intake_id, source_ref="", source_name="",
                 can_register=((has_capability(request.state.user, "ai_use.intake_create")
                                and intake["submitted_by"] == request.state.user["id"])
                               or (intake["source_kind"] == "import"
                                   and has_capability(request.state.user, "ai_use.review")))))


@router.get("/review", response_class=HTMLResponse)
@require_capability("ai_use.review")
async def review_page(request: Request):
    return _page(request, "review.html", "review")


@router.get("/import", response_class=HTMLResponse)
@require_capability("ai_use.review")
async def import_page(request: Request):
    """Bring in the responses of an external form (plans/2026-10-governance-rework/01 section 4)."""
    response = _page(request, "import.html", "review")
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Vocabulary and pickers ──────────────────────────────────────────────────

@router.get("/api/vocabulary")
@require_capability("ai_use.submit", "ai_use.view")
async def api_vocabulary(request: Request):
    return JSONResponse({"ok": True, "capability_type": rules.CAPABILITY_TYPES, "autonomy": rules.AUTONOMY,
                         "deployment": rules.DEPLOYMENT, "data_categories": rules.DATA_CATEGORIES,
                         "affected_people": rules.AFFECTED_PEOPLE, "jurisdictions": rules.JURISDICTIONS,
                         "tiers": rules.TIER_LABELS, "required": list(rules.REQUIRED_TO_SUBMIT),
                         "labels": {f: rules.label(f) for f in rules.FIELDS}})


@router.get("/api/people")
@require_capability("ai_use.intake_create")
async def api_people(request: Request):
    """Colleagues to pick an owner from: names only, this organization only, found by typing."""
    user = request.state.user
    q = (request.query_params.get("q") or "").strip()
    db = get_db()
    try:
        sql, params = "SELECT id, full_name FROM users WHERE is_active = 1 AND deleted_at IS NULL", []
        if user.get("org_id") is not None:
            sql, params = sql + " AND org_id = %s", [user["org_id"]]
        if q:
            sql, params = sql + f" AND ({ci_like('full_name')} OR {ci_like('username')})", [*params, like_pattern(q), like_pattern(q)]
        rows = db.execute(sql + " ORDER BY full_name LIMIT 30", params).fetchall()
    finally:
        db.close()
    return JSONResponse({"ok": True, "items": [{"id": r["id"], "name": r["full_name"]} for r in rows]})


@router.get("/api/business-units")
@require_capability("ai_use.submit")
async def api_business_units(request: Request):
    """The units the signed-in person may register a use under: their own and the ones below it."""
    from modules.governance.data_service import bu_scope_ids
    user = request.state.user
    scope = bu_scope_ids(user)
    db = get_db()
    try:
        sql, params = "SELECT id, name FROM business_units WHERE is_active = 1", []
        if scope is not None:
            sql += f" AND id IN ({','.join(['%s'] * len(scope))})"
            params = list(scope)
        rows = db.execute(sql + " ORDER BY name", params).fetchall()
    finally:
        db.close()
    return JSONResponse({"ok": True, "items": [{"id": r["id"], "name": r["name"]} for r in rows],
                         "default": user.get("business_unit_id")})


@router.get("/api/applications/search")
@require_capability("ai_use.review")
async def api_application_search(request: Request):
    return _read(request, lambda db, user: service.search_applications(db, user, request.query_params.get("q")))


@router.get("/api/flags")
@require_capability("ai_use.review")
async def api_flagged(request: Request):
    """Vendors and processes said to use AI that no AI use covers yet."""
    return _read(request, lambda db, user: service.flagged_queue(db, user))


@router.put("/api/flags/{kind}/{record_id}")
@require_capability("ai_use.review", "sentinel.vendor.manage", "grid.vendor.manage", "bcm.vendor.manage", "governance.entities.manage")
async def api_set_flag(request: Request, kind: str, record_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.set_uses_ai(
        db, user, kind, record_id, body.get("answer"), body.get("note"), body.get("source")))


@router.get("/api/duplicates")
@require_capability("ai_use.intake_create")
async def api_duplicates(request: Request):
    q = request.query_params
    return _read(request, lambda db, user: service.find_duplicates(db, user, q.get("name"), q.get("provider")))


# ── Requests (the author's side) ────────────────────────────────────────────

@router.get("/api/requests")
@require_capability("ai_use.submit")
async def api_my_requests(request: Request):
    return _read(request, lambda db, user: service.list_mine(db, user, request.query_params.get("status") or None))


@router.post("/api/requests")
@require_capability("ai_use.intake_create")
async def api_create_request(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.create_draft(
        db, user, body.get("answers") or {}, body.get("idempotency_key"), body.get("source_ref")), status_code=201)


@router.get("/api/requests/{intake_id}")
@require_capability("ai_use.submit", "ai_use.review")
async def api_get_request(request: Request, intake_id: int):
    return _read(request, lambda db, user: {"intake": service.get_intake(db, user, intake_id)})


@router.put("/api/requests/{intake_id}")
@require_capability("ai_use.intake_create", "ai_use.review")
async def api_save_request(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.save_draft(db, user, intake_id, body.get("answers"), body.get("version")))


@router.post("/api/requests/{intake_id}/submit")
@require_capability("ai_use.intake_create", "ai_use.review")
async def api_submit_request(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.submit(db, user, intake_id, body.get("version")))


# ── Review (the reviewer's side) ────────────────────────────────────────────

@router.get("/api/review/queue")
@require_capability("ai_use.review")
async def api_review_queue(request: Request):
    status = request.query_params.get("status") or "submitted"
    if status not in ("submitted", "returned", "approved", "rejected", "waiting"):
        return JSONResponse({"ok": False, "error": "Unknown status."}, status_code=400)
    return _read(request, lambda db, user: service.review_queue(db, user, status))


@router.get("/api/review/worklist")
@require_capability("ai_use.review")
async def api_review_worklist(request: Request):
    return _private(_read(request, lambda db, user: service.review_worklist(
        db, user, stage=request.query_params.get("stage") or None, page=request.query_params.get("page") or 1)))


@router.post("/api/review/requests/{intake_id}/close")
@require_capability("ai_use.review")
async def api_close_request(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: service.close_request(
        db, user, intake_id, expected_version=body.get("version"), note=body.get("note"),
        channel=body.get("channel"), reference=body.get("reference"))))


@router.get("/api/review/requests/{intake_id}/duplicates")
@require_capability("ai_use.review")
async def api_review_duplicates(request: Request, intake_id: int):
    def work(db, user):
        intake = service.get_intake(db, user, intake_id)
        answers = intake["answers"]
        return service.find_duplicates(db, user, answers.get("name"), answers.get("provider_name"))
    return _read(request, work)


@router.post("/api/review/requests/{intake_id}/return")
@require_capability("ai_use.review")
async def api_review_return(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.return_to_author(db, user, intake_id, body.get("note"), body.get("version")))


@router.post("/api/review/requests/{intake_id}/reject")
@require_capability("ai_use.review")
async def api_review_reject(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.reject(db, user, intake_id, body.get("reason"), body.get("version")))


@router.post("/api/review/requests/{intake_id}/approve")
@require_capability("ai_use.review")
async def api_review_approve(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.approve(
        db, user, intake_id, body.get("version"), application_id=body.get("application_id"),
        new_application=body.get("new_application"), corrections=body.get("corrections"),
        adopted_tier=body.get("adopted_tier"), tier_reason=body.get("tier_reason"), note=body.get("note")))


@router.get("/api/review/requests/{intake_id}/assignees")
@require_capability("ai_use.review")
async def api_review_assignees(request: Request, intake_id: int):
    """The people who may be named as the reviewer of this request."""
    return _read(request, lambda db, user: {"items": assignment.reviewers_for(db, user, intake_id)})


@router.post("/api/review/requests/{intake_id}/assign")
@require_capability("ai_use.review")
async def api_review_assign(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: assignment.assign_reviewer(db, user, intake_id, body.get("assignee_id")))


# ── The inventory and the workspace ─────────────────────────────────────────

@router.get("/api/systems")
@require_capability("ai_use.view")
async def api_systems(request: Request):
    q = request.query_params
    return _read(request, lambda db, user: workspace.list_systems(
        db, user, q=q.get("q") or None, owner_id=q.get("owner"), bu_id=q.get("unit"), vendor_id=q.get("provider"),
        capability_type=q.get("use_type") or None, tier=q.get("tier") or None, state=q.get("state") or "active",
        page=q.get("page") or 1, page_size=q.get("page_size") or 25, sort=q.get("sort") or "name"))


@router.get("/api/systems/choices")
@require_capability("ai_use.view")
async def api_system_choices(request: Request):
    return _read(request, lambda db, user: workspace.filter_choices(db, user))


@router.get("/api/systems/{application_id}")
@require_capability("ai_use.view")
async def api_system(request: Request, application_id: int):
    return _read(request, lambda db, user: workspace.get_system(db, user, application_id))


@router.get("/api/systems/{application_id}/tabs/{tab}")
@require_capability("ai_use.view")
async def api_system_tab(request: Request, application_id: int, tab: str):
    return _read(request, lambda db, user: workspace.get_tab(db, user, application_id, tab))


# ── Guidance: what a use needs, its AI controls with proof, and its quality checks ──

@router.get("/api/systems/{application_id}/checklist")
@require_capability("ai_use.view")
async def api_checklist(request: Request, application_id: int):
    return _read(request, lambda db, user: guidance.get_checklist(db, user, application_id))


@router.put("/api/systems/{application_id}/checklist/{key}")
@require_capability("ai_use.review")
async def api_step_not_applicable(request: Request, application_id: int, key: str):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: guidance.set_step_not_applicable(db, user, application_id, key, body.get("reason")))


@router.delete("/api/systems/{application_id}/checklist/{key}")
@require_capability("ai_use.review")
async def api_step_reset(request: Request, application_id: int, key: str):
    return _transact(request, lambda db, user: guidance.clear_step_judgement(db, user, application_id, key))


@router.get("/api/systems/{application_id}/controls")
@require_capability("ai_use.view")
async def api_use_controls(request: Request, application_id: int):
    def work(db, user):
        items = controls.use_controls(db, user, application_id)
        return None if items is None else {"items": items, "access": controls.can_view(user)}
    return _read(request, work)


@router.get("/api/systems/{application_id}/quality")
@require_capability("ai_use.view")
async def api_quality(request: Request, application_id: int):
    return _read(request, lambda db, user: quality.evaluate(db, user, application_id))


@router.post("/api/systems/{application_id}/quality/dismiss")
@require_capability("ai_use.review")
async def api_dismiss_finding(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: quality.dismiss(
        db, user, application_id, body.get("key"), body.get("reason"), body.get("expires_at")))


@router.delete("/api/systems/{application_id}/quality/dismiss")
@require_capability("ai_use.review")
async def api_reopen_finding(request: Request, application_id: int):
    key = request.query_params.get("key") or ""
    return _transact(request, lambda db, user: quality.reopen(db, user, application_id, key))


@router.get("/api/systems/{application_id}/aiia-prefill")
@require_capability("ai_use.view")
async def api_aiia_prefill(request: Request, application_id: int):
    return _read(request, lambda db, user: guidance.aiia_prefill(db, user, application_id))


@router.get("/api/controls/{ai_control_id}/suggestions")
@require_capability("ai_use.review")
async def api_control_suggestions(request: Request, ai_control_id: int):
    return _read(request, lambda db, user: controls.suggest_mappings(db, user, ai_control_id))


@router.get("/api/canonical-controls")
@require_capability("ai_use.review")
async def api_canonical_controls(request: Request):
    return _read(request, lambda db, user: controls.search_canonical(db, user, request.query_params.get("q")))


@router.put("/api/control-mappings")
@require_capability("ai_use.review")
async def api_map_control(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: controls.map_control(
        db, user, body.get("ai_control_id"), body.get("canonical_control_id"), body.get("note")))


@router.delete("/api/control-mappings")
@require_capability("ai_use.review")
async def api_unmap_control(request: Request):
    q = request.query_params
    try:
        ai_id, canonical_id = int(q.get("ai_control_id")), int(q.get("canonical_control_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Say which mapping."}, status_code=400)
    return _transact(request, lambda db, user: controls.unmap_control(db, user, ai_id, canonical_id))


# ── The AI impact assessment (moved here from Sentinel, plans/ai-governance/06) ──

@router.get("/api/assessments")
@require_capability("ai_assessment.view")
async def api_assessments(request: Request):
    q = request.query_params
    return _read(request, lambda db, user: assessments.list_assessments(
        db, user, q=q.get("q"), status=q.get("status"), application_id=q.get("application_id"), linked=q.get("linked"),
        classification=q.get("classification"), page=q.get("page", 1), page_size=q.get("page_size", 25)))


@router.post("/api/assessments")
@require_capability("ai_assessment.manage")
async def api_assessment_create(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: assessments.create_assessment(db, user, body), 201)


@router.get("/api/assessments/link-options")
@require_capability("ai_assessment.manage")
async def api_assessment_link_options(request: Request):
    q = request.query_params
    return _read(request, lambda db, user: assessments.link_options(db, user, q.get("kind"), q.get("q")))


@router.get("/api/assessments/{assessment_id}")
@require_capability("ai_assessment.view")
async def api_assessment(request: Request, assessment_id: int):
    def work(db, user):
        shown = assessments.get_assessment(db, user, assessment_id)
        return None if shown is None else {"assessment": shown}
    return _read(request, work)


@router.put("/api/assessments/{assessment_id}")
@require_capability("ai_assessment.manage")
async def api_assessment_update(request: Request, assessment_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    version = body.pop("version", None)
    return _transact(request, lambda db, user: assessments.update_assessment(db, user, assessment_id, body, version))


@router.delete("/api/assessments/{assessment_id}")
@require_capability("ai_assessment.manage")
async def api_assessment_delete(request: Request, assessment_id: int):
    return _transact(request, lambda db, user: assessments.delete_assessment(db, user, assessment_id))


@router.get("/api/assessment-dimensions")
@require_capability("ai_assessment.view")
async def api_assessment_dimensions(request: Request):
    return _read(request, lambda db, user: assessments.list_dimensions(db, user))


@router.put("/api/assessment-dimensions")
@require_capability("ai_assessment.configure")
async def api_assessment_dimensions_save(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: assessments.save_dimensions(db, user, body.get("dimensions")))


# ── Decisions on an AI use (plans/ai-governance/07) ──

@router.get("/api/decisions")
@require_capability("ai_use.view")
async def api_decision_queue(request: Request):
    return _read(request, lambda db, user: decisions.list_queue(db, user))


@router.get("/api/decisions/{decision_id}")
@require_capability("ai_use.view")
async def api_decision(request: Request, decision_id: int):
    return _read(request, lambda db, user: {"decision": decisions.get_decision(db, user, decision_id)})


@router.get("/api/systems/{application_id}/decisions")
@require_capability("ai_use.view")
async def api_system_decisions(request: Request, application_id: int):
    return _read(request, lambda db, user: decisions.get_decisions(db, user, application_id))


@router.get("/api/systems/{application_id}/decision-brief")
@require_capability("ai_use.view")
async def api_decision_brief(request: Request, application_id: int):
    return _read(request, lambda db, user: decisions.get_brief(db, user, application_id))


@router.post("/api/systems/{application_id}/decisions")
@require_capability("ai_use.view")
async def api_decision_request(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: decisions.request_decision(
        db, user, application_id, body.get("note"), body.get("brief_hash"),
        proposed_conditions=body.get("proposed_conditions"), proposed_expires_at=body.get("proposed_expires_at"),
        proposed_review_due=body.get("proposed_review_due")), 201)


@router.get("/api/decisions/{decision_id}/assignees")
@require_capability("ai_use.view")
async def api_decision_assignees(request: Request, decision_id: int):
    """The people who may be named to decide this request."""
    return _read(request, lambda db, user: {"items": assignment.deciders_for(db, user, decision_id)})


@router.post("/api/decisions/{decision_id}/assign")
@require_capability("ai_use.view")
async def api_decision_assign(request: Request, decision_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: assignment.assign_decider(db, user, decision_id, body.get("assignee_id")))


@router.get("/api/decisions/{decision_id}/export")
@require_capability("ai_use.view")
async def api_decision_export(request: Request, decision_id: int):
    """The decision as signed, with the names of the records in it looked up again for the person asking."""
    import json as _json
    from fastapi.responses import Response
    db = get_db()
    try:
        record = decisions.get_decision(db, request.state.user, decision_id)
    except ServiceError as exc:
        return _error(exc)
    finally:
        db.close()
    body = _json.dumps({"ok": True, "format": "themisiq.ai_decision.v1", "decision": record}, indent=2, sort_keys=True, default=str)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="ai-decision-{int(decision_id)}.json"',
                             "Cache-Control": "no-store"})


@router.post("/api/decisions/{decision_id}/decide")
@require_capability("ai_use.decide")
async def api_decision_decide(request: Request, decision_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: decisions.decide(
        db, user, decision_id, body.get("outcome"), rationale=body.get("rationale"), conditions=body.get("conditions"),
        expires_at=body.get("expires_at"), override_reason=body.get("override_reason"), brief=body.get("brief_hash"),
        expected_version=body.get("version"), review_due=body.get("review_due")))


@router.post("/api/decisions/{decision_id}/withdraw")
@require_capability("ai_use.view")
async def api_decision_withdraw(request: Request, decision_id: int):
    return _transact(request, lambda db, user: decisions.withdraw(db, user, decision_id))


@router.post("/api/decisions/{decision_id}/revoke")
@require_capability("ai_use.decide")
async def api_decision_revoke(request: Request, decision_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: decisions.revoke(db, user, decision_id, body.get("reason")))


@router.put("/api/decision-conditions/{condition_id}")
@require_capability("ai_use.view")
async def api_decision_condition(request: Request, condition_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: decisions.set_condition(db, user, condition_id, body.get("met"), body.get("note")))


# ── Human oversight arrangements (G7 content-neutral foundation) ──────────

@router.get("/api/systems/{application_id}/oversight-people")
@require_capability("ai_use.review")
async def api_oversight_people(request: Request, application_id: int):
    return _private_response(_read(request, lambda db, user: oversight.eligible_people(
        db, user, application_id, request.query_params.get("q"))))


@router.get("/api/systems/{application_id}/oversight/{track}")
@require_capability("ai_use.view")
async def api_oversight(request: Request, application_id: int, track: str):
    return _private_response(_read(request, lambda db, user: oversight.get_arrangement(db, user, application_id, track)))


@router.put("/api/systems/{application_id}/oversight/{track}")
@require_capability("ai_use.review")
async def api_oversight_save(request: Request, application_id: int, track: str):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _private_response(_error(exc))
    return _private_response(_transact(request, lambda db, user: oversight.save_arrangement(
        db, user, application_id, track, body.get("arrangement"), body.get("revision"))))


@router.post("/api/systems/{application_id}/oversight/{track}/review")
@require_capability("ai_use.decide")
async def api_oversight_review(request: Request, application_id: int, track: str):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _private_response(_error(exc))
    return _private_response(_transact(request, lambda db, user: oversight.review_arrangement(
        db, user, application_id, track, body.get("revision"))))


# ── Monitoring, evaluation records, regulatory impact, explanations (plans/ai-governance/08) ──

# ── Importing the responses of an external form ─────────────────────────────

def _private(response, status_code=None):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/api/import/guide")
@require_capability("ai_use.review")
async def api_import_guide(request: Request):
    return _private(JSONResponse({"ok": True, **imports.guide()}))


@router.get("/api/import/template.csv")
@require_capability("ai_use.review")
async def api_import_template(request: Request):
    return Response(import_rules.template_csv(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="ai-use-intake-form-template.csv"', "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff"})


@router.post("/api/import/preview")
@require_capability("ai_use.review")
async def api_import_preview(request: Request, file: UploadFile = File(...), source_system: str = Form(""),
                             form_name: str = Form(""), export_date: str = Form(""), date_order: str = Form("iso"),
                             business_unit_id: str = Form(""), mapping: str = Form("")):
    data = await file.read(import_rules.MAX_FILE_BYTES + 1)
    unit = None
    if business_unit_id.strip():
        if not business_unit_id.strip().isdigit() or len(business_unit_id.strip()) > 9:
            return JSONResponse({"ok": False, "error": "Choose a business unit from the list."}, status_code=400)
        unit = int(business_unit_id.strip())
    chosen = None
    if mapping.strip():
        try:
            chosen = json.loads(mapping)
        except ValueError:
            return JSONResponse({"ok": False, "error": "The column mapping could not be read."}, status_code=400)
        if not isinstance(chosen, dict):
            return JSONResponse({"ok": False, "error": "The column mapping must be an object."}, status_code=400)
    return _private(_transact(request, lambda db, user: imports.preview(
        db, user, data=data, filename=file.filename or "", source_system=source_system, form_name=form_name,
        export_date=export_date or None, mapping=chosen, date_order=date_order, business_unit_id=unit), 201))


@router.get("/api/import/batches")
@require_capability("ai_use.review")
async def api_import_batches(request: Request):
    return _private(_read(request, lambda db, user: imports.list_batches(db, user)))


@router.get("/api/import/mappings")
@require_capability("ai_use.review")
async def api_import_mappings(request: Request):
    return _private(_read(request, lambda db, user: imports.list_saved_mappings(db, user)))


@router.post("/api/import/mappings")
@require_capability("ai_use.review")
async def api_import_mapping_save(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: imports.save_mapping(
        db, user, body.get("batch_id"), body.get("name")
    ), 201))


@router.delete("/api/import/mappings/{mapping_id}")
@require_capability("ai_use.review")
async def api_import_mapping_archive(request: Request, mapping_id: int):
    return _private(_transact(request, lambda db, user: imports.archive_mapping(
        db, user, mapping_id
    )))


@router.get("/api/import/batches/{batch_id}")
@require_capability("ai_use.review")
async def api_import_batch(request: Request, batch_id: int):
    return _private(_read(request, lambda db, user: imports.get_batch(db, user, batch_id)))


@router.post("/api/import/batches/{batch_id}/confirm")
@require_capability("ai_use.review")
async def api_import_confirm(request: Request, batch_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: imports.confirm(db, user, batch_id, body.get("version"), body.get("rows"))))


@router.post("/api/import/batches/{batch_id}/discard")
@require_capability("ai_use.review")
async def api_import_discard(request: Request, batch_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: imports.discard(db, user, batch_id, body.get("version"))))


# ── The review desk: outstanding items, precedents, questions for the requester ──

@router.get("/api/systems/{application_id}/outstanding")
@require_capability("ai_use.view")
async def api_outstanding(request: Request, application_id: int):
    return _read(request, lambda db, user: outstanding.get_outstanding(db, user, application_id))


@router.get("/api/systems/{application_id}/precedents")
@require_capability("ai_use.review")
async def api_use_precedents(request: Request, application_id: int):
    return _read(request, lambda db, user: precedents.for_use(db, user, application_id))


@router.get("/api/requests/{intake_id}/precedents")
@require_capability("ai_use.review")
async def api_request_precedents(request: Request, intake_id: int):
    return _read(request, lambda db, user: precedents.for_request(db, user, intake_id))


@router.put("/api/precedents")
@require_capability("ai_use.review")
async def api_precedent_verdict(request: Request):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: precedents.set_verdict(
        db, user, body.get("subject_kind"), body.get("subject_id"), body.get("candidate_id"), body.get("verdict"), body.get("note")))


@router.get("/api/requests/{intake_id}/questions")
@require_capability("ai_use.view")
async def api_questions(request: Request, intake_id: int):
    return _read(request, lambda db, user: questions.list_questions(db, user, intake_id))


@router.post("/api/requests/{intake_id}/questions")
@require_capability("ai_use.review")
async def api_questions_ask(request: Request, intake_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: questions.ask(db, user, intake_id, body.get("questions")), 201)


@router.post("/api/requests/{intake_id}/questions/export")
@require_capability("ai_use.review")
async def api_questions_export(request: Request, intake_id: int):
    return _private(_transact(request, lambda db, user: questions.export_text(db, user, intake_id)))


@router.post("/api/questions/{question_id}/answer")
@require_capability("ai_use.review")
async def api_question_answer(request: Request, question_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: questions.answer(
        db, user, question_id, body.get("answer"), body.get("source"), body.get("version")))


@router.post("/api/questions/{question_id}/withdraw")
@require_capability("ai_use.review")
async def api_question_withdraw(request: Request, question_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: questions.withdraw(db, user, question_id, body.get("version")))


# ── The response to a requester ─────────────────────────────────────────────

@router.get("/api/systems/{application_id}/responses")
@require_capability("ai_use.review")
async def api_responses(request: Request, application_id: int):
    raw = request.query_params.get("intake_id")
    try:
        intake_id = int(raw) if raw is not None else None
    except ValueError:
        return _error(ServiceError(400, "Choose a valid request."))
    return _private(_read(request, lambda db, user: external_responses.list_for_use(db, user, application_id, intake_id)))


@router.post("/api/systems/{application_id}/responses")
@require_capability("ai_use.review")
async def api_response_draft(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: external_responses.create_draft(db, user, application_id, body.get("intake_id")), 201))


@router.get("/api/responses/{response_id}")
@require_capability("ai_use.review")
async def api_response(request: Request, response_id: int):
    return _private(_read(request, lambda db, user: external_responses.get_response(db, user, response_id)))


@router.put("/api/responses/{response_id}")
@require_capability("ai_use.review")
async def api_response_edit(request: Request, response_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: external_responses.update_draft(db, user, response_id, body.get("fields"), body.get("version"))))


@router.post("/api/responses/{response_id}/approve")
@require_capability("ai_use.decide")
async def api_response_approve(request: Request, response_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: external_responses.approve(db, user, response_id, body.get("version"))))


@router.post("/api/responses/{response_id}/export")
@require_capability("ai_use.review")
async def api_response_export(request: Request, response_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    user = request.state.user
    db = get_db()
    try:
        result = external_responses.export(db, user, response_id, body.get("format"))
        db.commit()
    except ServiceError as exc:
        db.rollback()
        return _error(exc)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    service.audit(user, result)
    return Response(result["body"], media_type=result["media_type"], headers={
        "Content-Disposition": f'attachment; filename="{result["filename"]}"', "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff"})


@router.post("/api/responses/{response_id}/sent")
@require_capability("ai_use.review")
async def api_response_sent(request: Request, response_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: external_responses.mark_sent(
        db, user, response_id, body.get("sent_at"), body.get("channel"), body.get("reference"), body.get("version"))))


@router.post("/api/responses/{response_id}/withdraw")
@require_capability("ai_use.review")
async def api_response_withdraw(request: Request, response_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _private(_transact(request, lambda db, user: external_responses.withdraw(db, user, response_id, body.get("reason"), body.get("version"))))


@router.get("/api/overview")
@require_capability("ai_use.view")
async def api_overview(request: Request):
    return _read(request, lambda db, user: overview.get_overview(db, user))


@router.get("/api/portfolio")
@require_capability("ai_use.view")
async def api_portfolio(request: Request):
    return _read(request, lambda db, user: monitoring.get_portfolio(db, user, focus=request.query_params.get("focus") or None))


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


# Review packs: preview is read-only; issuing and revoking use the shared transaction helper.
# Opening is the exception because an access denial must also be committed.

@router.get("/api/packs/mine")
@require_capability("ai_pack.receive")
async def api_packs_mine(request: Request):
    return _read(request, review_packs.list_mine)


@router.get("/api/pack-recipients")
@require_capability("ai_pack.manage")
async def api_pack_recipients(request: Request):
    return _read(request, lambda db, user: review_packs.find_recipients(db, user, request.query_params.get("q")))


@router.get("/api/systems/{application_id}/packs")
@require_capability("ai_pack.manage")
async def api_system_packs(request: Request, application_id: int):
    return _read(request, lambda db, user: review_packs.list_for_application(db, user, application_id))


@router.post("/api/systems/{application_id}/packs/preview")
@require_capability("ai_pack.manage")
async def api_pack_preview(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _read(request, lambda db, user: review_packs.preview(db, user, application_id, body))


@router.post("/api/systems/{application_id}/packs")
@require_capability("ai_pack.manage")
async def api_pack_issue(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: review_packs.issue(db, user, application_id, body,
                                                                   body.get("expected_hash")), 201)


@router.get("/api/packs/{pack_id}")
@require_capability("ai_pack.manage", "ai_pack.receive")
async def api_pack_open(request: Request, pack_id: int):
    opened = _pack_access(request, pack_id)
    if "refused" in opened:
        return _pack_not_found()
    return JSONResponse({"ok": True, **opened}, headers={"Cache-Control": "no-store"})


@router.get("/api/packs/{pack_id}/export")
@require_capability("ai_pack.manage", "ai_pack.receive")
async def api_pack_export(request: Request, pack_id: int):
    opened = _pack_access(request, pack_id, "downloaded")
    if "refused" in opened:
        if opened["http"] == 403:
            return JSONResponse({"ok": False, "error": "Download was not allowed for this pack."}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        return _pack_not_found()
    return JSONResponse(review_packs.export_document(opened), headers={
        "Content-Disposition": f'attachment; filename="ai-review-pack-{pack_id}.json"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/api/packs/{pack_id}/history")
@require_capability("ai_pack.manage")
async def api_pack_history(request: Request, pack_id: int):
    return _read(request, lambda db, user: review_packs.access_history(db, user, pack_id))


@router.get("/api/packs/{pack_id}/changes")
@require_capability("ai_pack.manage")
async def api_pack_changes(request: Request, pack_id: int):
    return _read(request, lambda db, user: review_packs.changes_since(db, user, pack_id))


@router.post("/api/packs/{pack_id}/revoke")
@require_capability("ai_pack.manage")
async def api_pack_revoke(request: Request, pack_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: review_packs.revoke(db, user, pack_id, body.get("reason"), body.get("version")))


@router.get("/api/link-kinds")
@require_capability("ai_use.view")
async def api_link_kinds(request: Request):
    return JSONResponse({"ok": True, "items": workspace.link_kinds()})


@router.get("/api/systems/{application_id}/link-candidates")
@require_capability("ai_use.view")
async def api_link_candidates(request: Request, application_id: int):
    q = request.query_params
    return _read(request, lambda db, user: workspace.link_candidates(
        db, user, application_id, q.get("verb") or "", q.get("module") or "", q.get("type") or "", q.get("q") or None))


@router.post("/api/systems/{application_id}/profile")
@require_capability("ai_use.review")
async def api_create_profile(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.create_profile(db, user, application_id, body.get("answers")), status_code=201)


@router.put("/api/systems/{application_id}/profile")
@require_capability("ai_use.review")
async def api_update_profile(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.update_profile(db, user, application_id, body.get("answers"), body.get("version")))


@router.post("/api/systems/{application_id}/tier")
@require_capability("ai_use.review")
async def api_adopt_tier(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.adopt_tier(db, user, application_id, body.get("tier"), body.get("reason"), body.get("version")))


@router.post("/api/systems/{application_id}/reviewed")
@require_capability("ai_use.review")
async def api_mark_reviewed(request: Request, application_id: int):
    return _transact(request, lambda db, user: service.mark_reviewed(db, user, application_id))


@router.post("/api/systems/{application_id}/retire")
@require_capability("ai_use.review")
async def api_retire(request: Request, application_id: int):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _error(exc)
    return _transact(request, lambda db, user: service.retire(db, user, application_id, body.get("reason")))


@router.post("/api/systems/{application_id}/restore")
@require_capability("ai_use.review")
async def api_restore(request: Request, application_id: int):
    return _transact(request, lambda db, user: service.restore(db, user, application_id))


# The registry and operator notes live in public, even if an operator's session
# currently has a tenant context. The service performs its own capability check.
@router.get("/api/platform-features")
@require_capability("ai_governance.platform.manage")
async def api_platform_features(request: Request):
    with tenant_context(None, None, is_super_admin=True):
        return _private_response(_read(request, platform_features.list_features))


@router.put("/api/platform-features/{feature_key}")
@require_capability("ai_governance.platform.manage")
async def api_platform_feature_save(request: Request, feature_key: str):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _private_response(_error(exc))
    with tenant_context(None, None, is_super_admin=True):
        return _private_response(_transact(request, lambda db, user: platform_features.save_notes(
            db, user, feature_key, body, body.get("version"))))


@router.post("/api/platform-features/{feature_key}/review")
@require_capability("ai_governance.platform.manage")
async def api_platform_feature_review(request: Request, feature_key: str):
    try:
        body = await _body(request)
    except ServiceError as exc:
        return _private_response(_error(exc))
    with tenant_context(None, None, is_super_admin=True):
        return _private_response(_transact(request, lambda db, user: platform_features.mark_reviewed(
            db, user, feature_key, body.get("version"))))
