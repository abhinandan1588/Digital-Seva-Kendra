"""Admin: reusable document templates (Part 6) + official portal directory
(Part 10) + service pricing & availability views (Parts 7/8/11)."""
import json as _json

from flask import (render_template, request, redirect, url_for, flash, abort,
                   Response)
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import (Service, ServiceDocumentRequirement, DocumentTemplate,
                      OfficialPortal, ServiceCategory, ServiceSubcategory)
from ..models.service import CAPABILITY_TYPES, capability_label
from ..utils.audit import log_admin_action
from .catalog_admin import _slugify, _unique_slug


# --------------------------------------------------------------------------
# Document templates
# --------------------------------------------------------------------------

@admin_bp.route("/document-templates")
@login_required
def doc_templates_list():
    templates = DocumentTemplate.query.order_by(DocumentTemplate.template_group,
                                                DocumentTemplate.name_en).all()
    return render_template("admin/doc_templates_list.html", templates=templates)


@admin_bp.route("/document-templates/new", methods=["GET", "POST"])
@login_required
def doc_template_create():
    if request.method == "POST":
        name = (request.form.get("name_en") or "").strip()
        if not name:
            flash("English name is required.", "danger")
            return render_template("admin/doc_template_form.html", template=None)
        allowed = [a.strip().lstrip(".").lower() for a in
                   (request.form.get("allowed_extensions") or "").split(",") if a.strip()] \
            or ["pdf", "jpg", "jpeg", "png"]
        template = DocumentTemplate(
            slug=_unique_slug(DocumentTemplate, _slugify(name)),
            name_en=name,
            name_hi=(request.form.get("name_hi") or "").strip() or None,
            description_en=(request.form.get("description_en") or "").strip() or None,
            description_hi=(request.form.get("description_hi") or "").strip() or None,
            allowed_extensions=allowed,
            max_file_mb=request.form.get("max_file_mb", 5, type=int),
            is_required=bool(request.form.get("is_required")),
            allow_multiple=bool(request.form.get("allow_multiple")),
            min_width=request.form.get("min_width", type=int),
            max_width=request.form.get("max_width", type=int),
            min_height=request.form.get("min_height", type=int),
            max_height=request.form.get("max_height", type=int),
            compression_note_en=(request.form.get("compression_note_en") or "").strip() or None,
            compression_note_hi=(request.form.get("compression_note_hi") or "").strip() or None,
            expires_after_days=request.form.get("expires_after_days", type=int),
            template_group=request.form.get("template_group") or "general",
            is_active=bool(request.form.get("is_active")),
        )
        db.session.add(template)
        db.session.commit()
        log_admin_action(current_user, "doc_template_created", "document_template", template.id)
        db.session.commit()
        flash("Document template created.", "success")
        return redirect(url_for("admin.doc_templates_list"))
    return render_template("admin/doc_template_form.html", template=None)


@admin_bp.route("/document-templates/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def doc_template_edit(template_id):
    template = db.session.get(DocumentTemplate, template_id) or abort(404)
    if request.method == "POST":
        template.name_en = (request.form.get("name_en") or "").strip() or template.name_en
        template.name_hi = (request.form.get("name_hi") or "").strip() or None
        template.description_en = (request.form.get("description_en") or "").strip() or None
        template.description_hi = (request.form.get("description_hi") or "").strip() or None
        allowed = [a.strip().lstrip(".").lower() for a in
                   (request.form.get("allowed_extensions") or "").split(",") if a.strip()]
        if allowed:
            template.allowed_extensions = allowed
        template.max_file_mb = request.form.get("max_file_mb", 5, type=int)
        template.is_required = bool(request.form.get("is_required"))
        template.allow_multiple = bool(request.form.get("allow_multiple"))
        template.min_width = request.form.get("min_width", type=int)
        template.max_width = request.form.get("max_width", type=int)
        template.min_height = request.form.get("min_height", type=int)
        template.max_height = request.form.get("max_height", type=int)
        template.compression_note_en = (request.form.get("compression_note_en") or "").strip() or None
        template.compression_note_hi = (request.form.get("compression_note_hi") or "").strip() or None
        template.expires_after_days = request.form.get("expires_after_days", type=int)
        template.template_group = request.form.get("template_group") or template.template_group
        template.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        log_admin_action(current_user, "doc_template_updated", "document_template", template.id)
        db.session.commit()
        flash("Document template updated.", "success")
        return redirect(url_for("admin.doc_templates_list"))
    return render_template("admin/doc_template_form.html", template=template)


@admin_bp.route("/document-templates/<int:template_id>/delete", methods=["POST"])
@login_required
def doc_template_delete(template_id):
    template = db.session.get(DocumentTemplate, template_id) or abort(404)
    db.session.delete(template)  # requirements keep their copied data (SET NULL link)
    db.session.commit()
    log_admin_action(current_user, "doc_template_deleted", "document_template", template_id)
    db.session.commit()
    flash("Template deleted. Services keep their attached document requirements.", "info")
    return redirect(url_for("admin.doc_templates_list"))


@admin_bp.route("/services/<int:service_id>/templates/attach", methods=["GET", "POST"])
@login_required
def doc_template_apply(service_id):
    """Attach reusable templates to a service as document requirements."""
    service = db.session.get(Service, service_id) or abort(404)
    templates = DocumentTemplate.query.filter_by(is_active=True).order_by(
        DocumentTemplate.template_group, DocumentTemplate.name_en).all()
    if request.method == "POST":
        chosen = request.form.getlist("template_ids")
        max_sort = db.session.query(db.func.max(ServiceDocumentRequirement.sort_order)).filter_by(
            service_id=service.id).scalar() or 0
        added = 0
        existing_labels = {r.label_en for r in service.document_requirements.all()}
        for template_id in chosen:
            template = db.session.get(DocumentTemplate, int(template_id))
            if template is None or template.name_en in existing_labels:
                continue
            max_sort += 1
            db.session.add(ServiceDocumentRequirement(
                service=service, document_template_id=template.id,
                label_en=template.name_en, label_hi=template.name_hi,
                description_en=template.description_en, description_hi=template.description_hi,
                allowed_extensions=template.allowed_extensions, max_file_mb=template.max_file_mb,
                is_required=template.is_required, allow_multiple=template.allow_multiple,
                sort_order=max_sort))
            added += 1
        db.session.commit()
        log_admin_action(current_user, "doc_templates_attached", "service", service.id,
                         {"added": added})
        db.session.commit()
        flash(f"{added} document template(s) attached. Customise them per service if needed.", "success")
        return redirect(url_for("admin.doc_requirements", service_id=service.id))
    return render_template("admin/doc_template_apply.html", service=service, templates=templates)


# --------------------------------------------------------------------------
# Official portal directory
# --------------------------------------------------------------------------

@admin_bp.route("/portals")
@login_required
def portals_list():
    portals = OfficialPortal.query.order_by(OfficialPortal.state, OfficialPortal.name_en).all()
    return render_template("admin/portals_list.html", portals=portals)


@admin_bp.route("/portals/new", methods=["GET", "POST"])
@login_required
def portal_create():
    if request.method == "POST":
        name = (request.form.get("name_en") or "").strip()
        url = (request.form.get("url") or "").strip()
        if not name or not url.startswith(("http://", "https://")):
            flash("Name and a valid https URL are required.", "danger")
            return render_template("admin/portal_form.html", portal=None)
        portal = OfficialPortal(
            slug=_unique_slug(OfficialPortal, _slugify(name)),
            name_en=name,
            name_hi=(request.form.get("name_hi") or "").strip() or None,
            url=url,
            state=(request.form.get("state") or "All India").strip(),
            department=(request.form.get("department") or "").strip() or None,
            description_en=(request.form.get("description_en") or "").strip() or None,
            description_hi=(request.form.get("description_hi") or "").strip() or None,
            official_feed_url=(request.form.get("official_feed_url") or "").strip() or None,
            is_active=bool(request.form.get("is_active")),
        )
        db.session.add(portal)
        db.session.commit()
        log_admin_action(current_user, "portal_created", "official_portal", portal.id)
        db.session.commit()
        flash("Official portal added to the directory.", "success")
        return redirect(url_for("admin.portals_list"))
    return render_template("admin/portal_form.html", portal=None)


@admin_bp.route("/portals/<int:portal_id>/edit", methods=["GET", "POST"])
@login_required
def portal_edit(portal_id):
    portal = db.session.get(OfficialPortal, portal_id) or abort(404)
    if request.method == "POST":
        portal.name_en = (request.form.get("name_en") or "").strip() or portal.name_en
        portal.name_hi = (request.form.get("name_hi") or "").strip() or None
        url = (request.form.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            portal.url = url
        portal.state = (request.form.get("state") or portal.state).strip()
        portal.department = (request.form.get("department") or "").strip() or None
        portal.description_en = (request.form.get("description_en") or "").strip() or None
        portal.description_hi = (request.form.get("description_hi") or "").strip() or None
        portal.official_feed_url = (request.form.get("official_feed_url") or "").strip() or None
        portal.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        log_admin_action(current_user, "portal_updated", "official_portal", portal.id)
        db.session.commit()
        flash("Portal updated.", "success")
        return redirect(url_for("admin.portals_list"))
    return render_template("admin/portal_form.html", portal=portal)


@admin_bp.route("/portals/<int:portal_id>/verify", methods=["POST"])
@login_required
def portal_verify(portal_id):
    portal = db.session.get(OfficialPortal, portal_id) or abort(404)
    portal.last_verified_at = db.func.now()
    db.session.commit()
    log_admin_action(current_user, "portal_verified", "official_portal", portal.id)
    db.session.commit()
    flash("Portal link marked as verified.", "success")
    return redirect(url_for("admin.portals_list"))


# --------------------------------------------------------------------------
# Service pricing (Part 8) + availability/compliance (Part 11)
# --------------------------------------------------------------------------

@admin_bp.route("/services/pricing")
@login_required
def services_pricing():
    q = (request.args.get("q") or "").strip()
    category_id = request.args.get("category_id", type=int)
    query = Service.query.filter(Service.is_archived.is_(False))
    if q:
        query = query.filter(Service.name_en.ilike(f"%{q}%") | Service.name_hi.ilike(f"%{q}%"))
    if category_id:
        query = query.filter(Service.category_id == category_id)
    services = query.order_by(Service.category_id, Service.name_en).all()
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    return render_template("admin/services_pricing.html", services=services,
                           categories=categories, q=q, category_id=category_id)


@admin_bp.route("/services/<int:service_id>/pricing", methods=["POST"])
@login_required
def service_pricing_update(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    try:
        service.service_charge = request.form.get("service_charge", 0, type=float)
        service.official_fee = request.form.get("official_fee", 0, type=float)
        service.other_charge = request.form.get("other_charge", 0, type=float)
    except ValueError:
        flash("Invalid price values.", "danger")
        return redirect(url_for("admin.services_pricing"))
    db.session.commit()
    log_admin_action(current_user, "service_pricing_updated", "service", service.id)
    db.session.commit()
    flash("Prices updated. Existing orders keep their checkout snapshot.", "success")
    return redirect(request.referrer or url_for("admin.services_pricing"))


@admin_bp.route("/services/availability")
@login_required
def services_availability():
    capability = (request.args.get("capability") or "").strip()
    query = Service.query.filter(Service.is_archived.is_(False))
    if capability:
        query = query.filter(Service.capability_type == capability)
    services = query.order_by(Service.capability_type, Service.name_en).all()
    counts = {value: Service.query.filter_by(capability_type=value).count()
              for value in CAPABILITY_TYPES}
    return render_template("admin/services_availability.html", services=services,
                           capability=capability, counts=counts,
                           capability_label=capability_label)


@admin_bp.route("/services/<int:service_id>/capability", methods=["POST"])
@login_required
def service_capability_update(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    new_cap = request.form.get("capability_type")
    if new_cap in CAPABILITY_TYPES:
        service.capability_type = new_cap
        db.session.commit()
        log_admin_action(current_user, "service_capability_updated", "service", service.id,
                         {"capability": new_cap})
        db.session.commit()
        flash(f"Capability set to {capability_label(new_cap)}.", "success")
    else:
        flash("Invalid capability type.", "danger")
    return redirect(request.referrer or url_for("admin.services_availability"))


# --------------------------------------------------------------------------
# Scholarship & welfare-scheme management (group-filtered service lists with
# scheme-year metadata)
# --------------------------------------------------------------------------

def _group_services_list(group, title):
    q = (request.args.get("q") or "").strip()
    query = (Service.query.join(ServiceCategory, Service.category_id == ServiceCategory.id)
             .filter(ServiceCategory.group == group, Service.is_archived.is_(False)))
    if q:
        query = query.filter(Service.name_en.ilike(f"%{q}%") | Service.name_hi.ilike(f"%{q}%"))
    services = query.order_by(Service.name_en).all()
    return render_template("admin/group_services.html", services=services, q=q,
                           group=group, title=title)


@admin_bp.route("/services/scholarships")
@login_required
def services_scholarships():
    return _group_services_list("scholarship", "Scholarship Management")


@admin_bp.route("/services/schemes")
@login_required
def services_schemes():
    return _group_services_list("scheme", "Government Scheme Management")


@admin_bp.route("/services/<int:service_id>/meta-year", methods=["POST"])
@login_required
def service_meta_year(service_id):
    """Record the scholarship/scheme year & application cycle on the service."""
    service = db.session.get(Service, service_id) or abort(404)
    meta = service.meta or {}
    meta["year"] = (request.form.get("year") or "").strip() or None
    meta["cycle"] = (request.form.get("cycle") or "").strip() or None
    meta["status_note"] = (request.form.get("status_note") or "").strip() or None
    service.meta = meta
    db.session.commit()
    log_admin_action(current_user, "service_meta_updated", "service", service.id)
    db.session.commit()
    flash("Scheme year/cycle saved. Remember: only advertise an application window that is officially open.",
          "success")
    return redirect(request.referrer or url_for("admin.services_scholarships"))
