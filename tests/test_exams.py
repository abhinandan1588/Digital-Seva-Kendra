"""Tests for examination cycle management (Parts 3-5): status engine,
countdowns, filters, closed-cycle ordering guard, admin lifecycle."""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import Service, ExamCycle, Application
from app.utils.exams import (compute_status, refresh_cycle_status, deadline_info,
                             cycle_accepting_applications, today)


@pytest.fixture
def exam_service(category):
    svc = Service(category=category, slug="exam-svc", name_en="Test Exam",
                  name_hi="परीक्षा", service_charge=150, official_fee=0,
                  is_active=True, is_examination=True)
    db.session.add(svc)
    db.session.commit()
    return svc


def _cycle(service, slug, start=None, last=None, status="upcoming",
           published=True, year=2027, org="SSC", **kwargs):
    kwargs.setdefault("state", "All India")
    cycle = ExamCycle(service_id=service.id, cycle_slug=slug,
                      display_name=f"Test Exam {slug}", organization=org,
                      exam_year=year, exam_status=status, is_published=published,
                      application_start_date=start, application_last_date=last,
                      **kwargs)
    db.session.add(cycle)
    db.session.commit()
    return cycle


# --- status engine --------------------------------------------------------------

def test_status_transitions(exam_service):
    t = today()
    opening = _cycle(exam_service, "c-open", start=t - timedelta(days=2),
                     last=t + timedelta(days=20))
    upcoming = _cycle(exam_service, "c-upcoming", start=t + timedelta(days=5),
                      last=t + timedelta(days=30))
    closed = _cycle(exam_service, "c-closed", start=t - timedelta(days=30),
                    last=t - timedelta(days=2))
    assert compute_status(opening) == "open"
    assert compute_status(upcoming) == "upcoming"
    assert compute_status(closed) == "closed"
    # refresh persists the computed status
    assert refresh_cycle_status(closed) is True
    assert closed.exam_status == "closed"


def test_approaching_deadline_label(exam_service):
    t = today()
    cycle = _cycle(exam_service, "c-approaching", start=t - timedelta(days=2),
                   last=t + timedelta(days=3))
    info = deadline_info(cycle)
    assert info["label_key"] == "last_date_approaching"
    assert info["days_left"] == 3
    far = _cycle(exam_service, "c-far", start=t - timedelta(days=2),
                 last=t + timedelta(days=40))
    assert deadline_info(far)["label_key"] == "days_left"


def test_open_cycles_property(exam_service):
    t = today()
    _cycle(exam_service, "open-c", start=t - timedelta(days=1), last=t + timedelta(days=9))
    _cycle(exam_service, "closed-c", start=t - timedelta(days=9), last=t - timedelta(days=1))
    _cycle(exam_service, "unpub-c", start=t - timedelta(days=1), last=t + timedelta(days=9),
           published=False)
    assert [c.cycle_slug for c in exam_service.open_cycles] == ["open-c"]


def test_auto_close_refresh_all(exam_service):
    t = today()
    cycle = _cycle(exam_service, "will-close", start=t - timedelta(days=10),
                   last=t - timedelta(days=1), status="open")
    from app.utils.exams import refresh_all_cycle_statuses
    changed = refresh_all_cycle_statuses()
    assert changed >= 1
    db.session.refresh(cycle)
    assert cycle.exam_status == "closed"


# --- public listing & guard rails -------------------------------------------------

def test_exam_listing_shows_only_published(client, exam_service):
    t = today()
    _cycle(exam_service, "pub-open", start=t - timedelta(days=1),
           last=t + timedelta(days=10))
    _cycle(exam_service, "hidden", start=t - timedelta(days=1),
           last=t + timedelta(days=10), published=False)
    page = client.get("/exams/")
    assert b"pub-open" in page.data
    assert b"hidden" not in page.data


def test_exam_listing_filters(client, exam_service):
    t = today()
    _cycle(exam_service, "ssc-open", start=t - timedelta(days=1),
           last=t + timedelta(days=10), org="SSC", education_level="Graduation")
    _cycle(exam_service, "bpsc-open", start=t - timedelta(days=1),
           last=t + timedelta(days=10), org="BPSC", state="Bihar")
    _cycle(exam_service, "soon-closed", start=t - timedelta(days=1),
           last=t + timedelta(days=3), org="SSC")
    page = client.get("/exams/?organization=SSC")
    assert b"ssc-open" in page.data and b"bpsc-open" not in page.data
    page = client.get("/exams/?education_level=Graduation")
    assert b"ssc-open" in page.data
    page = client.get("/exams/?state=Bihar")
    assert b"bpsc-open" in page.data and b"ssc-open" not in page.data
    page = client.get("/exams/?deadline_within=7")
    assert b"soon-closed" in page.data and b"ssc-open" not in page.data


def test_exam_detail_closed_cycle_not_orderable(client, exam_service):
    t = today()
    closed = _cycle(exam_service, "closed-pub", start=t - timedelta(days=10),
                    last=t - timedelta(days=1))
    page = client.get(f"/exams/{closed.cycle_slug}")
    assert page.status_code == 200
    assert b"closed" in page.data.lower()
    assert b"Apply Now" not in page.data  # no add-to-cart form for closed cycles


def test_closed_cycle_rejected_in_add_to_cart(client, exam_service):
    t = today()
    closed = _cycle(exam_service, "closed-pub", start=t - timedelta(days=10),
                    last=t - timedelta(days=1))
    resp = client.post(f"/cart/add/{exam_service.id}", data={"exam_cycle_id": closed.id},
                       follow_redirects=False)
    assert resp.status_code == 302  # redirected with a flash, nothing added
    with client.session_transaction() as sess:
        assert sess.get("dsk_cart", []) == []


# --- ordering with cycle ------------------------------------------------------------

def _order_exam_with_cycle(client, exam_service, cycle, cycle_required_setup=True):
    client.post(f"/cart/add/{exam_service.id}", data={"exam_cycle_id": cycle.id})
    with client.session_transaction() as sess:
        items = sess.get("dsk_cart", [])
        key = items[-1]["key"]
    resp = client.post(f"/apply/{key}", data={
        "exam_cycle_id": str(cycle.id),
        "candidate_name": "Test Candidate",
        "mobile": "9876543210",
    }, follow_redirects=True)
    assert resp.status_code == 200
    return key


def test_exam_order_requires_cycle_and_snapshots_it(client, exam_service):
    t = today()
    open_cycle = _cycle(exam_service, "order-open", start=t - timedelta(days=1),
                        last=t + timedelta(days=10))
    _order_exam_with_cycle(client, exam_service, open_cycle)
    resp = client.post("/checkout", data={
        "name": "Test Candidate", "mobile": "9876543210", "consent": "y",
    }, follow_redirects=True)
    assert resp.status_code == 200
    order = None
    from app.models import Order
    order = Order.query.order_by(Order.id.desc()).first()
    assert order is not None
    application = order.applications[0]
    assert application.exam_cycle_id == open_cycle.id
    assert open_cycle.display_name in (application.exam_cycle_snapshot or "")


def test_exam_order_blocked_without_cycle_selection(client, exam_service):
    t = today()
    _cycle(exam_service, "order-open", start=t - timedelta(days=1),
           last=t + timedelta(days=10))
    client.post(f"/cart/add/{exam_service.id}")
    with client.session_transaction() as sess:
        key = sess.get("dsk_cart", [])[-1]["key"]
    # apply form without cycle choice must fail
    resp = client.post(f"/apply/{key}", data={"candidate_name": "X", "mobile": "9876543210"},
                       follow_redirects=True)
    assert b"examination cycle" in resp.data.lower()
    # checkout must stay blocked as well
    before = Order_count()
    resp = client.post("/checkout", data={"name": "Test", "mobile": "9876543210",
                                          "consent": "y"}, follow_redirects=True)
    assert Order_count() == before


def Order_count():
    from app.models import Order
    return Order.query.count()


def test_non_exam_service_unaffected(client, category):
    """Ordinal services keep working with no cycle logic."""
    svc = Service(category=category, slug="plain-svc", name_en="Plain Service",
                  service_charge=100, official_fee=10, is_active=True)
    db.session.add(svc)
    db.session.commit()
    client.post(f"/cart/add/{svc.id}")
    with client.session_transaction() as sess:
        key = sess.get("dsk_cart", [])[-1]["key"]
    resp = client.post(f"/apply/{key}", data={"applicant_name": "X", "mobile": "9876543210"},
                       follow_redirects=True)
    assert resp.status_code == 200
    resp = client.post("/checkout", data={"name": "Test", "mobile": "9876543210",
                                          "consent": "y"}, follow_redirects=True)
    assert resp.status_code == 200


# --- admin lifecycle ---------------------------------------------------------------

def test_admin_cycle_publish_requires_verification(admin_client, exam_service):
    t = today()
    cycle = _cycle(exam_service, "admin-c", start=t - timedelta(days=1),
                   last=t + timedelta(days=10), published=False)
    # publish without verification is refused
    resp = admin_client.post(f"/admin/exam-cycles/{cycle.id}/publish",
                             data={"action": "publish"}, follow_redirects=True)
    assert cycle.is_published is False
    # verify then publish works
    admin_client.post(f"/admin/exam-cycles/{cycle.id}/publish", data={"action": "verify"})
    assert cycle.last_verified_at is not None
    assert cycle.needs_review is False
    admin_client.post(f"/admin/exam-cycles/{cycle.id}/publish", data={"action": "publish"})
    assert cycle.is_published is True


def test_admin_extension_requires_confirmation(admin_client, exam_service):
    t = today()
    cycle = _cycle(exam_service, "ext-c", start=t - timedelta(days=1),
                   last=t + timedelta(days=1))
    resp = admin_client.post(f"/admin/exam-cycles/{cycle.id}/extend", data={
        "new_application_last_date": (t + timedelta(days=20)).isoformat(),
    }, follow_redirects=True)
    assert cycle.officially_extended is False
    admin_client.post(f"/admin/exam-cycles/{cycle.id}/extend", data={
        "new_application_last_date": (t + timedelta(days=20)).isoformat(),
        "official_confirmation": "y",
        "extension_note": "Official notice received",
    }, follow_redirects=True)
    assert cycle.application_last_date == t + timedelta(days=20)
    assert cycle.officially_extended is True


def test_admin_create_cycle_via_form(admin_client, exam_service):
    t = today()
    resp = admin_client.post("/admin/exam-cycles/new", data={
        "service_id": exam_service.id,
        "display_name": "Test Exam 2028",
        "organization": "SSC",
        "exam_year": "2028",
        "application_start_date": (t + timedelta(days=3)).isoformat(),
        "application_last_date": (t + timedelta(days=33)).isoformat(),
        "fee_general": "100",
        "fee_sc_st": "25",
        "fee_note": "As per notification",
        "exam_status": "upcoming",
    }, follow_redirects=True)
    assert resp.status_code == 200
    cycle = ExamCycle.query.filter_by(display_name="Test Exam 2028").first()
    assert cycle is not None
    assert cycle.application_fees["general"] == 100
    assert cycle.fee_note.startswith("General")
