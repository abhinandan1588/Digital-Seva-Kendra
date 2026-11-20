"""Dedicated category pages (Part 12): title, description, search, service
cards with price/documents preview/availability and Apply Now."""
from flask import Blueprint, render_template, request

from ..models import ServiceCategory, ServiceSubcategory, Service
from ..utils.search import search_services, popular_searches

category_bp = Blueprint("category", __name__, url_prefix="/category")


@category_bp.route("/<slug>")
def category_page(slug):
    category = ServiceCategory.query.filter_by(slug=slug, is_active=True).first_or_404()
    query = (request.args.get("q") or "").strip()
    subcategory_slug = (request.args.get("sub") or "").strip()

    subcategories = (ServiceSubcategory.query.filter_by(category_id=category.id, is_active=True)
                     .order_by(ServiceSubcategory.sort_order).all())
    selected_subcategory = next((s for s in subcategories if s.slug == subcategory_slug), None)

    if query:
        services = [s for s in search_services(query) if s.category_id == category.id]
    else:
        services_query = Service.query.filter(Service.is_active.is_(True),
                                              Service.is_archived.is_(False),
                                              Service.category_id == category.id)
        if selected_subcategory:
            services_query = services_query.filter(Service.subcategory_id == selected_subcategory.id)
        services = services_query.order_by(Service.sort_order, Service.id).all()

    return render_template("services/category.html", category=category,
                           subcategories=subcategories,
                           selected_subcategory=selected_subcategory,
                           services=services, query=query,
                           popular_terms=popular_searches(6))
