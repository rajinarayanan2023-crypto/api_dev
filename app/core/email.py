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
    attachment, via Gmail SMTP.

    - html_body is optional — omit it for plain-text-only (the audit report
      email); pass it alongside body_text for a rich version (the OTP email's
      colorful template) — mail clients that render HTML show html_body,
      everything else falls back to body_text.
    - attachment_bytes/attachment_filename are optional and independent of
      html_body — pass both together for an attachment (the audit .xlsx).
    - from_name overrides the display name in the From header for this one
      email (e.g. "GM Agency App OTP" for login codes) — defaults to
      settings.smtp_from_name (used for audit report emails) when omitted.

    Raises AppError (config missing) or EmailSendError (the send itself
    failed) rather than ever returning a fake success — the caller must not
    catch these and report success anyway.
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
