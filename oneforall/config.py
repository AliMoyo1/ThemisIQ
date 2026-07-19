"""
One For All — configuration loaded from environment / .env file.
"""
import os
import secrets
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

_log = logging.getLogger("oneforall.config")


def _resolve_secret_key() -> str:
    """Return SECRET_KEY from env, or — only in DEBUG mode — auto-generate one.

    In production (DEBUG=false) a missing SECRET_KEY is a hard error: sessions
    silently invalidate every restart and there is no recovery, so refuse to
    start rather than appear to work.
    """
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes", "on")
    if debug:
        _log.warning(
            "SECRET_KEY not set — auto-generating an ephemeral key for DEBUG mode. "
            "Sessions will be invalidated on every restart. Set SECRET_KEY in .env."
        )
        return secrets.token_hex(32)
    raise RuntimeError(
        "SECRET_KEY environment variable is required in production. "
        "Generate one with `python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "and set it in .env, or set DEBUG=true to allow auto-generation."
    )


class Settings:
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes", "on")
    SECRET_KEY: str = _resolve_secret_key()
    DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "oneforall.db"))

    # Fallback regulation key when no specific one is set on a record/event AND
    # no per-org primary jurisdiction is configured. Override per deployment.
    DEFAULT_REGULATION: str = os.getenv("DEFAULT_REGULATION", "GDPR")

    # AI — multi-provider support (Sentinel module)
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "anthropic").lower()
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    # DeepSeek (cloud API — https://platform.deepseek.com)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL:   str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Ollama (locally hosted — https://ollama.com)
    OLLAMA_HOST:  str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    # ERM v2 (PLAN-28): grounded horizon-scan settings. Pins a current model
    # explicitly rather than inheriting ANTHROPIC_MODEL above, which may be
    # older and lack the web search tool. max_uses is the per-scan cost cap
    # (never exposed as a client-supplied parameter); allowed_domains is the
    # "reliable internet sources" control, changeable per deployment with no
    # code change.
    ERM_SCAN_MODEL: str = os.getenv("ERM_SCAN_MODEL", "claude-sonnet-5")
    ERM_SCAN_MAX_SEARCHES: int = int(os.getenv("ERM_SCAN_MAX_SEARCHES", "8"))
    ERM_SCAN_ALLOWED_DOMAINS: list = [d.strip() for d in os.getenv(
        "ERM_SCAN_ALLOWED_DOMAINS",
        "enisa.europa.eu,edpb.europa.eu,ico.org.uk,nist.gov,cisa.gov,"
        "iso.org,weforum.org,reuters.com,csoonline.com,darkreading.com"
    ).split(",") if d.strip()]

    # ── Email provider ────────────────────────────────────────────────────────
    # Options: "google" | "microsoft_smtp" | "microsoft_graph" | "smtp" | "console"
    # Leave blank for auto-detection from SMTP_HOST, or configure in Admin → Email Settings.
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "")

    # SMTP (works for Google Gmail and Microsoft Office 365 with app passwords)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "ThemisIQ <noreply@example.com>")

    # ── Microsoft Graph API (service account) ────────────────────────────────
    # Required when EMAIL_PROVIDER=microsoft_graph.
    # Create an Azure AD App Registration with Mail.Send application permission.
    MS_TENANT_ID:     str = os.getenv("MS_TENANT_ID", "")
    MS_CLIENT_ID:     str = os.getenv("MS_CLIENT_ID", "")
    MS_CLIENT_SECRET: str = os.getenv("MS_CLIENT_SECRET", "")

    # Admin contact email — receives demo requests and system alerts.
    # Falls back to SMTP_USER if not explicitly set.
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "") or os.getenv("SMTP_USER", "")

    # ── Slack / Teams connectors ──────────────────────────────────────────────
    # Override in Admin > Connectors (values stored in settings table take priority).
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    TEAMS_WEBHOOK_URL: str = os.getenv("TEAMS_WEBHOOK_URL", "")

    # ── PostgreSQL (production) ───────────────────────────────────────────────
    # Set DATABASE_URL to switch from SQLite to PostgreSQL.
    # Example: postgresql://themisiq@pgbouncer:5432/themisiq
    # Leave empty (default) to keep using SQLite for local development.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    POSTGRES_POOL_MIN: int = int(os.getenv("POSTGRES_POOL_MIN", "2"))
    POSTGRES_POOL_MAX: int = int(os.getenv("POSTGRES_POOL_MAX", "10"))

    @staticmethod
    def is_postgres() -> bool:
        return bool(os.getenv("DATABASE_URL", "").startswith("postgresql"))

    # Monitoring
    POSTHOG_API_KEY: str = os.getenv("POSTHOG_API_KEY", "")
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    SENTRY_ENVIRONMENT: str = os.getenv("SENTRY_ENVIRONMENT", "production")

    # Server
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Session
    SESSION_COOKIE_NAME: str = "ofa_session"
    SESSION_MAX_AGE: int = 86400  # 24 hours


settings = Settings()
