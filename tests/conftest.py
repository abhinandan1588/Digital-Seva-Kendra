"""Pytest fixtures: test app on a dedicated test database.

Defaults to a file-based SQLite DB (works on any machine, no services needed).
Set TEST_DATABASE_URL to a postgresql:// URL to run against PostgreSQL instead.
"""
import os
import sys
from io import BytesIO

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["FLASK_CONFIG"] = "testing"
IS_POSTGRES = bool(os.environ.get("TEST_DATABASE_URL", "").startswith("postgres"))
if IS_POSTGRES:
    TEST_DB_URL = os.environ["TEST_DATABASE_URL"]
else:
    _test_db_path = os.path.join(PROJECT_ROOT, "instance", "digital_seva_test.db")
    os.makedirs(os.path.dirname(_test_db_path), exist_ok=True)
    TEST_DB_URL = "sqlite:///" + _test_db_path
os.environ["TEST_DATABASE_URL"] = TEST_DB_URL

import pytest  # noqa: E402


def _ensure_test_database() -> None:
    if not IS_POSTGRES:
        return
    from urllib.parse import urlparse, parse_qs
    import psycopg
    u = urlparse(TEST_DB_URL)
    host_param = (parse_qs(u.query).get("host") or [None])[0]
    if host_param:
        admin_url = f"{u.scheme}://postgres:@/postgres?host={host_param}"
    else:
        admin_url = f"{u.scheme}://{u.netloc}/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", ("digital_seva_test",)
        ).fetchone()
        if not exists:
            conn.execute("CREATE DATABASE digital_seva_test")


_ensure_test_database()

from app import create_app  # noqa: E402
from app.config import TestingConfig  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import AdminUser, ServiceCategory, Service, ServiceFormField, \
    ServiceDocumentRequirement  # noqa: E402


@pytest.fixture(scope="session")
def app():
    TestingConfig.SQLALCHEMY_DATABASE_URI = TEST_DB_URL
    app = create_app(TestingConfig)
    # IMPORTANT: do NOT hold an app context open across tests - Flask reuses an
    # already-active app context for requests, which would leak `g` state
    # (e.g. flask-login's _login_user) between tests.
    with app.app_context():
        _db.create_all()
    yield app
    with app.app_context():
        _db.drop_all()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Fresh tables + one clean app context per test.

    The context is pushed/popped around each single test (never held across
    tests), so Flask request contexts can reuse it safely within one test
    while `g` state never leaks BETWEEN tests.
    """
    from sqlalchemy import text
    ctx = app.app_context()
    ctx.push()
    try:
        _db.session.rollback()
        _db.session.expire_all()
        if IS_POSTGRES:
            tables = ", ".join(f'"{t.name}"' for t in reversed(_db.metadata.sorted_tables))
            _db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        else:
            for t in reversed(_db.metadata.sorted_tables):
                _db.session.execute(text(f'DELETE FROM "{t.name}"'))
        _db.session.commit()
        yield
    finally:
        _db.session.remove()
        ctx.pop()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()


@pytest.fixture
def admin_user(app):
    user = AdminUser(email="admin@test.local", name="Test Admin")
    user.set_password("TestPass#123")
    _db.session.add(user)
    _db.session.commit()
    yield user
    AdminUser.query.delete()
    _db.session.commit()


@pytest.fixture
def admin_client(client, admin_user):
    """A client logged in as admin."""
    client.post("/admin/login", data={"email": "admin@test.local",
                                      "password": "TestPass#123"})
    return client


@pytest.fixture
def category(app):
    cat = ServiceCategory(slug="test-cat", name_en="Test Category", name_hi="टेस्ट श्रेणी",
                          icon="bi-bank", sort_order=1)
    _db.session.add(cat)
    _db.session.commit()
    yield cat


def _make_service(cat, slug, charge="150", official="110"):
    svc = Service(category=cat, slug=slug, name_en=f"Service {slug}",
                  name_hi="सेवा", service_charge=charge, official_fee=official,
                  is_active=True)
    _db.session.add(svc)
    _db.session.flush()
    _db.session.add(ServiceFormField(
        service=svc, field_key="full_name", label_en="Full Name", label_hi="पूरा नाम",
        field_type="text", is_required=True, min_length=3, max_length=100, sort_order=1))
    _db.session.add(ServiceFormField(
        service=svc, field_key="mobile", label_en="Mobile", field_type="mobile",
        is_required=True, sort_order=2))
    _db.session.add(ServiceFormField(
        service=svc, field_key="gender", label_en="Gender", field_type="select",
        options=[{"en": "Male", "hi": "पुरुष"}, {"en": "Female", "hi": "महिला"}],
        is_required=True, sort_order=3))
    _db.session.add(ServiceDocumentRequirement(
        service=svc, label_en="Aadhaar Document", label_hi="आधार",
        allowed_extensions=["pdf", "jpg", "jpeg", "png"], max_file_mb=2,
        is_required=True, sort_order=1))
    _db.session.commit()
    return svc


@pytest.fixture
def service(app, category):
    return _make_service(category, "svc-a")


@pytest.fixture
def service_b(app, category):
    return _make_service(category, "svc-b", charge="100", official="30")


# --- helpers -----------------------------------------------------------------

def add_to_cart(client, service_id):
    """Add a service via the real cart route; return the newest item key."""
    client.post(f"/cart/add/{service_id}")
    with client.session_transaction() as sess:
        items = sess.get("dsk_cart", [])
        assert items, "cart did not persist"
        return items[-1]["key"]


def fill_valid_form(client, item_key, service=None):
    """Submit a valid dynamic form for the cart item (image upload included).

    `service` is needed so the upload input name (req_<id>) matches the
    service's actual document requirement id.
    """
    data = {
        "full_name": "Ramesh Kumar", "mobile": "9876543210", "gender": "Male",
    }
    if service is not None:
        req = service.active_document_requirements[0]
        data[f"req_{req.id}"] = (BytesIO(png_bytes()), "aadhaar.png")
    else:
        data["req_1"] = (BytesIO(png_bytes()), "aadhaar.png")
    return client.post(f"/apply/{item_key}", data=data,
                       content_type="multipart/form-data", follow_redirects=True)


def png_bytes() -> bytes:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, format="PNG")
    return buf.getvalue()


def fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake pdf content" + b"x" * 200
