# PLAN-35 T05: ARIA policy conversion worker image.
#
# Isolated from the main app image (root Dockerfile): this container's only
# job is DOCX-to-PDF conversion via LibreOffice headless, reached through a
# private shared spool directory, never a network port. It must never
# import application code, receive the app's .env, or see the application
# database. Build with a pinned base digest for a reproducible, reviewable
# image; do not float on a mutable tag in the deployed reference.
#
# Build:   docker build -t themisiq/aria-preview:<tag> -f deploy/aria-preview/Dockerfile .
# Run:     see docker-compose.yml's aria-preview service.

FROM debian:bookworm-slim@sha256:PIN_ME_AT_RELEASE_TIME

# libreoffice-writer pulls in the ODF/OOXML filters needed for .docx ->
# .pdf; fonts-liberation2 approximates common MS-metric-compatible fonts
# (Arial/Calibri/Times New Roman substitutes) so branded templates render
# with predictable line breaks instead of falling back to a default serif.
# Extend this list deliberately if a specific template needs a font this
# doesn't cover -- do not add a broad "fonts-*" metapackage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation2 \
        python3-minimal \
    && rm -rf /var/lib/apt/lists/*

# Non-root, fixed UID matching the app image's convention (see root
# Dockerfile). No shell access needed beyond what the worker script uses.
RUN useradd --create-home --uid 1001 ariaworker

WORKDIR /worker

# Only the worker script and its own pinned requirements -- never the
# application's requirements.txt, config.py, or database.py.
COPY --chown=ariaworker:ariaworker oneforall/requirements-preview.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements-preview.txt

COPY --chown=ariaworker:ariaworker oneforall/scripts/aria_policy_preview_worker.py .
COPY --chown=ariaworker:ariaworker deploy/aria-preview/runtime-manifest.json .

USER ariaworker

# No EXPOSE: this container publishes no ports (network_mode: none in
# compose). Healthcheck runs the worker's own --once mode against an empty
# spool, which exits cleanly without needing a live job.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 aria_policy_preview_worker.py --once || exit 1

ENTRYPOINT ["python3", "aria_policy_preview_worker.py"]
