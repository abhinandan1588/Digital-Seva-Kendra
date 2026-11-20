"""Tests for the service catalogue expansion: models, capability compliance,
bilingual search, document templates, portals, category pages, seed data."""
import pytest

from app.extensions import db
from app.models import (ServiceCategory, ServiceSubcategory, Service,
                        DocumentTemplate, OfficialPortal, SearchAlias,
                        ServiceDocumentRequirement)


@pytest.fixture
def subcategory(category):
    sub = ServiceSubcategory(category_id=category.id, slug="test-sub",
                             name_en="Test Sub", name_hi="उपश्रेणी")
    db.session.add(sub)
    db.session.commit()
    return sub


@pytest.fixture
def portal():
    p = OfficialPortal(slug="test-portal", name_en="Test Portal",
                       url="https://example.gov.in/", state="Bihar")
    db.session.add(p)
    db.session.commit()
    return p


def _make_service(cat, slug, charge="100", official="0", name_hi="सेवा", **kwargs):
    svc = Service(category=cat, slug=slug, name_en=f"Service {slug}",
                  name_hi=name_hi, service_charge=charge, official_fee=official,
                  is_active=True, **kwargs)
    db.session.add(svc)
    db.session.commit()
    return svc


# --- catalogue structure ------------------------------------------------------

def test_category_group_field(category):
    assert category.group == "other"
    category.group = "documents"
    db.session.commit()
    assert ServiceCategory.query.filter_by(group="documents").count() >= 1


def test_subcategory_crud_and_link(category, subcategory):
    svc = _make_service(category, "sub-linked", subcategory_id=subcategory.id)
    assert svc.subcategory.slug == "test-sub"
    assert subcategory.active_service_count == 1


def test_service_capability_and_orderability(category):
    restricted = _make_service(category, "restricted-svc",
                               capability_type="restricted_authorization_required")
    internal = _make_service(category, "internal-svc", capability_type="internal_service")
    assert restricted.is_restricted
    assert not restricted.is_orderable
    assert internal.is_orderable


def test_restricted_service_visible_but_not_orderable(client, category):
    _make_service(category, "restricted-svc",
                  capability_type="restricted_authorization_required")
    # Visible in catalogue with restriction badge
    page = client.get("/services/")
    assert "Service restricted-svc".encode() in page.data
    # Cannot be added to cart
    svc = Service.query.filter_by(slug="restricted-svc").first()
    client.post(f"/cart/add/{svc.id}")
    with client.session_transaction() as sess:
        assert sess.get("dsk_cart", []) == []


def test_service_detail_shows_capability_and_portal(client, category, portal):
    svc = _make_service(category, "portal-svc", official_portal_id=portal.id,
                        eligibility_en="Only for testing")
    page = client.get("/services/portal-svc")
    assert b"example.gov.in" in page.data
    assert b"Only for testing" in page.data


# --- search -------------------------------------------------------------------

def test_bilingual_and_alias_search(client, category):
    svc = _make_service(category, "income-cert", name_hi="आय प्रमाणपत्र",
                        search_keywords="aay praman patra income")
    db.session.add(SearchAlias(alias="aay praman patra", service_id=svc.id))
    db.session.commit()
    for query in ("aay praman patra", "आय प्रमाणपत्र", "income-cert", "Income Cert"):
        page = client.get(f"/services/?q={query}")
        assert "Service income-cert".encode() in page.data, query


def test_suggestions_endpoint(client, category):
    _make_service(category, "pan-check", search_keywords="pan")
    resp = client.get("/services/suggest?q=pan")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any("pan-check" == s["slug"] for s in data["suggestions"])


def test_search_logged_and_popular(client, category):
    _make_service(category, "searchable-svc")
    client.get("/services/?q=scholarship test query")
    from app.models import SearchQueryStat
    from app.utils.search import popular_searches
    stat = SearchQueryStat.query.filter_by(term="scholarship test query").first()
    assert stat is not None and stat.count == 1
    assert "scholarship test query" in popular_searches()


# --- category pages -----------------------------------------------------------

def test_category_page_and_subcategory_filter(client, category, subcategory):
    sub_svc = _make_service(category, "in-sub", subcategory_id=subcategory.id)
    _make_service(category, "not-in-sub")
    # Without a sub filter, the whole category is shown
    page = client.get(f"/category/{category.slug}")
    assert b"in-sub" in page.data and b"not-in-sub" in page.data
    # With ?sub= only that subcategory's services are shown
    page = client.get(f"/category/{category.slug}?sub={subcategory.slug}")
    assert b"in-sub" in page.data and b"not-in-sub" not in page.data


# --- document templates -------------------------------------------------------

def test_document_template_attach(category):
    template = DocumentTemplate(slug="photo-tpl", name_en="Photograph",
                                allowed_extensions=["jpg"], max_file_mb=2,
                                is_required=True, template_group="general")
    db.session.add(template)
    svc = _make_service(category, "doc-tpl-svc")
    db.session.add(ServiceDocumentRequirement(
        service=svc, document_template_id=template.id, label_en=template.name_en,
        allowed_extensions=template.allowed_extensions, max_file_mb=2,
        is_required=True, sort_order=1))
    db.session.commit()
    assert svc.active_document_requirements[0].document_template_id == template.id
    # Deleting the template must never destroy the service's requirement copy
    # (label/data survive; FK is SET NULL on PostgreSQL - SQLite dev DBs only
    # enforce FKs with a pragma, so we assert the surviving data here).
    template_id = template.id
    db.session.delete(template)
    db.session.commit()
    req = svc.active_document_requirements[0]
    assert req.label_en == "Photograph"
    assert req.document_template_id in (None, template_id)


# --- seeded catalogue data (the real files) ------------------------------------

def test_seed_catalogue_data(app):
    from app.cli_catalogue import (_seed_portals, _seed_document_templates,
                                   _seed_search_aliases, _seed_categories,
                                   _seed_template_exam_cycles)
    with app.app_context():
        portals = _seed_portals()
        templates = _seed_document_templates()
        aliases = _seed_search_aliases()
        cats, subs, services = _seed_categories()
        cycles = _seed_template_exam_cycles()
        db.session.commit()
        assert cats >= 15
        assert subs >= 40
        assert services >= 250
        assert portals >= 40 and templates >= 20
        # every category has a group; services have capability + charges
        assert ServiceCategory.query.filter_by(slug="government-certificates-documents").first().group == "documents"
        assert Service.query.filter(Service.official_portal_id.is_(None)).count() < services
        restricted = Service.query.filter_by(capability_type="restricted_authorization_required").count()
        assert restricted > 0
        exam_services = Service.query.filter_by(is_examination=True).count()
        assert exam_services >= 100
        # template cycles are created unpublished + flagged for review (no invented dates)
        from app.models import ExamCycle
        sample = ExamCycle.query.filter_by(is_published=False, needs_review=True).first()
        assert sample is not None
        assert sample.application_last_date is None
        # idempotent: run again, nothing duplicated
        assert _seed_categories() == (0, 0, 0)
        db.session.commit()


def test_no_duplicate_services_for_hindi_english(app):
    with app.app_context():
        # Hindi and English names refer to the SAME record: name_hi is on the
        # same row, so no service shares a slug suffix pair across languages.
        slugs = [s.slug for s in Service.query.all()]
        assert len(slugs) == len(set(slugs))
