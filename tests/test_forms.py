"""Dynamic form validation and service management tests."""
from io import BytesIO

from app.extensions import db
from app.models import Service
from .conftest import png_bytes, add_to_cart


def test_service_creation_via_admin(admin_client, category):
    resp = admin_client.post("/admin/services/new", data={
        "name_en": "Admin Made Service", "category_id": category.id,
        "service_charge": "250", "official_fee": "0", "other_charge": "10",
        "is_active": "on",
    }, follow_redirects=True)
    assert resp.status_code == 200
    svc = Service.query.filter_by(name_en="Admin Made Service").first()
    assert svc is not None
    assert svc.slug == "admin-made-service"
    assert float(svc.total_price) == 260.0


def test_form_field_add(admin_client, service):
    admin_client.post(f"/admin/services/{service.id}/form/add", data={
        "label_en": "Email", "field_type": "email", "is_required": "on", "is_active": "on",
    }, follow_redirects=True)
    assert any(f.field_key == "email" for f in service.form_fields.all())


def test_field_key_uniqueness(admin_client, service):
    for _ in range(2):
        admin_client.post(f"/admin/services/{service.id}/form/add", data={
            "label_en": "Village Name", "field_type": "text", "is_active": "on",
        })
    keys = [f.field_key for f in service.form_fields.filter_by(label_en="Village Name")]
    assert len(keys) == 2 and len(set(keys)) == 2  # auto-deduplicated keys


# --- validation behaviour ------------------------------------------------------

def test_required_field_rejected(client, service):
    item_key = add_to_cart(client, service.id)
    resp = client.post(f"/apply/{item_key}", data={}, follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "required" in page or "आवश्यक" in page


def test_invalid_option_rejected(client, service):
    item_key = add_to_cart(client, service.id)
    resp = client.post(f"/apply/{item_key}", data={
        "full_name": "Ramesh", "mobile": "9876543210", "gender": "HackerValue",
    }, follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "valid option" in page or "मान्य विकल्प" in page


def test_mobile_number_format_validated(client, service):
    item_key = add_to_cart(client, service.id)
    resp = client.post(f"/apply/{item_key}", data={
        "full_name": "Ramesh", "mobile": "not-a-number", "gender": "Male",
    }, follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "valid mobile" in page or "मान्य मोबाइल" in page


def test_document_wrong_extension_rejected(client, service):
    item_key = add_to_cart(client, service.id)
    data = {"full_name": "Ramesh", "mobile": "9876543210", "gender": "Male",
            "req_1": (BytesIO(b"GIF89a" + b"z" * 50), "document.gif")}
    resp = client.post(f"/apply/{item_key}", data=data,
                       content_type="multipart/form-data", follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "format" in page or "प्रारूप" in page


def test_document_fake_content_rejected(client, service):
    item_key = add_to_cart(client, service.id)
    data = {"full_name": "Ramesh", "mobile": "9876543210", "gender": "Male",
            "req_1": (BytesIO(b"this is not really a pdf file" * 5), "fake.pdf")}
    resp = client.post(f"/apply/{item_key}", data=data,
                       content_type="multipart/form-data", follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "invalid" in page or "अमान्य" in page


def test_valid_submission_stages_files(client, service):
    item_key = add_to_cart(client, service.id)
    data = {"full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
            "req_1": (BytesIO(png_bytes()), "aadhaar.png")}
    resp = client.post(f"/apply/{item_key}", data=data,
                       content_type="multipart/form-data", follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "saved" in page or "सुरक्षित" in page


def test_min_length_enforced(client, service):
    item_key = add_to_cart(client, service.id)
    resp = client.post(f"/apply/{item_key}", data={
        "full_name": "ab", "mobile": "9876543210", "gender": "Male",
        "req_1": (BytesIO(png_bytes()), "a.png"),
    }, content_type="multipart/form-data", follow_redirects=True)
    page = resp.get_data(as_text=True)
    assert "too short" in page or "बहुत छोटा" in page


def test_form_preview_renders_fields(admin_client, service):
    resp = admin_client.get(f"/admin/services/{service.id}/form/preview")
    page = resp.get_data(as_text=True)
    assert "Full Name" in page and "Aadhaar Document" in page


def test_deactivated_field_not_validated(admin_client, service):
    field = service.form_fields.filter_by(field_key="gender").first()
    field.is_active = False
    db.session.commit()
    from app.utils.dynamic_forms import validate_dynamic_form

    class FakeReq:  # minimal request stand-in
        form = {"full_name": "Valid Name", "mobile": "9876543210"}
        files = {}

    values, errors = validate_dynamic_form(service.active_form_fields, FakeReq)
    assert errors == {}
    assert "gender" not in values
    field.is_active = True
    db.session.commit()
