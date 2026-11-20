"""Checkout, pricing, multi-service orders and duplicate prevention tests."""
from io import BytesIO

from app.extensions import db
from app.models import Order, OrderItem, Application, ApplicationFieldValue, Payment
from .conftest import add_to_cart, fill_valid_form, png_bytes


def _checkout(client, name="Test Customer", mobile="9000000001", token_header=None):
    with client.session_transaction() as sess:
        token = sess.get("checkout_token") or ""
    return client.post("/checkout", data={
        "name": name, "mobile": mobile, "consent": "1", "checkout_token": token,
    }, follow_redirects=False)


def test_full_flow_multiple_services(client, service, service_b):
    """Two services -> one order with two independent applications."""
    key_a = add_to_cart(client, service.id)
    key_b = add_to_cart(client, service_b.id)
    fill_valid_form(client, key_a, service)
    fill_valid_form(client, key_b, service_b)

    resp = _checkout(client)
    assert resp.status_code == 302 and "/confirmation" in resp.headers["Location"]

    order = Order.query.order_by(Order.id.desc()).first()
    assert order.order_number.startswith("DSK-")
    assert len(order.items) == 2
    assert len(order.applications) == 2
    # 150+110 + 100+30 = 390
    assert float(order.total_amount) == 390.0
    assert float(order.service_charges_total) == 250.0
    assert float(order.official_fees_total) == 140.0
    payment = Payment.query.filter_by(order_id=order.id).first()
    assert payment and float(payment.amount_expected) == 390.0
    # each application has its own form values
    for app in order.applications:
        values = ApplicationFieldValue.query.filter_by(application_id=app.id).all()
        assert len(values) == 3
    # documents uploaded through the local fallback provider
    from app.models import UploadedDocument
    docs = UploadedDocument.query.filter_by(order_id=order.id).all()
    assert len(docs) == 2
    assert all(d.upload_status == "uploaded" for d in docs)


def test_same_service_twice_two_applications(client, service):
    key1 = add_to_cart(client, service.id)
    key2 = add_to_cart(client, service.id)
    fill_valid_form(client, key1, service)
    # second applicant has a different name
    client.post(f"/apply/{key2}", data={
        "full_name": "Second Applicant", "mobile": "9876500000", "gender": "Female",
        "req_1": (BytesIO(png_bytes()), "b.png"),
    }, content_type="multipart/form-data", follow_redirects=True)
    resp = _checkout(client, mobile="9000000002")
    assert resp.status_code == 302
    order = Order.query.order_by(Order.id.desc()).first()
    assert len(order.applications) == 2
    names = {v.value_text for app in order.applications
             for v in ApplicationFieldValue.query.filter_by(
                 application_id=app.id, field_key="full_name")}
    assert names == {"Ramesh Kumar", "Second Applicant"}


def test_price_snapshot_protected_from_later_price_change(client, service):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    _checkout(client, mobile="9000000003")

    order = Order.query.order_by(Order.id.desc()).first()
    before = float(order.total_amount)
    # admin changes the service price AFTER the order
    service.service_charge = "999"
    db.session.commit()
    assert float(order.total_amount) == before
    assert float(order.items[0].service_charge_snapshot) == 150.0
    service.service_charge = "150"
    db.session.commit()


def test_server_side_pricing_not_from_client(client, service):
    """Even if a browser tampered with prices, totals come from the DB."""
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    client.post("/checkout", data={
        "name": "Cheater", "mobile": "9000000004", "consent": "1",
        "checkout_token": token,
        # injected fields a malicious client might add
        "total_amount": "1", "service_charge": "0",
    }, follow_redirects=False)
    order = Order.query.order_by(Order.id.desc()).first()
    assert float(order.total_amount) == 260.0  # real DB price, not 1


def test_duplicate_submit_creates_single_order(client, service):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    data = {"name": "Doubler", "mobile": "9000000005", "consent": "1",
            "checkout_token": token}
    resp1 = client.post("/checkout", data=data, follow_redirects=False)
    resp2 = client.post("/checkout", data=data, follow_redirects=False)
    assert resp1.status_code == 302
    assert resp2.status_code == 302  # redirected, not a crash
    count = Order.query.filter_by(customer_id=Order.query.order_by(
        Order.id.desc()).first().customer_id).count()
    assert count == 1  # only one order created


def test_missing_form_blocks_checkout(client, service):
    add_to_cart(client, service.id)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    resp = client.post("/checkout", data={
        "name": "Lazy", "mobile": "9000000006", "consent": "1", "checkout_token": token,
    })
    assert resp.status_code == 302  # bounced back to cart
    assert Order.query.count() == 0


def test_consent_required(client, service):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    resp = client.post("/checkout", data={
        "name": "NoConsent", "mobile": "9000000007", "checkout_token": token,
    })
    assert resp.status_code == 302
    assert Order.query.count() == 0


def test_order_number_sequence_format(client, service):
    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    _checkout(client, mobile="9000000008")
    order = Order.query.order_by(Order.id.desc()).first()
    parts = order.order_number.split("-")
    assert len(parts) == 3 and parts[0] == "DSK" and parts[2].isdigit()
