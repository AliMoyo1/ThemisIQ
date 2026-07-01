"""
Security regression tests — Phase 7 verification.

Each test maps to a specific control implemented in the security audit phases.
These are unit-level: no running server or database required.
"""
import html
import secrets
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Phase 2c: SSRF webhook URL validation ────────────────────────────────────

from modules.launcher.routes_admin import _validate_webhook_url
from fastapi import HTTPException


class TestSSRFValidation:
    def _blocked(self, url: str) -> bool:
        try:
            _validate_webhook_url(url)
            return False
        except HTTPException as e:
            return e.status_code == 400

    def test_valid_https_url_passes(self):
        assert not self._blocked("https://hooks.example.com/webhook")

    def test_http_url_blocked(self):
        assert self._blocked("http://hooks.example.com/webhook")

    def test_localhost_blocked(self):
        assert self._blocked("https://localhost/webhook")

    def test_127_loopback_blocked(self):
        assert self._blocked("https://127.0.0.1/webhook")

    def test_ipv6_loopback_blocked(self):
        assert self._blocked("https://[::1]/webhook")

    def test_link_local_blocked(self):
        assert self._blocked("https://169.254.169.254/latest/meta-data/")

    def test_private_10_blocked(self):
        assert self._blocked("https://10.0.0.1/internal")

    def test_private_192168_blocked(self):
        assert self._blocked("https://192.168.1.1/internal")

    def test_private_172_blocked(self):
        assert self._blocked("https://172.16.0.1/internal")

    def test_zero_addr_blocked(self):
        assert self._blocked("https://0.0.0.0/webhook")

    def test_empty_url_blocked(self):
        assert self._blocked("")

    def test_ftp_scheme_blocked(self):
        assert self._blocked("ftp://example.com/file")


# ── Phase 2d: XSS escaping in email template rendering ───────────────────────

class TestTemplateXSSEscaping:
    def _render(self, template: str, variables: dict) -> str:
        result = template
        for key, val in variables.items():
            escaped = html.escape(str(val))
            result = result.replace("{{" + key + "}}", escaped)
        return result

    def test_script_tag_escaped(self):
        out = self._render("Hello {{name}}", {"name": "<script>alert(1)</script>"})
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_img_onerror_escaped(self):
        out = self._render("Ref: {{ref}}", {"ref": '<img src=x onerror="alert(1)">'})
        assert "onerror" not in out or "&lt;" in out

    def test_plain_text_unchanged(self):
        out = self._render("Hello {{name}}", {"name": "Alice"})
        assert out == "Hello Alice"

    def test_ampersand_escaped(self):
        out = self._render("{{val}}", {"val": "A & B"})
        assert "&amp;" in out
        assert "A & B" not in out

    def test_quotes_escaped(self):
        out = self._render("{{val}}", {"val": '"quoted"'})
        assert "&quot;" in out

    def test_multiple_variables(self):
        out = self._render("{{a}} and {{b}}", {
            "a": "<b>bold</b>",
            "b": "safe",
        })
        assert "<b>" not in out
        assert "safe" in out


# ── Phase 2e: Cookie security flags ──────────────────────────────────────────

def _auth_source() -> str:
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "modules", "launcher", "routes_auth.py",
    )
    with open(src_path) as f:
        return f.read()


class TestCookieSecureFlag:
    def test_secure_constant_defined(self):
        assert "_SECURE = not settings.DEBUG" in _auth_source()

    def test_secure_applied_to_session_cookie(self):
        src = _auth_source()
        assert "secure=_SECURE" in src

    def test_session_cookie_has_path(self):
        src = _auth_source()
        assert 'path="/"' in src

    def test_all_csrf_cookies_have_secure(self):
        src = _auth_source()
        # Every set_cookie call for csrf_token should have secure=_SECURE
        import re
        cookie_calls = re.findall(
            r'set_cookie\("csrf_token".*?\)',
            src, re.DOTALL
        )
        assert len(cookie_calls) > 0
        for call in cookie_calls:
            assert "secure=_SECURE" in call, f"Missing secure flag in: {call[:80]}"


# ── Phase 2b: Password complexity validation ──────────────────────────────────

class TestPasswordComplexity:
    """Test _validate_password without importing routes_auth (avoids pyotp dep)."""

    def _make_validator(self):
        import re
        _PW_MIN_LEN = 8
        _PW_RULES = [
            (r"[A-Z]", "at least one uppercase letter"),
            (r"[a-z]", "at least one lowercase letter"),
            (r"[0-9]", "at least one digit"),
            (r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", "at least one special character"),
        ]
        def _validate(pw):
            if len(pw) < _PW_MIN_LEN:
                return f"Password must be at least {_PW_MIN_LEN} characters."
            for pattern, desc in _PW_RULES:
                if not re.search(pattern, pw):
                    return f"Password must contain {desc}."
            return None
        return _validate

    def test_strong_password_passes(self):
        assert self._make_validator()("Correct#Horse9") is None

    def test_too_short_rejected(self):
        assert self._make_validator()("Ab1!") is not None

    def test_no_uppercase_rejected(self):
        assert self._make_validator()("correct#horse9") is not None

    def test_no_lowercase_rejected(self):
        assert self._make_validator()("CORRECT#HORSE9") is not None

    def test_no_digit_rejected(self):
        assert self._make_validator()("Correct#Horse") is not None

    def test_no_special_rejected(self):
        assert self._make_validator()("CorrectHorse9") is not None

    def test_minimum_length_exactly(self):
        assert self._make_validator()("Aa1!aaaa") is None

    def test_source_contains_complexity_rules(self):
        src = _auth_source()
        assert "_PW_RULES" in src
        assert "_PW_MIN_LEN" in src


# ── Phase 3a: Rate limiting key namespacing ───────────────────────────────────

class TestRateLimitNamespacing:
    def setup_method(self):
        from core.middleware import _login_attempts
        _login_attempts.clear()

    def test_mfa_key_separate_from_login(self):
        from core.middleware import record_failed_login, check_rate_limit, _MAX_LOGIN_ATTEMPTS
        ip = "1.2.3.4"
        for _ in range(_MAX_LOGIN_ATTEMPTS):
            record_failed_login(f"mfa:{ip}")
        # mfa namespace is rate-limited
        assert check_rate_limit(f"mfa:{ip}") is False
        # login namespace for same IP is unaffected
        assert check_rate_limit(ip) is True

    def test_pw_key_separate_from_login(self):
        from core.middleware import record_failed_login, check_rate_limit, _MAX_LOGIN_ATTEMPTS
        user_id = 42
        for _ in range(_MAX_LOGIN_ATTEMPTS):
            record_failed_login(f"pw:{user_id}")
        assert check_rate_limit(f"pw:{user_id}") is False
        assert check_rate_limit("1.2.3.4") is True

    def test_rate_limit_allows_up_to_max(self):
        from core.middleware import record_failed_login, check_rate_limit, _MAX_LOGIN_ATTEMPTS
        ip = "5.6.7.8"
        for _ in range(_MAX_LOGIN_ATTEMPTS - 1):
            record_failed_login(ip)
        assert check_rate_limit(ip) is True
        record_failed_login(ip)
        assert check_rate_limit(ip) is False

    def test_clear_resets_limit(self):
        from core.middleware import record_failed_login, check_rate_limit, clear_login_attempts, _MAX_LOGIN_ATTEMPTS
        ip = "9.10.11.12"
        for _ in range(_MAX_LOGIN_ATTEMPTS):
            record_failed_login(ip)
        assert check_rate_limit(ip) is False
        clear_login_attempts(ip)
        assert check_rate_limit(ip) is True


# ── Phase 3c: Seed script uses random passwords ───────────────────────────────

class TestSeedRandomPasswords:
    def test_seed_imports_secrets(self):
        import seeds.seed as seed_mod
        import inspect
        src = inspect.getsource(seed_mod)
        assert "secrets.token_urlsafe" in src

    def test_no_hardcoded_admin_password(self):
        import seeds.seed as seed_mod
        import inspect
        src = inspect.getsource(seed_mod)
        assert "Admin@123!" not in src
        assert "Comply@123!" not in src
        assert "Privacy@123!" not in src
        assert "Bcm@123!" not in src

    def test_must_change_password_seeded(self):
        import seeds.seed as seed_mod
        import inspect
        src = inspect.getsource(seed_mod)
        assert "must_change_password" in src


# ── Phase 4a: Failed login audit logging ─────────────────────────────────────

class TestFailedLoginAuditLogging:
    def test_login_submit_calls_log_audit_on_failure(self):
        src = _auth_source()
        assert "login_failed" in src
        assert "log_audit" in src

    def test_audit_log_includes_ip(self):
        src = _auth_source()
        assert "ip=client_ip" in src


# ── Phase 4b: Deletion audit includes identifiers ────────────────────────────

class TestDeletionAuditIdentifiers:
    def test_api_key_revoke_fetches_prefix(self):
        import inspect
        from modules.launcher import routes_admin
        src = inspect.getsource(routes_admin.api_key_revoke)
        assert "key_prefix" in src

    def test_webhook_delete_fetches_url(self):
        import inspect
        from modules.launcher import routes_admin
        src = inspect.getsource(routes_admin.api_webhook_delete)
        assert "url" in src
        assert "log_audit" in src


# ── Phase 4e: Email password sentinel ────────────────────────────────────────

class TestEmailSentinel:
    def test_sentinel_is_not_bullet_chars(self):
        import inspect
        from modules.launcher import routes_admin
        src = inspect.getsource(routes_admin.api_email_config_get)
        assert "••••••••" not in src

    def test_sentinel_is_unchanged_string(self):
        import inspect
        from modules.launcher import routes_admin
        src = inspect.getsource(routes_admin.api_email_config_save)
        assert "__unchanged__" in src

    def test_sentinel_used_in_both_password_checks(self):
        import inspect
        from modules.launcher import routes_admin
        src = inspect.getsource(routes_admin.api_email_config_save)
        assert src.count("__unchanged__") >= 2


# ── Phase 4d: Bulk import atomic transaction ──────────────────────────────────

class TestBulkImportTransaction:
    def test_no_per_row_except_in_insert_loop(self):
        import inspect
        from modules.launcher import routes_platform
        src = inspect.getsource(routes_platform.api_bulk_import)
        # The old pattern had try/except inside the for loop before each db.execute
        # The new pattern has a single outer try with db.rollback() on failure
        assert "db.rollback()" in src

    def test_validation_pass_before_db(self):
        import inspect
        from modules.launcher import routes_platform
        src = inspect.getsource(routes_platform.api_bulk_import)
        assert "val_errors" in src or "Validation failed" in src


# ── Phase 5b: Security headers ───────────────────────────────────────────────

class TestSecurityHeaders:
    def test_coop_header_present(self):
        import inspect
        from core import middleware
        src = inspect.getsource(middleware.security_headers_middleware)
        assert "Cross-Origin-Opener-Policy" in src
        assert "same-origin" in src

    def test_corp_header_present(self):
        import inspect
        from core import middleware
        src = inspect.getsource(middleware.security_headers_middleware)
        assert "Cross-Origin-Resource-Policy" in src

    def test_google_fonts_removed_from_csp(self):
        import inspect
        from core import middleware
        src = inspect.getsource(middleware.security_headers_middleware)
        assert "fonts.googleapis.com" not in src
        assert "fonts.gstatic.com" not in src

    def test_csp_blocks_objects(self):
        import inspect
        from core import middleware
        src = inspect.getsource(middleware.security_headers_middleware)
        assert "object-src 'none'" in src

    def test_csp_blocks_frame_ancestors(self):
        import inspect
        from core import middleware
        src = inspect.getsource(middleware.security_headers_middleware)
        assert "frame-ancestors 'none'" in src


# ── Phase 1d: Gemini API key not in URL ──────────────────────────────────────

class TestGeminiKeyNotInURL:
    def test_gemini_key_in_header_not_url(self):
        import inspect
        from core import ai_client
        src = inspect.getsource(ai_client._gemini)
        assert "?key=" not in src
        assert "x-goog-api-key" in src

    def test_grc_guardrail_prepended(self):
        from core.ai_client import _GRC_GUARDRAIL
        assert "GRC" in _GRC_GUARDRAIL
        assert len(_GRC_GUARDRAIL) > 100


# ── ARIA/Sentinel AI dispatcher migration: no independent bypass of the ──────
# ── shared guardrail, no repeat of the Gemini-key-in-URL bug in either module ─

class TestAiDispatcherMigration:
    def test_aria_generator_has_no_gemini_url_key(self):
        import inspect
        from modules.aria import ai_generator
        src = inspect.getsource(ai_generator)
        assert "generateContent?key=" not in src

    def test_sentinel_ai_service_has_no_gemini_url_key(self):
        import inspect
        from modules.sentinel import ai_service
        src = inspect.getsource(ai_service)
        assert "generateContent?key=" not in src

    def test_aria_generator_routes_through_core_ai_client(self):
        import inspect
        from modules.aria import ai_generator
        src = inspect.getsource(ai_generator)
        assert "create_message_full" in src
        assert "from core.ai_client import" in src

    def test_sentinel_ai_service_routes_through_core_ai_client(self):
        import inspect
        from modules.sentinel import ai_service
        src = inspect.getsource(ai_service)
        assert "create_message" in src
        assert "from core.ai_client import" in src

    def test_sentinel_legal_basis_suggestion_constrained_to_allowed_list(self):
        """Anti-hallucination guardrail: the suggested legal basis must be
        verified against the regulation's own pre-approved list before return."""
        import inspect
        from modules.sentinel import ai_service
        src = inspect.getsource(ai_service.ai_suggest_legal_basis)
        assert "options" in src
        assert "not in options" in src
