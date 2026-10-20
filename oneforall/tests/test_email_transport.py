"""
The mail transport says what actually happened and never claims a delivery it did not make
(plans/2026-10-governance-rework/06 sections 2, 6 and 9, phase E1).

Before this a console fallback returned ok=True, a missing credential fell back to the console, the STARTTLS connection did
not verify the server, the message had no plain text part, and a recipient or subject with a line break could add a
header. The tests drive the real transport functions against a fake SMTP server and a fake provider.
"""
import smtplib
import ssl

import pytest

from core import email as mail


class FakeSMTP:
    sent = []
    context = None
    logged_in = None
    fail = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        FakeSMTP.context = context

    def login(self, user, password):
        FakeSMTP.logged_in = (user, password)
        if FakeSMTP.fail == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, message):
        if FakeSMTP.fail == "refused":
            raise smtplib.SMTPRecipientsRefused({})
        if FakeSMTP.fail == "timeout":
            raise TimeoutError("timed out")
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fresh_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.context, FakeSMTP.logged_in, FakeSMTP.fail = [], None, None, None
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.delenv("SMTP_REPLY_TO", raising=False)
    return FakeSMTP


@pytest.fixture
def gmail(monkeypatch):
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "google")
    monkeypatch.setattr(mail, "_smtp_config", lambda: {
        "host": "smtp.gmail.com", "port": 587, "user": "themisiq.alerts@gmail.com", "password": "abcd efgh ijkl mnop",
        "from": "ThemisIQ <noreply@themisiq.net>"})


def test_console_mode_is_logged_only_and_is_never_ok(monkeypatch):
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "console")
    got = mail.send_email(to="a@example.test", subject="Hello", body_html="<p>Hi</p>")
    assert got["status"] == mail.STATUS_LOGGED and got["ok"] is False and got["provider"] == "console"


def test_a_missing_credential_is_logged_only_not_a_send(monkeypatch):
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "google")
    monkeypatch.setattr(mail, "_smtp_config", lambda: {
        "host": "smtp.gmail.com", "port": 587, "user": "themisiq.alerts@gmail.com", "password": "", "from": ""})
    got = mail.send_email(to="a@example.test", subject="Hello", body_html="<p>Hi</p>")
    assert got["status"] == mail.STATUS_LOGGED and got["ok"] is False and got["reason"] == "not_configured"
    assert FakeSMTP.sent == []


def test_an_address_that_is_not_a_plain_address_is_suppressed(gmail):
    for bad in ("", "no-at-sign", "a@b", "x@y.co, z@y.co", "Name <a@b.co>", "a@b.co\nBcc: c@d.co"):
        got = mail.send_email(to=bad, subject="Hello", body_html="<p>Hi</p>")
        assert got["status"] == mail.STATUS_SUPPRESSED and got["ok"] is False, repr(bad)
    assert FakeSMTP.sent == []
    assert mail.send_email(to="a@b.co", subject="  ", body_html="<p>x</p>")["status"] == mail.STATUS_SUPPRESSED


def test_an_accepted_message_has_both_parts_a_verified_tls_context_and_the_mailbox_as_sender(gmail, monkeypatch):
    monkeypatch.setenv("SMTP_REPLY_TO", "support@themisiq.net")
    got = mail.send_email(to="owner@example.test", subject="ThemisIQ: evidence needs review",
                          body_html="<p>Open <a href='https://app.themisiq.net/evidence/'>the item</a></p>")
    assert got["status"] == mail.STATUS_ACCEPTED and got["ok"] is True and got["provider"] == "google"
    (message,) = FakeSMTP.sent
    assert message["From"] == '"ThemisIQ" <themisiq.alerts@gmail.com>', "the mailbox, not a branded address"
    assert message["To"] == "owner@example.test" and message["Reply-To"] == "support@themisiq.net"
    assert message["Auto-Submitted"] == "auto-generated" and message["Message-ID"] and message["Date"]
    parts = [p.get_content_type() for p in message.get_payload()]
    assert parts == ["text/plain", "text/html"]
    assert "https://app.themisiq.net/evidence/" in message.get_payload()[0].get_payload(decode=True).decode("utf-8")
    assert isinstance(FakeSMTP.context, ssl.SSLContext) and FakeSMTP.context.verify_mode == ssl.CERT_REQUIRED
    assert FakeSMTP.context.check_hostname is True
    assert FakeSMTP.logged_in == ("themisiq.alerts@gmail.com", "abcdefghijklmnop"), "an app password is sent without spaces"


def test_a_subject_with_a_line_break_cannot_start_a_header(gmail):
    got = mail.send_email(to="owner@example.test", subject="Hello\r\nBcc: attacker@example.test", body_html="<p>Hi</p>")
    assert got["ok"] is True
    (message,) = FakeSMTP.sent
    assert message["Bcc"] is None
    assert "\n" not in message["Subject"] and "\r" not in message["Subject"]


def test_a_refused_recipient_or_bad_login_is_permanent_and_a_timeout_is_not(gmail):
    FakeSMTP.fail = "refused"
    got = mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    assert got["status"] == mail.STATUS_FAILED and got["ok"] is False and got["permanent"] is True
    FakeSMTP.fail = "auth"
    got = mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    assert got["status"] == mail.STATUS_FAILED and got["permanent"] is True
    FakeSMTP.fail = "timeout"
    got = mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    assert got["status"] == mail.STATUS_FAILED and got["permanent"] is False and "TimeoutError" in got["error"]
    assert "abcd" not in got["error"], "no credential in an error"


def test_an_error_names_its_class_and_code_and_never_the_recipient_or_the_server_text(gmail):
    FakeSMTP.fail = "refused"
    got = mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    assert got["error"] == "SMTPRecipientsRefused" and "owner@example.test" not in got["error"]
    FakeSMTP.fail = "auth"
    got = mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    assert got["error"] == "SMTPAuthenticationError 535" and "bad credentials" not in got["error"]


def test_a_plain_text_part_is_made_from_html_when_none_is_given():
    text = mail.html_to_text("<div><h1>Title</h1><p>One<br>two</p><a href='https://x.test/a'>link</a>"
                             "<script>alert(1)</script></div>")
    assert "Title" in text and "One" in text and "two" in text
    assert "alert" not in text and "(https://x.test/a)" in text


def test_the_app_origin_is_https_or_nothing(monkeypatch):
    cases = {"https://app.themisiq.net": "https://app.themisiq.net", "https://app.themisiq.net/": "https://app.themisiq.net",
             "http://app.themisiq.net": "", "http://localhost:8000": "http://localhost:8000", "": "",
             "javascript:alert(1)": "", "https://user:pw@app.themisiq.net": "", "https://app.themisiq.net/x?y=1": ""}
    for configured, expected in cases.items():
        monkeypatch.setenv("APP_URL", configured)
        assert mail.app_origin() == expected, configured


def test_a_password_is_a_deployment_secret_and_the_stored_copy_is_reported(monkeypatch):
    monkeypatch.setattr(mail.settings, "SMTP_PASS", "from-environment")
    monkeypatch.setattr(mail, "_get_setting", lambda key, default="": {
        "smtp_pass_enc": mail.encrypt_setting("old-stored"), "smtp_host": "smtp.gmail.com", "smtp_user": "m@gmail.com"
    }.get(key, default))
    assert mail._smtp_config()["password"] == "from-environment", "the environment wins over a stored value"
    assert mail.credential_source() == "environment"
    monkeypatch.setattr(mail.settings, "SMTP_PASS", "")
    assert mail._smtp_config()["password"] == "old-stored" and mail.credential_source() == "stored_obscured"
    assert any("obscured but not encrypted" in w for w in mail.health()["warnings"])
    assert "old-stored" not in str(mail.health())


def test_the_connection_test_does_not_call_console_mode_a_working_connection(monkeypatch):
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "console")
    got = mail.test_connection()
    assert got["ok"] is False and got["status"] == mail.STATUS_LOGGED


def test_the_shipped_placeholder_sender_is_not_used(monkeypatch):
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "smtp")
    monkeypatch.setattr(mail, "_smtp_config", lambda: {
        "host": "smtp.example.test", "port": 587, "user": "alerts@corp.example.test", "password": "pw",
        "from": "ThemisIQ <noreply@example.com>"})
    mail.send_email(to="owner@example.test", subject="s", body_html="<p>x</p>")
    (message,) = FakeSMTP.sent
    assert "example.com" not in message["From"] and "alerts@corp.example.test" in message["From"]
