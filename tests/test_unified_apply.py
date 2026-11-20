"""Unified application flow: common details, document wallet, storage dedupe."""
import io
import os
import shutil

from app.extensions import db
from app.models import Service, ServiceDocumentRequirement, UploadedDocument
from .conftest import png_bytes, fake_pdf_bytes


# --- helpers -----------------------------------------------------------------

def save_common(client, **overrides):
    payload = {
        "profile": {
            "name": "Ramesh Kumar", "mobile": "9876543210",
            "email": "ramesh@example.com", "address": "Main Bazar, Sitapur",
        },
        "answers": {"full_name": "Ramesh Kumar", "mobile": "9876543210"},
    }
    payload.update(overrides)
    return client.post("/api/apply/common", json=payload)


def upload_wallet_png(client, name="aadhaar.png"):
    return client.post("/api/apply/common",
                       data={"wallet_files": (io.BytesIO(png_bytes()), name)},
                       content_type="multipart/form-data")


def wallet_entries(client):
    resp = client.get("/api/apply/common").get_json()
    return resp["wallet"]


def add_to_cart_api(client, service_id):
    client.post("/api/cart/add", json={"service_id": service_id})
    with client.session_transaction() as sess:
        return sess["dsk_cart"][-1]["key"]


def make_pdf_only_service(app, category, slug="pdf-only"):
    svc = Service(category=category, slug=slug, name_en=f"Service {slug}",
                  name_hi="सेवा", service_charge="100", official_fee="0", is_active=True)
    db.session.add(svc)
    db.session.flush()
    db.session.add(ServiceDocumentRequirement(
        service=svc, label_en="Signed PDF", label_hi="हस्ताक्षरित PDF",
        allowed_extensions=["pdf"], max_file_mb=2, is_required=True, sort_order=1))
    db.session.commit()
    return svc


# --- common details ------------------------------------------------------------

def test_common_profile_validation(client):
    resp = save_common(client, profile={"name": "A", "mobile": "abc"})
    assert resp.status_code == 422
    assert resp.get_json()["errors"]["mobile"] == "invalid_mobile"


def test_common_profile_saved(client):
    resp = save_common(client)
    assert resp.status_code == 200
    data = client.get("/api/apply/common").get_json()
    assert data["profile"]["name"] == "Ramesh Kumar"
    assert data["profile"]["mobile"] == "9876543210"
    assert data["answers"]["full_name"]["value_text"] == "Ramesh Kumar"


def test_overview_prefills_answers_across_services(client, service, service_b):
    save_common(client)
    add_to_cart_api(client, service.id)
    add_to_cart_api(client, service_b.id)
    data = client.get("/api/apply/overview").get_json()
    assert len(data["items"]) == 2
    for item in data["items"]:
        full_name = next(f for f in item["form_fields"] if f["field_key"] == "full_name")
        assert full_name["prefill"] == "Ramesh Kumar"


# --- wallet --------------------------------------------------------------------

def test_wallet_upload_dedupes_identical_content(client):
    resp = client.post("/api/apply/common", data={
        "wallet_files": [(io.BytesIO(png_bytes()), "one.png"),
                         (io.BytesIO(png_bytes()), "two.png")],
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    entries = resp.get_json()["wallet"]
    assert len(entries) == 1  # same content -> one entry, one stored file
    from app.utils.customer_common import wallet_dir
    mine = [f for f in os.listdir(wallet_dir()) if f.startswith(entries[0]["id"])]
    assert len(mine) == 1


def test_wallet_remove(client):
    upload_wallet_png(client)
    entry = wallet_entries(client)[0]
    from app.utils.customer_common import wallet_dir
    path = os.path.join(wallet_dir(), f"{entry['id']}.png")
    assert os.path.isfile(path)
    client.post("/api/wallet/remove", json={"id": entry["id"]})
    assert wallet_entries(client) == []
    assert not os.path.isfile(path)


def test_overview_suggests_matching_wallet_entry(client, service):
    upload_wallet_png(client, name="my_aadhaar_scan.png")
    add_to_cart_api(client, service.id)
    data = client.get("/api/apply/overview").get_json()
    item = data["items"][0]
    req = item["document_requirements"][0]
    wallet = data["common"]["wallet"]
    assert req["prefill_wallet_id"] == wallet[0]["id"]


# --- per-item forms with wallet references ---------------------------------------

def test_item_form_accepts_wallet_reference(client, service):
    upload_wallet_png(client)
    entry = wallet_entries(client)[0]
    item_key = add_to_cart_api(client, service.id)
    req = service.active_document_requirements[0]
    resp = client.post(f"/api/cart/{item_key}/form", data={
        "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
        f"req_{req.id}": f"wallet:{entry['id']}",
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    cart = client.get("/api/cart").get_json()
    assert cart["items"][0]["form_filled"] is True
    # the wallet file itself stays reusable (not consumed)
    assert len(wallet_entries(client)) == 1


def test_item_form_wallet_wrong_extension_rejected(client, app, category):
    svc = make_pdf_only_service(app, category)
    upload_wallet_png(client)
    entry = wallet_entries(client)[0]
    item_key = add_to_cart_api(client, svc.id)
    req = svc.active_document_requirements[0]
    resp = client.post(f"/api/cart/{item_key}/form", data={
        f"req_{req.id}": f"wallet:{entry['id']}",
    }, content_type="multipart/form-data")
    assert resp.status_code == 422
    assert resp.get_json()["errors"][f"req:{req.id}"] == "file_bad_type"


def test_item_form_missing_wallet_reference_rejected(client, service):
    item_key = add_to_cart_api(client, service.id)
    req = service.active_document_requirements[0]
    resp = client.post(f"/api/cart/{item_key}/form", data={
        "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
        f"req_{req.id}": "wallet:doesnotexist",
    }, content_type="multipart/form-data")
    assert resp.status_code == 422
    assert resp.get_json()["errors"][f"req:{req.id}"] == "wallet_missing"


# --- checkout: shared wallet file stored ONCE per order --------------------------

def _order_storage_files(app, order_number):
    """Files stored by the local provider for ONE order (folder per order)."""
    root = os.path.join(app.instance_path, "storage")
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if dirpath.rstrip(os.sep).endswith(order_number) or f"{os.sep}{order_number}{os.sep}" in dirpath:
            found.extend(os.path.join(dirpath, f) for f in filenames)
    return found


def _fill_and_checkout(client, services, app=None):
    if app is not None:
        # order numbers restart per test DB; clear leftover storage folders
        shutil.rmtree(os.path.join(app.instance_path, "storage"), ignore_errors=True)
    upload_wallet_png(client)
    entry = wallet_entries(client)[0]
    item_keys = []
    for svc in services:
        item_key = add_to_cart_api(client, svc.id)
        item_keys.append(item_key)
        req = svc.active_document_requirements[0]
        resp = client.post(f"/api/cart/{item_key}/form", data={
            "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
            f"req_{req.id}": f"wallet:{entry['id']}",
        }, content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_json()
    init = client.post("/api/checkout/init").get_json()
    resp = client.post("/api/checkout", json={
        "name": "Ramesh Kumar", "mobile": "9876543210", "email": "", "address": "",
        "consent": True, "checkout_token": init["checkout_token"],
    })
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["order_number"]


def test_checkout_stores_shared_wallet_file_once(client, app, service, service_b):
    order_number = _fill_and_checkout(client, [service, service_b], app)

    # two applications, two metadata rows, but ONE stored file
    docs = UploadedDocument.query.all()
    assert len(docs) == 2
    assert len({d.stored_name for d in docs}) == 1
    assert len({d.drive_file_id for d in docs}) == 1
    assert all(d.upload_status == "uploaded" for d in docs)
    assert {d.application_id for d in docs} and None not in {d.application_id for d in docs}

    # exactly one file in the local storage provider for this order
    stored_files = _order_storage_files(app, order_number)
    assert len(stored_files) == 1, stored_files

    # wallet file survives checkout (still reusable)
    assert len(wallet_entries(client)) == 1

    # admin per-application document view still sees both rows
    from app.models import Application
    apps = Application.query.all()
    assert len(apps) == 2
    assert order_number.startswith("DSK-")


def test_mixed_uploads_dedupe_by_content(client, app, service, service_b):
    """A file uploaded directly for one service and the same content from the
    wallet for another is stored once, too."""
    order_number = _fill_and_checkout_mixed(client, app, service, service_b)
    docs = UploadedDocument.query.all()
    assert len(docs) == 2
    assert len({d.drive_file_id for d in docs}) == 1
    stored_files = _order_storage_files(app, order_number)
    assert len(stored_files) == 1, stored_files


def _fill_and_checkout_mixed(client, app, service, service_b):
    shutil.rmtree(os.path.join(app.instance_path, "storage"), ignore_errors=True)
    upload_wallet_png(client)
    entry = wallet_entries(client)[0]
    key_a = add_to_cart_api(client, service.id)
    key_b = add_to_cart_api(client, service_b.id)
    req_a = service.active_document_requirements[0]
    req_b = service_b.active_document_requirements[0]
    r1 = client.post(f"/api/cart/{key_a}/form", data={
        "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
        f"req_{req_a.id}": (io.BytesIO(png_bytes()), "direct.png"),
    }, content_type="multipart/form-data")
    assert r1.status_code == 200
    r2 = client.post(f"/api/cart/{key_b}/form", data={
        "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
        f"req_{req_b.id}": f"wallet:{entry['id']}",
    }, content_type="multipart/form-data")
    assert r2.status_code == 200

    init = client.post("/api/checkout/init").get_json()
    resp = client.post("/api/checkout", json={
        "name": "Ramesh Kumar", "mobile": "9876543210", "email": "", "address": "",
        "consent": True, "checkout_token": init["checkout_token"],
    })
    assert resp.status_code == 200
    return resp.get_json()["order_number"]
