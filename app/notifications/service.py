"""Notification service.

Creates an in-app notification record for every customer-visible event and
attempts real delivery through configured providers (WhatsApp/SMS/email).
If no provider is configured, delivery_status is 'skipped' - the system
never claims a message was sent when it was not.
"""
from datetime import datetime, timezone

from flask import current_app

from ..extensions import db
from ..models import Notification


def notify_customer(order, event_type: str, title_en: str, title_hi: str,
                    message_en: str = "", message_hi: str = "",
                    application=None, extra_channels: bool = True) -> Notification:
    """Record + attempt delivery. Safe to call within any request context."""
    notification = Notification(
        order_id=order.id if order else None,
        application_id=application.id if application else None,
        customer_id=order.customer_id if order else None,
        event_type=event_type,
        channel="inapp",
        recipient_mobile=order.customer.mobile if order and order.customer else None,
        recipient_email=order.customer.email if order and order.customer else None,
        title_en=title_en,
        title_hi=title_hi,
        message_en=message_en,
        message_hi=message_hi,
        visible_to_customer=True,
    )
    db.session.add(notification)

    if extra_channels:
        _attempt_external_delivery(notification)

    db.session.commit()
    return notification


def _attempt_external_delivery(notification: Notification) -> None:
    """Try each configured provider adapter. Honest status handling only."""
    adapters = []

    if current_app.config.get("WHATSAPP_PROVIDER_URL"):
        adapters.append(("whatsapp", _send_whatsapp))
    if current_app.config.get("SMS_PROVIDER_URL"):
        adapters.append(("sms", _send_sms))
    if current_app.config.get("SMTP_HOST") and notification.recipient_email:
        adapters.append(("email", _send_email))

    if not adapters:
        notification.delivery_status = "skipped"
        notification.provider_name = "none"
        notification.provider_error = "No external provider configured (v1: in-app tracking updates only)"
        return

    # Primary channel attempt (first configured)
    channel, sender = adapters[0]
    notification.channel = channel
    try:
        ok = sender(notification)
        notification.delivery_status = "sent" if ok else "failed"
        notification.provider_name = channel
        notification.sent_at = datetime.now(timezone.utc) if ok else None
    except Exception as exc:  # provider failure must never break checkout
        notification.delivery_status = "failed"
        notification.provider_name = channel
        notification.provider_error = str(exc)[:300]
        current_app.logger.warning("Notification provider failed: %s", type(exc).__name__)


def _render_message(notification: Notification, lang: str = "en") -> tuple[str, str]:
    title = notification.title_en if lang == "en" else (notification.title_hi or notification.title_en)
    message = notification.message_en if lang == "en" else (notification.message_hi or notification.message_en)
    return title, message


def _send_whatsapp(notification: Notification) -> bool:
    """Generic WhatsApp Business API adapter (Meta Cloud API compatible).

    Requires WHATSAPP_PROVIDER_URL and WHATSAPP_PROVIDER_KEY. The provider
    URL can be pointed at any HTTP-compatible gateway.
    """
    import requests  # local import: only needed when a provider is configured

    url = current_app.config["WHATSAPP_PROVIDER_URL"]
    key = current_app.config["WHATSAPP_PROVIDER_KEY"]
    title, message = _render_message(notification)
    resp = requests.post(url, json={
        "to": notification.recipient_mobile,
        "type": "text",
        "text": {"body": f"{title}\n{message}"},
    }, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    return 200 <= resp.status_code < 300


def _send_sms(notification: Notification) -> bool:
    """Generic HTTP SMS adapter; adapt the payload to your SMS gateway."""
    import requests

    url = current_app.config["SMS_PROVIDER_URL"]
    key = current_app.config["SMS_PROVIDER_KEY"]
    title, message = _render_message(notification, lang="hi")
    resp = requests.post(url, json={
        "to": notification.recipient_mobile,
        "message": f"{title}\n{message}",
    }, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    return 200 <= resp.status_code < 300


def _send_email(notification: Notification) -> bool:
    """SMTP email adapter using the standard library (no extra dependency)."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    cfg = current_app.config
    title, message = _render_message(notification)
    msg = MIMEMultipart()
    msg["From"] = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER") or "dsk@localhost"
    msg["To"] = notification.recipient_email
    msg["Subject"] = title
    msg.attach(MIMEText(message, "plain", "utf-8"))
    with smtplib.SMTP(cfg.get("SMTP_HOST"), cfg.get("SMTP_PORT") or 587, timeout=10) as smtp:
        smtp.starttls()
        if cfg.get("SMTP_USER"):
            smtp.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD") or "")
        smtp.send_message(msg)
    return True


# --- Event helpers used across the app ------------------------------------

def event_order_submitted(order, order_number, token) -> Notification:
    return notify_customer(
        order, "order_submitted",
        title_en=f"Order {order_number} submitted successfully",
        title_hi=f"ऑर्डर {order_number} सफलतापूर्वक जमा हुआ",
        message_en="Please complete the payment to start processing.",
        message_hi="प्रक्रिया शुरू करने के लिए कृपया भुगतान पूरा करें।",
    )


def event_payment_proof_received(order) -> Notification:
    return notify_customer(
        order, "payment_proof_received",
        title_en="Payment proof received - verification pending",
        title_hi="भुगतान प्रमाण प्राप्त - सत्यापन लंबित",
    )


def event_payment_verified(order) -> Notification:
    return notify_customer(
        order, "payment_verified",
        title_en="Payment verified - processing will start",
        title_hi="भुगतान सत्यापित - प्रक्रिया शुरू होगी",
    )


def event_payment_rejected(order, reason: str) -> Notification:
    return notify_customer(
        order, "payment_rejected",
        title_en="Payment could not be verified",
        title_hi="भुगतान सत्यापित नहीं हो सका",
        message_en=f"Reason: {reason}",
        message_hi=f"कारण: {reason}",
    )


def event_application_status(order, application, new_status: str, remark: str = "") -> Notification:
    from ..models.order import APPLICATION_STATUS_LABELS
    pair = APPLICATION_STATUS_LABELS.get(new_status, (new_status, new_status))
    return notify_customer(
        order, f"application_{new_status}",
        title_en=f"Application {application.application_number}: {pair[0]}",
        title_hi=f"आवेदन {application.application_number}: {pair[1]}",
        message_en=remark or "",
        message_hi=remark or "",
        application=application,
    )


def event_documents_required(order, application, detail: str) -> Notification:
    return notify_customer(
        order, "documents_required",
        title_en=f"Additional documents required for {application.application_number}",
        title_hi=f"{application.application_number} के लिए अतिरिक्त दस्तावेज़ आवश्यक",
        message_en=detail,
        message_hi=detail,
        application=application,
    )
