"""Tests for the Google Apps Script email transport contract."""
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.smtp import SmtpError, send_email, verify_smtp_connection
from app.integrations.smtp_client import send_email as reexported_send_email, verify_smtp_connection as reexported_verify


class _FakeWebhookResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"result": "success"}'


class _FakeHtmlWebhookResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"<html><body>Google Apps Script deployment page</body></html>"


def test_smtp_client_reexport():
    """Verify integrations.smtp_client re-exports send_email successfully."""
    assert send_email is reexported_send_email
    assert verify_smtp_connection is reexported_verify


@patch("urllib.request.urlopen")
def test_send_email_uses_app_script_webhook_success(mock_urlopen, monkeypatch):
    """Verify a configured Google Apps Script webhook is used as the sole email transport."""
    monkeypatch.setattr(settings, "GMAIL_WEBHOOK_URL", "https://example.com/webhook")
    mock_urlopen.return_value = _FakeWebhookResponse()

    send_email(
        to="recipient@example.com",
        subject="Test Subject",
        body="Test Body Message",
        html_body="<p>Test Body Message</p>",
    )

    request = mock_urlopen.call_args.args[0]
    assert request.full_url.startswith("https://example.com/webhook?")


def test_send_email_missing_webhook_config(monkeypatch):
    """Verify SmtpError is raised if the App Script webhook URL is empty."""
    monkeypatch.setattr(settings, "GMAIL_WEBHOOK_URL", "")
    with pytest.raises(SmtpError, match="Google Apps Script webhook is not configured"):
        send_email(to="recipient@example.com", subject="Subject", body="Body")


@patch("urllib.request.urlopen")
def test_send_email_rejects_html_200_webhook_as_false_positive(mock_urlopen, monkeypatch):
    """A plain HTML 200 response from the Google Apps Script webhook must not count as a delivered email."""
    monkeypatch.setattr(settings, "GMAIL_WEBHOOK_URL", "https://example.com/webhook")
    mock_urlopen.return_value = _FakeHtmlWebhookResponse()

    with pytest.raises(SmtpError, match="Google Apps Script webhook is configured"):
        send_email(
            to="recipient@example.com",
            subject="Test Subject",
            body="Test Body Message",
        )


@patch("app.core.smtp.send_email")
def test_send_test_email_endpoint(mock_send_email, client, admin_headers):
    """Verify POST /api/v1/notifications/test-email endpoint for admin user."""
    response = client.post(
        "/api/v1/notifications/test-email?target_email=verify@example.com",
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    mock_send_email.assert_called_once_with(
        to="verify@example.com",
        subject="[SACCO System] Test Email Verification",
        body="This is a test email sent from SACCO System using Google Apps Script webhook configuration. Your email settings are working correctly!",
    )
