"""
One way to hand a kit report to a browser as a download, so every module answers a report request the same way: the same
formats, the same safe file name and the same headers (nosniff, no-store). The adapter builds the `Report`; the route checks who
may ask for it and calls `download`.
"""
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from core.report_kit import identity
from core.report_kit.render_pdf import render_pdf
from core.report_kit.render_xlsx import render_xlsx

FORMATS = {
    "pdf": ("application/pdf", render_pdf),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", render_xlsx),
}


def client_ip(request) -> str:
    client = getattr(request, "client", None)
    return client.host if client else ""


def format_of(request):
    """The format a request asks for (`?format=`, pdf by default), or None when it is not one the kit serves."""
    fmt = str(request.query_params.get("format") or "pdf").lower()
    return fmt if fmt in FORMATS else None


async def download(report, fmt, stem) -> Response:
    """The report as an attachment. Rendering is CPU work, so it runs off the event loop."""
    media_type, render = FORMATS[fmt]
    body = await run_in_threadpool(render, report)
    return Response(body, media_type=media_type,
                    headers=identity.download_headers(identity.safe_filename(stem, fmt, when=report.meta.generated_at)))
