"""
PLAN-36 P05: evidence collection campaigns -- routes.

Capability gates: evidence.campaign.manage for creating/closing campaigns,
creating requests, and cancelling them; evidence.request.review for
deciding (accept/return) a submission. Submitting evidence and starting a
review require no role capability at all -- they are object-level checks
(are you this specific request's assignee/reviewer), enforced inside
data_service.py itself, matching aria.policy's own pattern for the same
reason: fulfilling your own assignment is not a management action.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from core.middleware import require_auth, require_capability, log_audit
from core.shell_context import shell_ctx
from modules.evidence_campaigns import data_service as svc

router = APIRouter(prefix="/evidence-campaigns", tags=["evidence-campaigns"])
templates = Jinja2Templates(directory=["modules/evidence_campaigns/templates", "templates"])


def _error_response(exc: svc.CampaignError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": exc.code, "message": exc.message}}, status_code=exc.http_status,
    )


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("", response_class=HTMLResponse)
@require_auth
async def campaigns_page(request: Request):
    ctx = shell_ctx(request, active_module="evidence_campaigns", active_section="evidence_campaigns")
    ctx["user"] = request.state.user
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/api/campaigns")
@require_auth
async def api_list_campaigns(request: Request):
    user = request.state.user
    status = request.query_params.get("status") or None
    db = get_db()
    try:
        campaigns = svc.list_campaigns(db, user, status=status)
        for c in campaigns:
            c["coverage"] = svc.campaign_coverage(db, user, c["id"])
    finally:
        db.close()
    return JSONResponse({"ok": True, "campaigns": campaigns})


@router.post("/api/campaigns")
@require_capability("evidence.campaign.manage")
async def api_create_campaign(request: Request):
    user = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        try:
            campaign = svc.create_campaign(
                db, user, name=payload.get("name", ""), description=payload.get("description", ""),
                due_date=payload.get("due_date", ""), start_date=payload.get("start_date"),
                business_unit_id=payload.get("business_unit_id"), recurrence=payload.get("recurrence", "none"),
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
        log_audit(user, "evidence_campaigns", f"Created campaign \"{campaign['name']}\"")
    finally:
        db.close()
    return JSONResponse({"ok": True, "campaign": campaign}, status_code=201)


@router.get("/api/campaigns/{campaign_id}")
@require_auth
async def api_get_campaign(request: Request, campaign_id: int):
    user = request.state.user
    db = get_db()
    try:
        campaign = svc.get_campaign(db, user, campaign_id)
        if campaign is None:
            return JSONResponse({"ok": False, "error": {"code": "NOT_FOUND", "message": "Campaign not found."}}, status_code=404)
        campaign["coverage"] = svc.campaign_coverage(db, user, campaign_id)
        requests = svc.list_requests(db, user, campaign_id=campaign_id)
    finally:
        db.close()
    return JSONResponse({"ok": True, "campaign": campaign, "requests": requests})


@router.post("/api/campaigns/{campaign_id}/close")
@require_capability("evidence.campaign.manage")
async def api_close_campaign(request: Request, campaign_id: int):
    user = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        try:
            campaign = svc.close_campaign(
                db, user, campaign_id, force=bool(payload.get("force")), reason=payload.get("reason"),
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
        log_audit(user, "evidence_campaigns", f"Closed campaign \"{campaign['name']}\"")
    finally:
        db.close()
    return JSONResponse({"ok": True, "campaign": campaign})


@router.get("/api/requests")
@require_auth
async def api_list_requests(request: Request):
    user = request.state.user
    q = request.query_params
    assignee_id = user["id"] if q.get("assignee") == "me" else None
    reviewer_id = user["id"] if q.get("reviewer") == "me" else None
    campaign_id = int(q["campaign_id"]) if q.get("campaign_id") else None
    db = get_db()
    try:
        requests_ = svc.list_requests(
            db, user, campaign_id=campaign_id, assignee_id=assignee_id,
            reviewer_id=reviewer_id, status=q.get("status") or None,
        )
    finally:
        db.close()
    return JSONResponse({"ok": True, "requests": requests_})


@router.post("/api/requests")
@require_capability("evidence.campaign.manage")
async def api_create_request(request: Request):
    user = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        try:
            req = svc.create_request(
                db, user, campaign_id=payload.get("campaign_id"), module=payload.get("module", ""),
                entity_type=payload.get("entity_type", ""), entity_id=payload.get("entity_id", ""),
                title=payload.get("title", ""), instructions=payload.get("instructions", ""),
                assignee_id=payload.get("assignee_id"), reviewer_id=payload.get("reviewer_id"),
                due_date=payload.get("due_date", ""), business_unit_id=payload.get("business_unit_id"),
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
        log_audit(user, "evidence_campaigns", f"Created evidence request \"{req['title']}\"")
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req}, status_code=201)


@router.get("/api/requests/{request_id}")
@require_auth
async def api_get_request(request: Request, request_id: int):
    user = request.state.user
    db = get_db()
    try:
        req = svc.get_request(db, user, request_id)
        if req is None:
            return JSONResponse({"ok": False, "error": {"code": "NOT_FOUND", "message": "Request not found."}}, status_code=404)
        events = svc.list_request_events(db, user, request_id)
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req, "events": events})


@router.post("/api/requests/{request_id}/submit")
@require_auth
async def api_submit_request(request: Request, request_id: int):
    user = request.state.user
    payload = await _json_body(request)
    if payload.get("evidence_id") is None or payload.get("expected_lock_version") is None:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT",
                             "message": "evidence_id and expected_lock_version are required."}}, status_code=422)
    db = get_db()
    try:
        try:
            req = svc.submit_request(
                db, user, request_id, evidence_id=payload["evidence_id"],
                expected_lock_version=payload["expected_lock_version"],
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req})


@router.post("/api/requests/{request_id}/start-review")
@require_auth
async def api_start_review(request: Request, request_id: int):
    user = request.state.user
    payload = await _json_body(request)
    if payload.get("expected_lock_version") is None:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT",
                             "message": "expected_lock_version is required."}}, status_code=422)
    db = get_db()
    try:
        try:
            req = svc.start_review(db, user, request_id, payload["expected_lock_version"])
        except svc.CampaignError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req})


@router.post("/api/requests/{request_id}/decide")
@require_capability("evidence.request.review")
async def api_decide_request(request: Request, request_id: int):
    user = request.state.user
    payload = await _json_body(request)
    if payload.get("decision") is None or payload.get("expected_lock_version") is None:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT",
                             "message": "decision and expected_lock_version are required."}}, status_code=422)
    db = get_db()
    try:
        try:
            req = svc.decide_request(
                db, user, request_id, decision=payload["decision"], notes=payload.get("notes", ""),
                expected_lock_version=payload["expected_lock_version"],
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
        log_audit(user, "evidence_campaigns", f"{payload['decision'].capitalize()}ed request {request_id}")
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req})


@router.post("/api/requests/{request_id}/cancel")
@require_capability("evidence.campaign.manage")
async def api_cancel_request(request: Request, request_id: int):
    user = request.state.user
    payload = await _json_body(request)
    if payload.get("reason") is None or payload.get("expected_lock_version") is None:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT",
                             "message": "reason and expected_lock_version are required."}}, status_code=422)
    db = get_db()
    try:
        try:
            req = svc.cancel_request(
                db, user, request_id, reason=payload["reason"],
                expected_lock_version=payload["expected_lock_version"],
            )
        except svc.CampaignError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "request": req})
