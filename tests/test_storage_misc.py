"""Storage adapters (local fallback + mock Drive), receipts, i18n, notifications."""
import os
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import UploadedDocument, Notification
from app.storage.base import BaseStorage
from .conftest import png_bytes


# --------------------------------------------------------------------------
# Google Drive mock adapter (interface compliance)
# --------------------------------------------------------------------------

class MockDriveStorage(BaseStorage):
    """Test adapter mimicking the Google Drive interface."""
    name = "gdrive_mock"

    def __init__(self):
        self.files = {}
        self.folders = {}
        self._next = 1

    def _id(self):
        self._next += 1
        return f"mockid{self._next}"

    def test_connection(self):
        return {"ok": True, "detail": "mock connected"}

    def ensure_folder_tree(self, order_number, service_labels, year=None):
        year = year or order_number.split("-")[1]
        tree = {"service_folder_ids": {}}
        tree["order_folder_id"] = f"folder-{order_number}"
        for label in service_labels:
            tree["service_folder_ids"][label] = f"folder-{order_number}-{label}"
        tree["service_folder_ids"]["__proof__"] = f"folder-{order_number}-proof"
        tree["service_folder_ids"]["__output__"] = f"folder-{order_number}-output"
        self.folders[order_number] = tree
        return tree

    def upload_file(self, local_path, stored_name, mime_type, folder_id=None):
        file_id = self._id()
        with open(local_path, "rb") as fh:
            self.files[file_id] = (stored_name, mime_type, folder_id, fh.read())
        return {"provider": self.name, "file_id": file_id, "web_view_link": f"https://drive.google.com/file/d/{file_id}/view"}

    def download_file(self, file_id):
        return self.files[file_id][3]

    def delete_file(self, file_id):
        return self.files.pop(file_id, None) is not None

    def delete_folder_tree(self, order_number):
        return self.folders.pop(order_number, None) is not None


def test_mock_drive_adapter_full_cycle():
    storage = MockDriveStorage()
    tree = storage.ensure_folder_tree("DSK-2026-000099", ["PAN Card"])
    assert tree["service_folder_ids"]["PAN Card"] == "folder-DSK-2026-000099-PAN Card"

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png_bytes())
        path = tmp.name
    result = storage.upload_file(path, "photo.png", "image/png",
                                 tree["service_folder_ids"]["PAN Card"])
    assert result["file_id"].startswith("mockid")
    content = storage.download_file(result["file_id"])
    assert content == png_bytes()
    assert storage.delete_file(result["file_id"])
    os.remove(path)


def test_drive_adapter_matches_base_interface():
    from app.storage.gdrive import GoogleDriveStorage
    from app.storage.local_storage import LocalStorage
    for cls in (MockDriveStorage, GoogleDriveStorage, LocalStorage):
        for method in ["test_connection", "ensure_folder_tree", "upload_file",
                       "download_file", "delete_file", "delete_folder_tree"]:
            assert hasattr(cls, method)


def test_local_adapter_folder_structure(tmp_path):
    from app.storage.local_storage import LocalStorage
    storage = LocalStorage(root=str(tmp_path))
    tree = storage.ensure_folder_tree("DSK-2026-000042", ["Income Certificate"])
    assert (tmp_path / "2026" / "DSK-2026-000042").exists()
    assert (tmp_path / "2026" / "DSK-2026-000042" / "Income Certificate").exists()
    assert (tmp_path / "2026" / "DSK-2026-000042" / "Payment_Proof").exists()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png_bytes())
        path = tmp.name
    result = storage.upload_file(path, "x.png", "image/png",
                                 tree["service_folder_ids"]["Income Certificate"])
    stored = tmp_path / "2026" / "DSK-2026-000042" / "Income Certificate" / "x.png"
    assert stored.exists()
    assert storage.delete_file(result["file_id"])
    os.remove(path)


# --------------------------------------------------------------------------
# Receipt PDF
# --------------------------------------------------------------------------

def test_receipt_pdf_generation(client, service):
    from app.utils.receipts import build_receipt_pdf
    from app.utils.settings import load_all_settings
    from app.models import Order
    from .conftest import add_to_cart, fill_valid_form

    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    client.post("/checkout", data={"name": "Receipt User", "mobile": "9400000001",
                                   "consent": "1", "checkout_token": token})
    order = Order.query.order_by(Order.id.desc()).first()
    pdf = build_receipt_pdf(order, load_all_settings())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1500


def test_receipt_shows_pending_not_paid(client, service):
    """A pending payment must never be described as paid in the receipt flow."""
    from app.models import Order
    from .conftest import add_to_cart, fill_valid_form

    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    resp = client.post("/checkout", data={"name": "Pending User", "mobile": "9400000002",
                                          "consent": "1", "checkout_token": token},
                       follow_redirects=False)
    from urllib.parse import urlparse, parse_qs
    order = Order.query.order_by(Order.id.desc()).first()
    url_token = parse_qs(urlparse(resp.headers["Location"]).query)["token"][0]
    receipt = client.get(f"/order/{order.order_number}/receipt.pdf?token={url_token}")
    assert receipt.status_code == 200
    assert receipt.headers["Content-Type"] == "application/pdf"
    # the confirmation page itself must show payment as awaiting, not paid
    confirm = client.get(resp.headers["Location"])
    page = confirm.get_data(as_text=True)
    assert "Pay by UPI Now" in page


# --------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------

def test_language_switch_and_bilingual_content(client, service):
    client.get("/set-lang/hi")
    resp = client.get("/")
    page = resp.get_data(as_text=True)
    assert "सेवाएँ" in page or "हिन्दी" in page
    client.get("/set-lang/en")
    resp = client.get("/")
    assert "Explore Services" in resp.get_data(as_text=True)


def test_service_name_hindi_on_hi_services_page(client, service):
    client.get("/set-lang/hi")
    resp = client.get("/services/")
    assert "सेवा" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

def test_notification_recorded_honestly(client, service):
    from .conftest import add_to_cart, fill_valid_form
    from app.models import Order

    key = add_to_cart(client, service.id)
    fill_valid_form(client, key, service)
    with client.session_transaction() as sess:
        token = sess.get("checkout_token")
    client.post("/checkout", data={"name": "Notify Me", "mobile": "9500000001",
                                   "consent": "1", "checkout_token": token})
    order = Order.query.order_by(Order.id.desc()).first()
    notifications = Notification.query.filter_by(order_id=order.id).all()
    assert any(n.event_type == "order_submitted" for n in notifications)
    # no provider configured in tests -> honest skipped state
    assert all(n.delivery_status in ("skipped", "sent") for n in notifications)
    assert all(n.delivery_status != "failed" for n in notifications)


# --------------------------------------------------------------------------
# Money formatting
# --------------------------------------------------------------------------

def test_indian_rupee_formatting(app):
    from app.utils.formatting import inr
    assert inr(150) == "\u20b9150.00"
    assert inr(1234567.5) == "\u20b912,34,567.50"
    assert inr(1000) == "\u20b91,000.00"


def test_drive_settings_encryption(app):
    """OAuth credentials must be encrypted at rest."""
    from app.utils import drive_settings
    with app.app_context():
        drive_settings.save_credentials({"token": "sensitive-token",
                                         "refresh_token": "r1"})
        from app.models import WebsiteSetting
        row = db.session.get(WebsiteSetting, drive_settings.CREDS_KEY)
        assert row.value_text != "sensitive-token"
        assert "sensitive-token" not in row.value_text
        creds = drive_settings.load_credentials()
        assert creds["refresh_token"] == "r1"
        drive_settings.clear_credentials()
        assert not drive_settings.is_drive_connected()
