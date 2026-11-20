"""Admin authentication & security tests."""
from app.models import AdminUser
from app.extensions import db


def test_admin_login_success(client, admin_user):
    resp = client.post("/admin/login", data={"email": "admin@test.local",
                                             "password": "TestPass#123"})
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


def test_admin_login_wrong_password(client, admin_user):
    resp = client.post("/admin/login", data={"email": "admin@test.local",
                                             "password": "wrong-pass"})
    assert resp.status_code == 401


def test_admin_login_unknown_email_is_same_error(client, admin_user):
    resp = client.post("/admin/login", data={"email": "nobody@test.local",
                                             "password": "TestPass#123"})
    assert resp.status_code == 401  # no account enumeration


def test_unauthorized_admin_access_redirects_to_login(client):
    for path in ["/admin/", "/admin/orders", "/admin/payments", "/admin/services"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]


def test_password_not_stored_in_plain_text(app, admin_user):
    with app.app_context():
        user = db.session.get(AdminUser, admin_user.id)
        assert user.password_hash != "TestPass#123"
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password("TestPass#123")
        assert not user.check_password("wrong")


def test_logout_requires_login_and_works(admin_client):
    resp = admin_client.post("/admin/logout")
    assert resp.status_code == 302
    resp = admin_client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]


def test_change_password_flow(admin_client, app, admin_user):
    resp = admin_client.post("/admin/change-password", data={
        "current_password": "TestPass#123",
        "new_password": "NewPass#456",
        "confirm_password": "NewPass#456",
    })
    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(AdminUser, admin_user.id)
        assert user.check_password("NewPass#456")


def test_change_password_rejects_short(admin_client, app, admin_user):
    admin_client.post("/admin/change-password", data={
        "current_password": "TestPass#123",
        "new_password": "short",
        "confirm_password": "short",
    })
    with app.app_context():
        user = db.session.get(AdminUser, admin_user.id)
        assert user.check_password("TestPass#123")


def test_account_lock_after_failed_attempts(client, admin_user, app):
    for _ in range(5):
        client.post("/admin/login", data={"email": "admin@test.local",
                                          "password": "bad-guess"})
    with app.app_context():
        user = db.session.get(AdminUser, admin_user.id)
        assert user.is_locked
    resp = client.post("/admin/login", data={"email": "admin@test.local",
                                             "password": "TestPass#123"})
    assert resp.status_code == 423  # locked even with correct password


def test_csrf_required_on_login(client, app):
    from app.extensions import csrf as csrf_ext
    app.config["WTF_CSRF_ENABLED"] = True
    resp = client.post("/admin/login", data={"email": "admin@test.local",
                                             "password": "TestPass#123"})
    assert resp.status_code == 400  # CSRF token missing -> rejected
    app.config["WTF_CSRF_ENABLED"] = False
