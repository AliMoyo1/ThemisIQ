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
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    # OpenRouter (OpenAI-compatible gateway). The default is deliberately an
    # exact, paid model slug rather than an auto/latest/free alias so a catalog
    # change cannot silently move production calls to a different model.
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv(
        "OPENROUTER_MODEL", "z-ai/glm-5.3-flash"
    )
    # GLM 5.3 Flash has mandatory reasoning and defaults to maximum effort.
    # Keep the production default low so reasoning cannot consume the entire
    # completion budget before the model emits user-visible content.
    OPENROUTER_REASONING_EFFORT: str = os.getenv(
        "OPENROUTER_REASONING_EFFORT", "low"
    ).lower()
    OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "https://app.themisiq.net")
    OPENROUTER_APP_NAME: str = os.getenv("OPENROUTER_APP_NAME", "ThemisIQ")
    OPENROUTER_REQUIRE_EXACT_MODEL: bool = os.getenv(
        "OPENROUTER_REQUIRE_EXACT_MODEL", "true"
    ).lower() in ("1", "true", "yes", "on")
    OPENROUTER_ZDR: bool = os.getenv("OPENROUTER_ZDR", "true").lower() in (
        "1", "true", "yes", "on"
    )
    OPENROUTER_DATA_COLLECTION: str = os.getenv(
        "OPENROUTER_DATA_COLLECTION", "deny"
    ).lower()
    OPENROUTER_MAX_INPUT_PRICE_PER_M: float = float(os.getenv(
        "OPENROUTER_MAX_INPUT_PRICE_PER_M", "0.25"
    ))
    OPENROUTER_MAX_OUTPUT_PRICE_PER_M: float = float(os.getenv(
        "OPENROUTER_MAX_OUTPUT_PRICE_PER_M", "0.75"
    ))
    OPENROUTER_WEB_SEARCH_ENGINE: str = os.getenv(
        "OPENROUTER_WEB_SEARCH_ENGINE", "exa"
    ).lower()
    OPENROUTER_WEB_SEARCH_MAX_RESULTS: int = int(os.getenv(
        "OPENROUTER_WEB_SEARCH_MAX_RESULTS", "5"
    ))
    OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS: int = int(os.getenv(
        "OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS", "15"
    ))

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
    ERM_SCAN_MAX_TOKENS: int = int(os.getenv("ERM_SCAN_MAX_TOKENS", "3000"))
    # Tailored to this deployment's actual sector (telecom) and jurisdiction
    # (Zimbabwe/Africa) rather than a generic EU/US list: general GRC +
    # cyber authorities, telecom-sector bodies, and Zimbabwe/regional
    # regulators relevant to a mobile-money product (EcoCash).
    ERM_SCAN_ALLOWED_DOMAINS: list = [d.strip() for d in os.getenv(
        "ERM_SCAN_ALLOWED_DOMAINS",
        "iso.org,weforum.org,reuters.com,nist.gov,cisa.gov,enisa.europa.eu,"
        "csoonline.com,darkreading.com,gsma.com,itu.int,rbz.co.zw,"
        "potraz.gov.zw,fatf-gafi.org"
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

    # ── PLAN-35: ARIA policy authoring workflow ─────────────────────────────
    # Disabled by default. ARIA_POLICY_AUTHORING_ORG_IDS empty means no
    # tenant is enabled even if the flag above is somehow set true --
    # enabling authoring is an explicit per-org allowlist, never a blanket
    # default-on switch.
    ARIA_POLICY_AUTHORING_ENABLED: bool = os.getenv(
        "ARIA_POLICY_AUTHORING_ENABLED", "false"
    ).lower() in ("1", "true", "yes", "on")
    ARIA_POLICY_AUTHORING_ORG_IDS: list = [
        int(x.strip()) for x in os.getenv("ARIA_POLICY_AUTHORING_ORG_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    # App-side settings only: the shared spool directory exchanged with the
    # converter worker container, and how long to wait for a conversion
    # before giving up. The converter executable path is the WORKER
    # container's own environment setting (ARIA_POLICY_PREVIEW_EXECUTABLE,
    # section 7.4/7.6) -- the app process never invokes LibreOffice directly
    # and has no business knowing where its binary lives.
    ARIA_POLICY_PREVIEW_SPOOL_DIR: str = os.getenv(
        "ARIA_POLICY_PREVIEW_SPOOL_DIR", str(BASE_DIR / "data" / "aria_preview_spool")
    )
    ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS: int = int(
        os.getenv("ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS", "60")
    )
    ARIA_POLICY_DRAFT_EXPIRY_DAYS: int = int(os.getenv("ARIA_POLICY_DRAFT_EXPIRY_DAYS", "30"))
    ARIA_POLICY_ORPHAN_GRACE_HOURS: int = int(os.getenv("ARIA_POLICY_ORPHAN_GRACE_HOURS", "24"))
    ARIA_POLICY_TRASH_RETENTION_DAYS: int = int(
        os.getenv("ARIA_POLICY_TRASH_RETENTION_DAYS", "7")
    )


settings = Settings()


def _validate_aria_policy_workflow_settings(s: "Settings") -> None:
    """Fail fast at startup on a nonsensical PLAN-35 setting (e.g. a
    negative timeout) rather than surface it later as a confusing runtime
    error deep inside a build or cleanup job. int(os.getenv(...)) above
    already fails fast on a non-numeric value; this checks the remaining
    "numeric but meaningless" cases."""
    checks = (
        ("ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS", s.ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS),
        ("ARIA_POLICY_DRAFT_EXPIRY_DAYS", s.ARIA_POLICY_DRAFT_EXPIRY_DAYS),
        ("ARIA_POLICY_ORPHAN_GRACE_HOURS", s.ARIA_POLICY_ORPHAN_GRACE_HOURS),
        ("ARIA_POLICY_TRASH_RETENTION_DAYS", s.ARIA_POLICY_TRASH_RETENTION_DAYS),
    )
    for name, value in checks:
        if value <= 0:
            raise RuntimeError(f"{name} must be a positive integer, got {value}.")


_validate_aria_policy_workflow_settings(settings)
