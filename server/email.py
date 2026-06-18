"""
email.py — Transactional email for Bazaar.

In development (DEBUG=true), codes are printed to the server console so you
don't need to configure anything.  In production, set the SMTP_* variables
in your environment and codes are emailed for real.

Compatible with any SMTP provider:
  Gmail      → smtp.gmail.com : 587  (use an App Password, not your main password)
  SendGrid   → smtp.sendgrid.net : 587
  Mailgun    → smtp.mailgun.org : 587
  AWS SES    → email-smtp.<region>.amazonaws.com : 587
"""
import smtplib
from email.mime.text import MIMEText

from config import settings


def send_verification_code(to_email: str, code: str) -> None:
    _dispatch(
        to=to_email,
        label="VERIFICATION CODE",
        subject="Verify your Bazaar account",
        body=(
            f"Welcome to Bazaar!\n\n"
            f"Your verification code is: {code}\n\n"
            f"It expires in 15 minutes. If you didn't create an account, ignore this email."
        ),
        code=code,
    )


def send_reset_code(to_email: str, code: str) -> None:
    _dispatch(
        to=to_email,
        label="PASSWORD RESET CODE",
        subject="Reset your Bazaar password",
        body=(
            f"Your password reset code is: {code}\n\n"
            f"It expires in 15 minutes. If you didn't request this, ignore this email."
        ),
        code=code,
    )


# ── internals ─────────────────────────────────────────────────────────────────

def _dispatch(*, to: str, label: str, subject: str, body: str, code: str) -> None:
    if settings.debug:
        _print_to_console(to, label, code)
    else:
        _send_smtp(to=to, subject=subject, body=body)


def _print_to_console(to: str, label: str, code: str) -> None:
    """Dev shortcut — print instead of sending email."""
    border = "=" * 48
    print(f"\n{border}\n  {label}\n  To:   {to}\n  Code: {code}\n{border}\n")


def _send_smtp(*, to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError(
            "SMTP_HOST is not configured. "
            "Set DEBUG=true to print codes to the console during development."
        )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_from
    msg["To"]      = to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
