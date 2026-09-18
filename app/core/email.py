import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("app.email")
settings = get_settings()

_XLSX_CONTENT_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class EmailSendError(AppError):
    status_code = 502
    detail = "Could not send the email — please try again."


def send_email(
    to: str,
    subject: str,
    body_text: str,
    html_body: str | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    from_name: str | None = None,
) -> None:
    """Sends an email, optionally with an HTML alternative and/or one
    attachment, via whichever provider EMAIL_PROVIDER selects (see
    get_email_sender below) — Gmail SMTP or Resend today, same call for
    either.

    - html_body is optional — omit it for plain-text-only (the audit report
      email); pass it alongside body_text for a rich version (the OTP email's
      colorful template) — mail clients that render HTML show html_body,
      everything else falls back to body_text.
    - attachment_bytes/attachment_filename are optional and independent of
      html_body — pass both together for an attachment (the audit .xlsx).
    - from_name overrides the display name in the From header for this one
      email (e.g. "GM Agency App OTP" for login codes) — defaults to
      settings.smtp_from_name (shared across both providers — it's just a
      display name, not actually SMTP-specific) when omitted.

    Raises AppError (config missing, or an unknown EMAIL_PROVIDER) or
    EmailSendError (the send itself failed) rather than ever returning a
    fake success — the caller must not catch these and report success
    anyway.
    """
    sender = get_email_sender()
    sender(
        to,
        subject,
        body_text,
        html_body=html_body,
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment_filename,
        from_name=from_name,
    )


def get_email_sender():
    """Same pattern as app.core.sms.get_sms_provider — one flag, one
    implementation picked, both fully available in the codebase regardless
    of which is active.
    """
    if settings.email_provider == "smtp":
        return _send_email_smtp
    if settings.email_provider == "resend":
        return _send_email_resend
    raise NotImplementedError(
        f"No email sender implemented for EMAIL_PROVIDER={settings.email_provider!r} yet — "
        "add one to app/core/email.py."
    )


def _send_email_smtp(
    to: str,
    subject: str,
    body_text: str,
    html_body: str | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    from_name: str | None = None,
) -> None:
    """Sends via Gmail SMTP. Same contract as send_email above — not meant
    to be called directly except through get_email_sender/send_email.
    """
    if not settings.smtp_username or not settings.smtp_app_password:
        raise AppError(
            "Email sending is not configured — set SMTP_USERNAME and SMTP_APP_PASSWORD to send emails."
        )

    message = MIMEMultipart("mixed")
    message["From"] = f"{from_name or settings.smtp_from_name} <{settings.smtp_username}>"
    message["To"] = to
    message["Subject"] = subject

    if html_body is not None:
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(body_text, "plain"))
        body.attach(MIMEText(html_body, "html"))
        message.attach(body)
    else:
        message.attach(MIMEText(body_text, "plain"))

    if attachment_bytes is not None and attachment_filename is not None:
        attachment = MIMEApplication(attachment_bytes, _subtype=_XLSX_CONTENT_SUBTYPE)
        attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
        message.attach(attachment)

    # Never log the message object or its headers/body here — From/Subject
    # are harmless but this is the one call site that ever touches
    # smtp_app_password, so it stays out of every log line on principle.
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_app_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        logger.exception("SMTP authentication failed while sending email to %s", to)
        raise EmailSendError(
            "Email login failed — the configured SMTP username/app password was rejected."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Failed to send email to %s", to)
        raise EmailSendError(f"Could not send the email: {exc}") from exc


def _send_email_resend(
    to: str,
    subject: str,
    body_text: str,
    html_body: str | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    from_name: str | None = None,
) -> None:
    """Sends via Resend's HTTP API (the official `resend` SDK). Same
    contract as send_email above — not meant to be called directly except
    through get_email_sender/send_email.

    Resend has no SMTP-style login step — resend.api_key is set fresh on
    every call (cheap, just a module attribute) rather than once at import
    time, so a key rotated in settings without a process restart still
    takes effect on the next send.

    `resend` is imported here, not at module level — this module is
    imported (via send_email) regardless of EMAIL_PROVIDER, and an
    unconditional top-level `import resend` would make the whole app fail to
    start in any environment that hasn't pip-installed it, even one that
    only ever uses EMAIL_PROVIDER=smtp. Same lazy principle as the config
    check just below.
    """
    if not settings.resend_api_key or not settings.resend_from_email:
        raise AppError(
            "Email sending is not configured — set RESEND_API_KEY and RESEND_FROM_EMAIL to send emails."
        )

    import resend

    resend.api_key = settings.resend_api_key

    params: resend.Emails.SendParams = {
        "from": f"{from_name or settings.smtp_from_name} <{settings.resend_from_email}>",
        "to": [to],
        "subject": subject,
        "text": body_text,
    }
    if html_body is not None:
        params["html"] = html_body
    if attachment_bytes is not None and attachment_filename is not None:
        # Resend wants attachment content as a list of raw bytes, not a
        # base64 string or the bytes object itself — see
        # https://resend.com/docs/send-with-python.
        params["attachments"] = [{"filename": attachment_filename, "content": list(attachment_bytes)}]

    # Never log `params` here — it carries the recipient/subject (harmless)
    # but this is the one call site that ever touches resend_api_key (set
    # as a module attribute just above), so the whole block stays out of
    # every log line on principle, same as the SMTP path above.
    try:
        result = resend.Emails.send(params)
        logger.info("Resend accepted email to %s (id=%s)", to, result.get("id") if isinstance(result, dict) else result)
    except resend.exceptions.InvalidApiKeyError as exc:
        logger.exception("Resend rejected the API key while sending email to %s", to)
        raise EmailSendError("Email login failed — the configured Resend API key was rejected.") from exc
    except resend.exceptions.ResendError as exc:
        logger.exception("Resend failed to send email to %s", to)
        raise EmailSendError(f"Could not send the email: {exc.message}") from exc
    except Exception as exc:
        # Catch-all: a network failure, a malformed response, or anything
        # else the SDK doesn't wrap in its own ResendError hierarchy still
        # becomes a clean EmailSendError rather than an unhandled 500 — same
        # "never a silent failure or unhandled crash" rule as the rest of
        # this module.
        logger.exception("Unexpected error sending email via Resend to %s", to)
        raise EmailSendError(f"Could not send the email: {exc}") from exc
