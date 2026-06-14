This directory holds Docker secrets for production.
It MUST NOT be committed to version control.

Setup (run once on the VPS before starting the stack):

    mkdir -p secrets
    openssl rand -base64 32 > secrets/pg_password.txt
    chmod 600 secrets/pg_password.txt

The file is referenced in docker-compose.yml as:

    secrets:
      pg_password:
        file: ./secrets/pg_password.txt

Both the PostgreSQL container and the app container mount this secret
at /run/secrets/pg_password at runtime.
