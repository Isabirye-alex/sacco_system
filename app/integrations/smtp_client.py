"""
SMTP Client Integration module.
Re-exports SMTP functions from app.core.smtp for compatibility with integrations.
"""
from app.core.smtp import SmtpError, send_email, verify_smtp_connection

__all__ = ["send_email", "SmtpError", "verify_smtp_connection"]
