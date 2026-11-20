"""Payment QR generation, proof submission, and manual verification tests."""
import re
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.models import Order, Payment, UploadedDocument
from .conftest import add_to_cart, fill_valid_form, png_bytes


def _make_paid_flow(client, service, mobile_suffix="1"):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    resp = client.post("/checkout", data={
        "name": "Pay Test", "mobile": f"91000000{mobile_suffix}", "consent": "1",
        "checkout_token": token,
    }, follow_redirects=False)
    order = Order.query.order_by(Order.id.desc()).first()
    # extract the tracking token from the confirmation redirect URL
    location = resp.headers["Location"]
    tracking_token = parse_qs(urlparse(location).query)["token"][0]
    return order, tracking_token


def test_upi_intent_format(app, client, service):
    from app.utils.payments import build_upi_intent
    intent = build_upi_intent(390.5, "shop@upi", "Test Shop", "DSK-2026-000001")
    assert intent.startswith("upi://pay?")
    qs = parse_qs(urlparse(intent).query)
    assert qs["pa"] == ["shop@upi"]
    assert qs["pn"] == ["Test Shop"]
    assert qs["am"] == ["390.50"]
    assert qs["cu"] == ["INR"]
    assert qs["tr"] == ["DSK-2026-000001"]


def test_qr_image_rendered_for_order(client, service, app):
    order, token = _make_paid_flow(client, service, "10")
    resp = client.get(f"/pay/{order.order_number}/qr.png?token={token}")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_pay_page_shows_amount_and_upi(client, service):
    order, token = _make_paid_flow(client, service, "11")
    resp = client.get(f"/pay/{order.order_number}?token={token}")
    page = resp.get_data(as_text=True)
    assert order.order_number in page
    assert "260.00" in page
    assert "shop@upi" in page


def test_qr_denied_without_valid_token(client, service):
    order, _ = _make_paid_flow(client, service, "12")
    resp = client.get(f"/pay/{order.order_number}/qr.png?token=WRONG")
    assert resp.status_code == 404


def test_proof_submission_moves_to_pending_verification(client, service):
    order, token = _make_paid_flow(client, service, "13")
    resp = client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "123456789012",
        "screenshot": (BytesIO(png_bytes()), "payment.png"),
    }, content_type="multipart/form-data", follow_redirects=True)
    page = resp.get_data(as_text=True)
    payment = Payment.query.filter_by(order_id=order.id).first()
    assert payment.status == "pending_verification"
    assert payment.upi_transaction_id == "123456789012"
    assert order.payment_status == "pending_verification"
    assert payment.screenshot is not None
    assert "submitted" in page or "जमा" in page


def test_proof_rejected_without_screenshot(client, service):
    order, token = _make_paid_flow(client, service, "14")
    resp = client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "123456789012",
    }, follow_redirects=True)
    payment = Payment.query.filter_by(order_id=order.id).first()
    assert payment.status == "awaiting_payment"


def test_screenshot_never_auto_verifies(client, service):
    order, token = _make_paid_flow(client, service, "15")
    client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "999999999999",
        "screenshot": (BytesIO(png_bytes()), "proof.png"),
    }, content_type="multipart/form-data")
    payment = Payment.query.filter_by(order_id=order.id).first()
    assert payment.status != "verified"  # manual verification only


def test_admin_approve_payment_flow(admin_client, client, service):
    order, token = _make_paid_flow(client, service, "16")
    client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "777777777777",
        "screenshot": (BytesIO(png_bytes()), "p.png"),
    }, content_type="multipart/form-data")
    payment = Payment.query.filter_by(order_id=order.id).first()

    resp = admin_client.post(f"/admin/payments/{payment.id}/approve", follow_redirects=True)
    db.session.refresh(payment)
    db.session.refresh(order)
    assert payment.status == "verified"
    assert payment.verified_by_admin_id is not None
    assert payment.verified_at is not None
    assert order.payment_status == "verified"
    assert order.status == "confirmed"
    for app_rec in order.applications:
        assert app_rec.status == "payment_verified"


def test_admin_reject_requires_reason(admin_client, client, service):
    order, token = _make_paid_flow(client, service, "17")
    client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "555555555555",
        "screenshot": (BytesIO(png_bytes()), "p.png"),
    }, content_type="multipart/form-data")
    payment = Payment.query.filter_by(order_id=order.id).first()

    resp = admin_client.post(f"/admin/payments/{payment.id}/reject", data={},
                             follow_redirects=True)
    page = resp.get_data(as_text=True)
    db.session.refresh(payment)
    assert payment.status != "rejected"  # reason mandatory
    assert "reason is mandatory" in page

    resp = admin_client.post(f"/admin/payments/{payment.id}/reject",
                             data={"reason": "Amount mismatch in screenshot"},
                             follow_redirects=True)
    db.session.refresh(payment)
    db.session.refresh(order)
    assert payment.status == "rejected"
    assert payment.rejection_reason == "Amount mismatch in screenshot"
    assert order.payment_status == "rejected"
    # customer can resubmit after rejection
    resp = client.post(f"/pay/{order.order_number}/submit", data={
        "token": token, "utr": "555555555556",
        "screenshot": (BytesIO(png_bytes()), "p2.png"),
    }, content_type="multipart/form-data")
    db.session.refresh(payment)
    assert payment.status == "pending_verification"
    assert payment.upi_transaction_id == "555555555556"
