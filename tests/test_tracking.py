"""Secure tracking without login + data isolation + status history tests."""
from io import BytesIO

from app.extensions import db
from app.models import Order, StatusHistory, UploadedDocument
from .conftest import add_to_cart, fill_valid_form, png_bytes


def _create_order(client, service, mobile):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    resp = client.post("/checkout", data={
        "name": "Tracker", "mobile": mobile, "consent": "1", "checkout_token": token,
    }, follow_redirects=False)
    order = Order.query.order_by(Order.id.desc()).first()
    location = resp.headers["Location"]
    from urllib.parse import urlparse, parse_qs
    tracking_token = parse_qs(urlparse(location).query)["token"][0]
    return order, tracking_token


def test_track_with_token(client, service):
    order, token = _create_order(client, service, "9200000001")
    resp = client.post("/track", data={"order_number": order.order_number, "token": token})
    page = resp.get_data(as_text=True)
    assert order.order_number in page
    assert "Ramesh" not in page  # form data (PII) not exposed on tracking


def test_track_with_pin(client, service):
    order, token = _create_order(client, service, "9200000002")
    # PIN was displayed at confirmation; simulate knowing it via hash lookup is
    # impossible by design - so we test that the PIN shown at confirmation works.
    with client.session_transaction() as sess:
        pin = sess.get(f"_pin_{order.order_number}")
    assert pin and len(pin) == 6
    resp = client.post("/track", data={"order_number": order.order_number, "token": pin})
    assert order.order_number in resp.get_data(as_text=True)


def test_track_rejects_wrong_token(client, service):
    order, _ = _create_order(client, service, "9200000003")
    resp = client.post("/track", data={"order_number": order.order_number,
                                       "token": "wrong-token"})
    page = resp.get_data(as_text=True)
    assert "Invalid" in page or "गलत" in page


def test_customer_data_isolation(client, service):
    order_a, token_a = _create_order(client, service, "9200000004")
    order_b, token_b = _create_order(client, service, "9200000005")
    # B's token cannot open A's order
    resp = client.post("/track", data={"order_number": order_a.order_number,
                                       "token": token_b})
    assert "Invalid" in resp.get_data(as_text=True) or "गलत" in resp.get_data(as_text=True)


def test_tracking_token_hashed_in_db(client, service):
    order, token = _create_order(client, service, "9200000006")
    assert order.tracking_token_hash != token
    assert len(order.tracking_token_hash) == 64  # sha256 hex


def test_internal_notes_hidden_on_tracking(client, service):
    order, token = _create_order(client, service, "9200000007")
    # simulate an internal-only history entry
    db.session.add(StatusHistory(
        entity_type="order", order_id=order.id, previous_status="submitted",
        new_status="submitted", visible_to_customer=False,
        internal_note="Customer sounded suspicious - double check documents",
    ))
    db.session.commit()
    resp = client.post("/track", data={"order_number": order.order_number, "token": token})
    page = resp.get_data(as_text=True)
    assert "suspicious" not in page


def test_customer_remark_visible_on_tracking(client, service):
    order, token = _create_order(client, service, "9200000008")
    db.session.add(StatusHistory(
        entity_type="order", order_id=order.id, previous_status=None,
        new_status="submitted", visible_to_customer=True,
        customer_remark="Thank you for your order",
    ))
    db.session.commit()
    resp = client.post("/track", data={"order_number": order.order_number, "token": token})
    assert "Thank you for your order" in resp.get_data(as_text=True)


def test_output_document_download_requires_token(client, service):
    order, token = _create_order(client, service, "9200000009")
    doc = UploadedDocument(
        order_id=order.id, doc_purpose="output_document",
        label_snapshot="Completed Certificate", original_name="certificate.pdf",
        stored_name="out.pdf", mime_type="application/pdf", size_bytes=100,
        upload_status="uploaded", storage_provider="local", is_private=True,
    )
    db.session.add(doc)
    db.session.commit()
    import os
    # give the local adapter a real file
    local_path = os.path.join(doc.stored_name)
    with open(local_path, "wb") as fh:
        fh.write(b"%PDF-1.4 test")
    doc.drive_file_id = os.path.abspath(local_path)
    db.session.commit()

    resp = client.get(f"/order/{order.order_number}/document/{doc.id}?token={token}")
    assert resp.status_code == 200
    # wrong token fails
    resp = client.get(f"/order/{order.order_number}/document/{doc.id}?token=bad")
    assert resp.status_code == 404
    # payment proofs are NEVER downloadable through tracking
    proof = UploadedDocument(
        order_id=order.id, doc_purpose="payment_proof",
        label_snapshot="Payment Screenshot", original_name="proof.png",
        stored_name="proof.png", mime_type="image/png", size_bytes=10,
        upload_status="uploaded", storage_provider="local", is_private=True,
    )
    db.session.add(proof)
    db.session.commit()
    resp = client.get(f"/order/{order.order_number}/document/{proof.id}?token={token}")
    assert resp.status_code == 404
    os.remove(local_path)


def test_independent_application_status_updates(admin_client, client, service):
    """Two applications in one order are managed independently."""
    from app.models import Application
    key1 = add_to_cart(client, service.id)
    key2 = add_to_cart(client, service.id)
    fill_valid_form(client, key1, service)
    fill_valid_form(client, key2, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    client.post("/checkout", data={"name": "Indep", "mobile": "9300000001",
                                   "consent": "1", "checkout_token": token},
                follow_redirects=False)
    order = Order.query.order_by(Order.id.desc()).first()
    app1, app2 = order.applications[0], order.applications[1]

    resp = admin_client.post(f"/admin/applications/{app1.id}/status", data={
        "status": "under_processing", "customer_remark": "Documents verified",
    }, follow_redirects=True)
    db.session.refresh(app1)
    db.session.refresh(app2)
    assert app1.status == "under_processing"
    assert app2.status == "submitted"  # untouched

    # history record created with previous status + admin identity
    hist = (StatusHistory.query.filter_by(application_id=app1.id, entity_type="application")
            .order_by(StatusHistory.id.desc()).first())
    assert hist.previous_status == "submitted"
    assert hist.new_status == "under_processing"
    assert hist.updated_by_admin_id is not None
    assert hist.customer_remark == "Documents verified"

    # mark both completed -> order auto-completes
    admin_client.post(f"/admin/applications/{app1.id}/status",
                      data={"status": "completed"}, follow_redirects=True)
    admin_client.post(f"/admin/applications/{app2.id}/status",
                      data={"status": "completed"}, follow_redirects=True)
    db.session.refresh(order)
    assert order.status == "completed"
