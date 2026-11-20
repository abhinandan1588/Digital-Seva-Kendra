"""Tests for bulk import/export, pricing snapshots, historical-order safety."""
import io

import pytest

from app.extensions import db
from app.models import Service, ServiceCategory, Order


CSV_GOOD = """service_name,hindi_name,category,subcategory,description,service_charge,official_fee,processing_time,official_url,capability_type,active_status
Import New Service,आयात सेवा,Test Category,,Imported description,120,0,3-5 days,https://example.gov.in,assisted_application,active
Import Update Service,अपडेट सेवा,Test Category,,Updated description,90,10,1-2 days,,internal_service,active
"""

CSV_BAD = """service_name,hindi_name,category,subcategory,description,service_charge,official_fee,processing_time,official_url,capability_type,active_status
Bad Category Service,बैड,Nonexistent Category,,desc,100,0,1 day,,assisted_application,active
Bad Capability Service,बैड2,Test Category,,desc,100,0,1 day,,bogus_capability,active
Bad Price Service,बैड3,Test Category,,desc,abc,0,1 day,,assisted_application,active
Bad URL Service,बैड4,Test Category,,desc,100,0,1 day,ftp://bad,assisted_application,active
"""

CSV_GOOD_HEADER, CSV_BAD_BODY = CSV_BAD.split("\n", 1)


CSV_BAD_HEADER, CSV_BAD_BODY = CSV_BAD.split("\n", 1)


@pytest.fixture
def update_target(category):
    svc = Service(category=category, slug="import-update-service",
                  name_en="Import Update Service", service_charge=100,
                  official_fee=0, is_active=True)
    db.session.add(svc)
    db.session.commit()
    return svc


def _upload(client, endpoint, content, filename="services.csv"):
    data = {"file": (io.BytesIO(content.encode("utf-8")), filename)}
    return client.post(endpoint, data=data, content_type="multipart/form-data",
                       follow_redirects=True)


def test_import_preview_validates_rows(admin_client, category):
    _upload(admin_client, "/admin/catalogue/import/preview",
            CSV_GOOD + CSV_BAD_BODY)
    rows = None
    with admin_client.session_transaction() as sess:
        rows = sess.get("dsk_import_rows", [])
    assert len(rows) == 6
    errors = {r["line"]: r["errors"] for r in rows if r["errors"]}
    assert len(errors) == 4
    # invalid category / capability / price / URL rows all flagged
    assert any("invalid category" in " ".join(e) for e in errors.values())
    assert any("invalid capability_type" in " ".join(e) for e in errors.values())
    assert any("invalid pricing" in " ".join(e) for e in errors.values())
    assert any("official_url" in " ".join(e) for e in errors.values())


def test_import_apply_creates_and_updates(admin_client, category, update_target):
    before_charge = update_target.service_charge
    _upload(admin_client, "/admin/catalogue/import/preview", CSV_GOOD)
    resp = admin_client.post("/admin/catalogue/import/apply",
                             data={"confirm": "y"}, follow_redirects=True)
    created = Service.query.filter_by(slug="import-new-service").first()
    assert created is not None
    assert created.name_hi == "आयात सेवा"
    assert created.capability_type == "assisted_application"
    db.session.refresh(update_target)
    assert update_target.service_charge == 90
    assert update_target.official_fee == 10
    assert str(before_charge) == "100.00"


def test_import_without_confirmation_does_nothing(admin_client, category):
    _upload(admin_client, "/admin/catalogue/import/preview", CSV_GOOD)
    resp = admin_client.post("/admin/catalogue/import/apply",
                             data={}, follow_redirects=True)
    assert Service.query.filter_by(slug="import-new-service").first() is None


def test_import_duplicate_in_file_flagged(admin_client, category):
    csv_dup = (CSV_GOOD +
               "Import New Service,आयात सेवा 2,Test Category,,dup,50,0,,,,\n")
    _upload(admin_client, "/admin/catalogue/import/preview", csv_dup)
    with admin_client.session_transaction() as sess:
        rows = sess.get("dsk_import_rows", [])
    dup_errors = [r["errors"] for r in rows if "duplicate" in " ".join(r["errors"])]
    assert dup_errors


def test_export_csv_and_json(admin_client, category):
    svc = Service(category=category, slug="export-svc", name_en="Export Svc",
                  name_hi="निर्यात", service_charge=55, official_fee=0, is_active=True)
    db.session.add(svc)
    db.session.commit()
    csv_resp = admin_client.get("/admin/catalogue/export.csv")
    assert csv_resp.status_code == 200
    assert b"Export Svc" in csv_resp.data
    json_resp = admin_client.get("/admin/catalogue/export.json")
    assert json_resp.status_code == 200
    assert b"Export Svc" in json_resp.data
    assert b"service_charge" in json_resp.data


def test_sample_csv_downloadable(admin_client):
    resp = admin_client.get("/admin/catalogue/import/sample.csv")
    assert resp.status_code == 200
    assert b"service_name" in resp.data
    assert b"hindi_name" in resp.data


def test_price_change_never_alters_historical_orders(client, category):
    """Part 8: pricing snapshots in every order stay intact."""
    svc = Service(category=category, slug="price-svc", name_en="Price Svc",
                  service_charge=100, official_fee=50, is_active=True)
    db.session.add(svc)
    db.session.commit()
    client.post(f"/cart/add/{svc.id}")
    with client.session_transaction() as sess:
        key = sess.get("dsk_cart", [])[-1]["key"]
    client.post(f"/apply/{key}", data={"applicant_name": "X", "mobile": "9876543210"})
    client.post("/checkout", data={"name": "Buyer", "mobile": "9876543210",
                                   "consent": "y"})
    order = Order.query.order_by(Order.id.desc()).first()
    assert float(order.total_amount) == 150.0
    # admin raises the prices afterwards
    svc.service_charge = 200
    svc.official_fee = 100
    db.session.commit()
    db.session.refresh(order)
    assert float(order.total_amount) == 150.0
    item = order.items[0]
    assert float(item.service_charge_snapshot) == 100.0
    assert float(item.official_fee_snapshot) == 50.0


def test_pricing_page_and_inline_update(admin_client, category):
    svc = Service(category=category, slug="pricing-svc", name_en="Pricing Svc",
                  service_charge=10, official_fee=0, is_active=True)
    db.session.add(svc)
    db.session.commit()
    assert admin_client.get("/admin/services/pricing").status_code == 200
    admin_client.post(f"/admin/services/{svc.id}/pricing",
                      data={"service_charge": "75", "official_fee": "25", "other_charge": "5"})
    db.session.refresh(svc)
    assert float(svc.service_charge) == 75 and float(svc.official_fee) == 25


def test_availability_page_and_capability_update(admin_client, category):
    svc = Service(category=category, slug="avail-svc", name_en="Avail Svc",
                  service_charge=10, is_active=True)
    db.session.add(svc)
    db.session.commit()
    assert admin_client.get("/admin/services/availability").status_code == 200
    admin_client.post(f"/admin/services/{svc.id}/capability",
                      data={"capability_type": "restricted_authorization_required"})
    db.session.refresh(svc)
    assert svc.is_restricted is True


def test_service_archive_keeps_orders(admin_client, client, category):
    svc = Service(category=category, slug="archive-svc", name_en="Archive Svc",
                  service_charge=10, is_active=True)
    db.session.add(svc)
    db.session.commit()
    client.post(f"/cart/add/{svc.id}")
    with client.session_transaction() as sess:
        key = sess.get("dsk_cart", [])[-1]["key"]
    client.post(f"/apply/{key}", data={"applicant_name": "X", "mobile": "9876543210"})
    client.post("/checkout", data={"name": "Buyer", "mobile": "9876543210", "consent": "y"})
    order = Order.query.order_by(Order.id.desc()).first()
    admin_client.post(f"/admin/services/{svc.id}/archive")
    db.session.refresh(svc)
    assert svc.is_archived is True and svc.is_active is False
    # historical order + snapshot remain untouched
    db.session.refresh(order)
    assert order.items[0].service_slug_snapshot == "archive-svc"
    assert order.service_names_snapshot == "Archive Svc"


def test_service_duplicate_as_template(admin_client, category):
    svc = Service(category=category, slug="dup-src", name_en="Dup Source",
                  service_charge=60, is_active=True)
    db.session.add(svc)
    db.session.commit()
    admin_client.post(f"/admin/services/{svc.id}/duplicate")
    copy = Service.query.filter_by(slug="dup-src-copy").first()
    assert copy is not None
    assert copy.is_active is False  # review before publishing
    assert copy.name_en.startswith("Dup Source (Copy)")
