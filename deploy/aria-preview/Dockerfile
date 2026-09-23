# PLAN-35 T05: ARIA policy conversion worker image.
#
# Isolated from the main app image (root Dockerfile): this container's only
# job is DOCX-to-PDF conversion via LibreOffice headless, reached through a
# private shared spool directory, never a network port. It must never
# import application code, receive the app's .env, or see the application
# database. Build with a pinned base digest for a reproducible, reviewable
# image; do not float on a mutable tag in the deployed reference.
#
# Build:   use docker-compose.yml for local builds; release builds must supply
#          ARIA_PREVIEW_WORKER_BUILD_ID and ARIA_PREVIEW_BUILT_AT.
# Run:     see docker-compose.yml (full stack) or compose.vps.yml (systemd VPS).

FROM debian:bookworm-slim@sha256:f3034a6ec3c1205360777c4aae76234998866ad18806ae62b63a3f84ccad782b

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
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Non-root image default. The VPS companion Compose file overrides the numeric
# UID/GID with the actual systemd `themisiq` account so the two isolated
# processes can share a private bind mount without making it world-writable.
# No shell access is needed beyond what the worker script uses.
RUN groupadd --gid 1001 ariaworker \
    && useradd --create-home --uid 1001 --gid 1001 ariaworker

WORKDIR /worker

# Only the worker script and its own pinned requirements -- never the
# application's requirements.txt, config.py, or database.py.
COPY --chown=ariaworker:ariaworker oneforall/requirements-preview.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements-preview.txt

COPY --chown=ariaworker:ariaworker oneforall/scripts/aria_policy_preview_worker.py .
COPY deploy/aria-preview/generate_runtime_manifest.py .

# Generate evidence from the image that was actually built. Missing release
# metadata fails the build; a template containing placeholder values is never
# copied into a runnable image. Keep these arguments below the expensive OS
# package layer so a new build ID/timestamp does not invalidate that cache.
ARG ARIA_PREVIEW_WORKER_BUILD_ID
ARG ARIA_PREVIEW_BUILT_AT
RUN test -n "$ARIA_PREVIEW_WORKER_BUILD_ID" \
    && test -n "$ARIA_PREVIEW_BUILT_AT" \
    && python3 generate_runtime_manifest.py \
       --output runtime-manifest.json \
       --base-image "debian:bookworm-slim@sha256:f3034a6ec3c1205360777c4aae76234998866ad18806ae62b63a3f84ccad782b" \
       --worker-build-id "$ARIA_PREVIEW_WORKER_BUILD_ID" \
       --built-at "$ARIA_PREVIEW_BUILT_AT" \
    && rm generate_runtime_manifest.py \
    && chown ariaworker:ariaworker runtime-manifest.json

LABEL org.opencontainers.image.revision=$ARIA_PREVIEW_WORKER_BUILD_ID \
      org.opencontainers.image.created=$ARIA_PREVIEW_BUILT_AT

USER ariaworker

# No EXPOSE: this container publishes no ports (network_mode: none in
# compose). Health checks only verify the build manifest, spool and worker
# heartbeat; they never compete for the singleton lock or launch LibreOffice.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 aria_policy_preview_worker.py --healthcheck || exit 1

ENTRYPOINT ["python3", "aria_policy_preview_worker.py"]
