FROM python:3.11-slim

# Runtime libs: libpq5 (psycopg2), postgresql-client (pg_dump for backups),
# curl (container healthcheck).  No build tools in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with a fixed UID — host volumes should be owned by UID 1000.
RUN useradd --create-home --uid 1000 themisiq

WORKDIR /app

# Install Python deps before copying app code so this layer is cached until
# requirements.txt changes.
COPY --chown=themisiq:themisiq oneforall/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY --chown=themisiq:themisiq oneforall/ .

# Ensure entrypoint is executable (Windows hosts don't preserve the x-bit).
RUN chmod +x entrypoint.sh

USER themisiq

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
