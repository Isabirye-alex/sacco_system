"""
Tests for SMTP email module and Google App Password functionality.
"""
from unittest.mock import MagicMock, patch
import smtplib
import pytest

from app.core.config import settings
from app.core.smtp import SmtpError, send_email, verify_smtp_connection
from app.integrations.smtp_client import send_email as reexported_send_email, verify_smtp_connection as reexported_verify


def test_smtp_client_reexport():
    """Verify integrations.smtp_client re-exports send_email successfully."""
    assert send_email is reexported_send_email
    assert verify_smtp_connection is reexported_verify


@patch("smtplib.SMTP")
def test_send_email_tls_google_app_password_space_stripping(mock_smtp_cls, monkeypatch):
    """Verify that Google App Password with spaces ('abcd efgh ijkl mnop') is stripped and login is called."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "testuser@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "testuser@gmail.com")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "SACCO Admin")
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USE_SSL", False)

    mock_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_instance

    send_email(
        to="recipient@example.com",
        subject="Test Subject",
        body="Test Body Message",
        html_body="<p>Test Body Message</p>"
    )

    mock_instance.starttls.assert_called_once()
    # Check that spaces were stripped from "abcd efgh ijkl mnop" -> "abcdefghijklmnop"
    mock_instance.login.assert_called_once_with("testuser@gmail.com", "abcdefghijklmnop")
    mock_instance.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_send_email_ssl_mode(mock_smtp_ssl_cls, monkeypatch):
    """Verify SSL mode when SMTP_PORT is 465 or SMTP_USE_SSL is True."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "testuser@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secretpass")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "testuser@gmail.com")
    monkeypatch.setattr(settings, "SMTP_USE_SSL", True)

    mock_instance = MagicMock()
    mock_smtp_ssl_cls.return_value.__enter__.return_value = mock_instance

    send_email(to="recipient@example.com", subject="Test SSL", body="Test Body")

    mock_instance.login.assert_called_once_with("testuser@gmail.com", "secretpass")
    mock_instance.send_message.assert_called_once()


def test_send_email_missing_host(monkeypatch):
    """Verify SmtpError is raised if SMTP_HOST is empty."""
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with pytest.raises(SmtpError, match="SMTP is not configured"):
        send_email(to="recipient@example.com", subject="Subject", body="Body")


@patch("smtplib.SMTP")
def test_send_email_authentication_error(mock_smtp_cls, monkeypatch):
    """Verify friendly error hint on Google SMTP authentication failure."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "testuser@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "wrongpass")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "testuser@gmail.com")

    mock_instance = MagicMock()
    mock_instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted.")
    mock_smtp_cls.return_value.__enter__.return_value = mock_instance

    with pytest.raises(SmtpError, match="Check your Gmail email and 16-character App Password"):
        send_email(to="recipient@example.com", subject="Subject", body="Body")


@patch("app.core.smtp.send_email")
def test_send_test_email_endpoint(mock_send_email, client, admin_headers):
    """Verify POST /api/v1/notifications/test-email endpoint for admin user."""
    response = client.post(
        "/api/v1/notifications/test-email?target_email=verify@example.com",
        headers=admin_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    mock_send_email.assert_called_once_with(
        to="verify@example.com",
        subject="[SACCO System] Test Email Verification",
        body="This is a test email sent from SACCO System using Google SMTP configuration. Your email settings are working correctly!"
    )
