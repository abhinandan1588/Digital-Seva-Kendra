"""Public service catalogue: browse, search (bilingual + aliases), service
detail, dedicated category pages and search suggestions."""
from flask import Blueprint, render_template, request, jsonify

from sqlalchemy import or_

from ..extensions import db
from ..models import ServiceCategory, Service, ServiceSubcategory, ExamCycle
from ..utils.exams import refresh_all_cycle_statuses, deadline_info
from ..utils.search import search_services, suggest, popular_searches, log_search_term
from ..models.service import capability_label, capability_description

services_bp = Blueprint("services", __name__, url_prefix="/services")


def _service_context(service):
    """Everything the detail template needs beyond the Service row."""
    return {
        "capability_label": capability_label(service.capability_type),
        "capability_description": capability_description(service.capability_type),
        "portal": service.official_portal if service.official_portal and service.official_portal.is_active else None,
        "open_cycles": service.open_cycles if service.is_examination else [],
        "closed_cycles": [c for c in service.exam_cycles
                          if c.is_published and not c.is_archived
                          and c not in service.open_cycles][:6],
        "deadline": {c.id: deadline_info(c) for c in service.exam_cycles},
    }


@services_bp.route("/")
def catalogue():
    query = (request.args.get("q") or "").strip()
    category_slug = (request.args.get("category") or "").strip()
    subcategory_slug = (request.args.get("subcategory") or "").strip()

    active_categories = (ServiceCategory.query.filter_by(is_active=True)
                         .order_by(ServiceCategory.sort_order).all())

    selected_category = None
    selected_subcategory = None
    if category_slug:
        selected_category = ServiceCategory.query.filter_by(slug=category_slug).first()

    subcategories = []
    if selected_category:
        subcategories = (ServiceSubcategory.query.filter_by(
            category_id=selected_category.id, is_active=True)
            .order_by(ServiceSubcategory.sort_order).all())
        if subcategory_slug:
            selected_subcategory = next((s for s in subcategories if s.slug == subcategory_slug), None)

    if query:
        services = search_services(query)
        log_search_term(query)
        db.session.commit()
    else:
        services_query = Service.query.filter(Service.is_active.is_(True),
                                              Service.is_archived.is_(False))
        if selected_subcategory:
            services_query = services_query.filter(Service.subcategory_id == selected_subcategory.id)
        elif selected_category:
            services_query = services_query.filter(Service.category_id == selected_category.id)
        services = services_query.order_by(Service.sort_order, Service.id).all()

    recent_services = (Service.query.filter(Service.is_active.is_(True),
                                            Service.is_archived.is_(False))
                       .order_by(Service.id.desc()).limit(8).all()) if not query else []

    return render_template("services/list.html",
                           services=services,
                           categories=active_categories,
                           subcategories=subcategories,
                           selected_category=selected_category,
                           selected_subcategory=selected_subcategory,
                           popular_terms=popular_searches(6),
                           recent_services=recent_services,
                           query=query)


@services_bp.route("/suggest")
def suggestions():
    """JSON suggestions for the navbar search box (bilingual)."""
    q = (request.args.get("q") or "").strip()
    return jsonify({"suggestions": suggest(q, limit=8)})


@services_bp.route("/<slug>")
def detail(slug):
    service = Service.query.filter_by(slug=slug, is_active=True).first_or_404()
    requirements = service.active_document_requirements
    fields = service.active_form_fields
    if service.is_examination:
        refresh_all_cycle_statuses()
    return render_template("services/detail.html", service=service,
                           requirements=requirements, fields=fields,
                           ctx=_service_context(service))
