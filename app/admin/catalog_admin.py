"""Admin catalogue management: categories, services, dynamic form builder,
and per-service document requirements - all without touching code."""
import json as _json
import os

from flask import (render_template, request, redirect, url_for, flash,
                   abort, current_app)
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import (ServiceCategory, Service, ServiceFormField,
                      ServiceDocumentRequirement, ServiceSubcategory, OfficialPortal)
from ..models.service import FIELD_TYPES, CAPABILITY_TYPES
from ..models.category import CATEGORY_GROUPS
from ..utils.audit import log_admin_action
from ..utils.files import allowed_extension, safe_stored_name
from ..utils.i18n import t


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out).strip("-")
    slug = "-".join(s for s in slug.split("-") if s)
    return slug or "item"


def _unique_slug(model, base: str, current_id=None) -> str:
    slug = base
    index = 2
    while True:
        row = model.query.filter_by(slug=slug).first()
        if row is None or (current_id and row.id == current_id):
            return slug
        slug = f"{base}-{index}"
        index += 1


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------

@admin_bp.route("/categories")
@login_required
def categories_list():
    categories = (ServiceCategory.query.order_by(ServiceCategory.sort_order,
                                                 ServiceCategory.id).all())
    sub_counts = {}
    for category in categories:
        sub_counts[category.id] = ServiceSubcategory.query.filter_by(
            category_id=category.id).count()
    return render_template("admin/categories_list.html", categories=categories,
                           sub_counts=sub_counts)


def _group_choices():
    return [(value, value.replace("_", " ").title()) for value in CATEGORY_GROUPS]


@admin_bp.route("/categories/new", methods=["GET", "POST"])
@login_required
def category_create():
    if request.method == "POST":
        name = (request.form.get("name_en") or "").strip()
        if not name:
            flash("English name is required.", "danger")
            return render_template("admin/category_form.html", category=None,
                                   groups=_group_choices())
        category = ServiceCategory(
            slug=_unique_slug(ServiceCategory, _slugify(name)),
            name_en=name,
            name_hi=(request.form.get("name_hi") or "").strip() or None,
            description_en=(request.form.get("description_en") or "").strip() or None,
            description_hi=(request.form.get("description_hi") or "").strip() or None,
            icon=(request.form.get("icon") or "").strip() or None,
            group=(request.form.get("group") or "other"),
            is_active=bool(request.form.get("is_active")),
        )
        _handle_image_upload(category)
        db.session.add(category)
        db.session.commit()
        log_admin_action(current_user, "category_created", "category", category.id)
        db.session.commit()
        flash("Category created.", "success")
        return redirect(url_for("admin.categories_list"))
    return render_template("admin/category_form.html", category=None, groups=_group_choices())


@admin_bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
def category_edit(category_id):
    category = db.session.get(ServiceCategory, category_id) or abort(404)
    if request.method == "POST":
        category.name_en = (request.form.get("name_en") or "").strip() or category.name_en
        category.name_hi = (request.form.get("name_hi") or "").strip() or None
        category.description_en = (request.form.get("description_en") or "").strip() or None
        category.description_hi = (request.form.get("description_hi") or "").strip() or None
        category.icon = (request.form.get("icon") or "").strip() or None
        category.group = request.form.get("group") or category.group
        category.is_active = bool(request.form.get("is_active"))
        _handle_image_upload(category)
        db.session.commit()
        log_admin_action(current_user, "category_updated", "category", category.id)
        db.session.commit()
        flash("Category updated.", "success")
        return redirect(url_for("admin.categories_list"))
    return render_template("admin/category_form.html", category=category,
                           groups=_group_choices())


@admin_bp.route("/categories/<int:category_id>/move/<direction>", methods=["POST"])
@login_required
def category_move(category_id, direction):
    category = db.session.get(ServiceCategory, category_id) or abort(404)
    if direction == "up":
        category.sort_order -= 1
    elif direction == "down":
        category.sort_order += 1
    db.session.commit()
    return redirect(url_for("admin.categories_list"))


@admin_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
def category_delete(category_id):
    category = db.session.get(ServiceCategory, category_id) or abort(404)
    has_services = category.services.count() > 0
    if has_services:
        # Historical safety: categories with services cannot be deleted.
        flash("This category has services. Deactivate it instead to keep history safe.",
              "warning")
        return redirect(url_for("admin.categories_list"))
    db.session.delete(category)
    db.session.commit()
    log_admin_action(current_user, "category_deleted", "category", category_id)
    db.session.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("admin.categories_list"))


def _handle_image_upload(obj):
    """Shared public image upload for categories/services/settings assets."""
    image = request.files.get("image")
    if image is None or not image.filename:
        return
    if not allowed_extension(image.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
        flash("Image must be PNG/JPG/WEBP.", "danger")
        return
    from ..utils.files import safe_stored_name
    ext = image.filename.rsplit(".", 1)[-1].lower()
    upload_dir = current_app.config["PUBLIC_UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    stored = safe_stored_name(ext)
    image.save(os.path.join(upload_dir, stored))
    obj.image_path = f"uploads/{stored}"


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

def _services_query_filters(query, args):
    q = (args.get("q") or "").strip()
    category_id = args.get("category_id", type=int)
    subcategory_id = args.get("subcategory_id", type=int)
    capability = (args.get("capability") or "").strip()
    show = (args.get("show") or "active").strip()  # active|archived|all
    if q:
        like = f"%{q}%"
        query = query.filter(Service.name_en.ilike(like) | Service.name_hi.ilike(like))
    if category_id:
        query = query.filter(Service.category_id == category_id)
    if subcategory_id:
        query = query.filter(Service.subcategory_id == subcategory_id)
    if capability:
        query = query.filter(Service.capability_type == capability)
    if show == "active":
        query = query.filter(Service.is_archived.is_(False))
    elif show == "archived":
        query = query.filter(Service.is_archived.is_(True))
    return query


@admin_bp.route("/services")
@login_required
def services_list():
    query = _services_query_filters(Service.query, request.args)
    services = query.order_by(Service.category_id, Service.sort_order, Service.id).all()
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    subcategories = ServiceSubcategory.query.order_by(ServiceSubcategory.sort_order).all()
    return render_template("admin/services_list.html", services=services,
                           categories=categories, subcategories=subcategories,
                           q=request.args.get("q", ""),
                           category_id=request.args.get("category_id", type=int),
                           subcategory_id=request.args.get("subcategory_id", type=int),
                           capability=request.args.get("capability", ""),
                           show=request.args.get("show", "active"))


@admin_bp.route("/services/popular")
@login_required
def services_popular():
    services = (Service.query.filter(Service.is_popular.is_(True),
                                     Service.is_archived.is_(False))
                .order_by(Service.category_id, Service.sort_order).all())
    return render_template("admin/services_list.html", services=services,
                           categories=ServiceCategory.query.order_by(ServiceCategory.sort_order).all(),
                           subcategories=ServiceSubcategory.query.all(),
                           q="", category_id=None, subcategory_id=None,
                           capability="", show="active", mode="popular")


@admin_bp.route("/services/featured")
@login_required
def services_featured():
    services = (Service.query.filter(Service.is_featured.is_(True),
                                     Service.is_archived.is_(False))
                .order_by(Service.category_id, Service.sort_order).all())
    return render_template("admin/services_list.html", services=services,
                           categories=ServiceCategory.query.order_by(ServiceCategory.sort_order).all(),
                           subcategories=ServiceSubcategory.query.all(),
                           q="", category_id=None, subcategory_id=None,
                           capability="", show="active", mode="featured")


@admin_bp.route("/services/new", methods=["GET", "POST"])
@login_required
def service_create():
    categories = ServiceCategory.query.filter_by(is_active=True).order_by(
        ServiceCategory.sort_order).all()
    subcategories = ServiceSubcategory.query.filter_by(is_active=True).order_by(
        ServiceSubcategory.sort_order).all()
    portals = OfficialPortal.query.filter_by(is_active=True).order_by(OfficialPortal.name_en).all()
    if request.method == "POST":
        name = (request.form.get("name_en") or "").strip()
        if not name:
            flash("English service name is required.", "danger")
            return render_template("admin/service_form.html", service=None, categories=categories,
                                   subcategories=subcategories, portals=portals)
        category_id = request.form.get("category_id", type=int)
        if not category_id or not db.session.get(ServiceCategory, category_id):
            flash("Please choose a valid category.", "danger")
            return render_template("admin/service_form.html", service=None, categories=categories,
                                   subcategories=subcategories, portals=portals)
        capability = request.form.get("capability_type") or "assisted_application"
        if capability not in CAPABILITY_TYPES:
            capability = "assisted_application"
        service = Service(
            category_id=category_id,
            subcategory_id=request.form.get("subcategory_id", type=int) or None,
            slug=_unique_slug(Service, _slugify(name)),
            name_en=name,
            name_hi=(request.form.get("name_hi") or "").strip() or None,
            description_en=(request.form.get("description_en") or "").strip() or None,
            description_hi=(request.form.get("description_hi") or "").strip() or None,
            instructions_en=(request.form.get("instructions_en") or "").strip() or None,
            instructions_hi=(request.form.get("instructions_hi") or "").strip() or None,
            eligibility_en=(request.form.get("eligibility_en") or "").strip() or None,
            eligibility_hi=(request.form.get("eligibility_hi") or "").strip() or None,
            icon=(request.form.get("icon") or "").strip() or None,
            search_keywords=(request.form.get("search_keywords") or "").strip() or None,
            official_info_url=(request.form.get("official_info_url") or "").strip() or None,
            capability_type=capability,
            official_portal_id=request.form.get("official_portal_id", type=int) or None,
            service_charge=request.form.get("service_charge", 0, type=float),
            official_fee=request.form.get("official_fee", 0, type=float),
            other_charge=request.form.get("other_charge", 0, type=float),
            processing_time_en=(request.form.get("processing_time_en") or "").strip() or None,
            processing_time_hi=(request.form.get("processing_time_hi") or "").strip() or None,
            is_active=bool(request.form.get("is_active")),
            is_featured=bool(request.form.get("is_featured")),
            is_popular=bool(request.form.get("is_popular")),
            is_examination=bool(request.form.get("is_examination")),
        )
        _handle_image_upload(service)
        db.session.add(service)
        db.session.commit()
        log_admin_action(current_user, "service_created", "service", service.id)
        db.session.commit()
        flash("Service created. Now build its form and document requirements.", "success")
        return redirect(url_for("admin.service_edit", service_id=service.id))
    return render_template("admin/service_form.html", service=None, categories=categories,
                           subcategories=subcategories, portals=portals)


@admin_bp.route("/services/<int:service_id>/edit", methods=["GET", "POST"])
@login_required
def service_edit(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    subcategories = ServiceSubcategory.query.order_by(ServiceSubcategory.sort_order).all()
    portals = OfficialPortal.query.filter_by(is_active=True).order_by(OfficialPortal.name_en).all()
    if request.method == "POST":
        service.category_id = request.form.get("category_id", type=service.category_id)
        service.subcategory_id = request.form.get("subcategory_id", type=int) or None
        service.name_en = (request.form.get("name_en") or "").strip() or service.name_en
        service.name_hi = (request.form.get("name_hi") or "").strip() or None
        service.description_en = (request.form.get("description_en") or "").strip() or None
        service.description_hi = (request.form.get("description_hi") or "").strip() or None
        service.instructions_en = (request.form.get("instructions_en") or "").strip() or None
        service.instructions_hi = (request.form.get("instructions_hi") or "").strip() or None
        service.eligibility_en = (request.form.get("eligibility_en") or "").strip() or None
        service.eligibility_hi = (request.form.get("eligibility_hi") or "").strip() or None
        service.icon = (request.form.get("icon") or "").strip() or None
        service.search_keywords = (request.form.get("search_keywords") or "").strip() or None
        service.official_info_url = (request.form.get("official_info_url") or "").strip() or None
        capability = request.form.get("capability_type") or service.capability_type
        service.capability_type = capability if capability in CAPABILITY_TYPES else service.capability_type
        service.official_portal_id = request.form.get("official_portal_id", type=int) or None
        service.service_charge = request.form.get("service_charge", 0, type=float)
        service.official_fee = request.form.get("official_fee", 0, type=float)
        service.other_charge = request.form.get("other_charge", 0, type=float)
        service.processing_time_en = (request.form.get("processing_time_en") or "").strip() or None
        service.processing_time_hi = (request.form.get("processing_time_hi") or "").strip() or None
        service.is_active = bool(request.form.get("is_active"))
        service.is_featured = bool(request.form.get("is_featured"))
        service.is_popular = bool(request.form.get("is_popular"))
        service.is_examination = bool(request.form.get("is_examination"))
        _handle_image_upload(service)
        db.session.commit()
        log_admin_action(current_user, "service_updated", "service", service.id)
        db.session.commit()
        flash("Service updated.", "success")
        return redirect(url_for("admin.service_edit", service_id=service.id))
    return render_template("admin/service_form.html", service=service, categories=categories,
                           subcategories=subcategories, portals=portals)


@admin_bp.route("/services/<int:service_id>/toggle", methods=["POST"])
@login_required
def service_toggle(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    service.is_active = not service.is_active
    db.session.commit()
    log_admin_action(current_user, "service_toggled", "service", service_id,
                     {"active": service.is_active})
    db.session.commit()
    flash(f"Service {'activated' if service.is_active else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin.services_list"))


@admin_bp.route("/services/<int:service_id>/toggle-popular", methods=["POST"])
@login_required
def service_toggle_popular(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    service.is_popular = not service.is_popular
    db.session.commit()
    log_admin_action(current_user, "service_popular_toggled", "service", service_id,
                     {"popular": service.is_popular})
    db.session.commit()
    return redirect(request.referrer or url_for("admin.services_popular"))


@admin_bp.route("/services/<int:service_id>/toggle-featured", methods=["POST"])
@login_required
def service_toggle_featured(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    service.is_featured = not service.is_featured
    db.session.commit()
    log_admin_action(current_user, "service_featured_toggled", "service", service_id,
                     {"featured": service.is_featured})
    db.session.commit()
    return redirect(request.referrer or url_for("admin.services_featured"))


@admin_bp.route("/services/<int:service_id>/archive", methods=["POST"])
@login_required
def service_archive(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    service.is_archived = not service.is_archived
    if service.is_archived:
        service.is_active = False  # archived services are never orderable
    db.session.commit()
    log_admin_action(current_user, "service_archived" if service.is_archived
                     else "service_unarchived", "service", service_id)
    db.session.commit()
    flash(f"Service {'archived - historical orders are kept intact' if service.is_archived else 'unarchived'}.",
          "success")
    return redirect(url_for("admin.services_list", show="archived" if service.is_archived else "active"))


@admin_bp.route("/services/<int:service_id>/duplicate", methods=["POST"])
@login_required
def service_duplicate(service_id):
    """Duplicate an existing service as an inactive template (variants)."""
    source = db.session.get(Service, service_id) or abort(404)
    copy = Service(
        category_id=source.category_id,
        subcategory_id=source.subcategory_id,
        slug=_unique_slug(Service, f"{source.slug}-copy"),
        name_en=f"{source.name_en} (Copy)",
        name_hi=source.name_hi,
        description_en=source.description_en,
        description_hi=source.description_hi,
        instructions_en=source.instructions_en,
        instructions_hi=source.instructions_hi,
        eligibility_en=source.eligibility_en,
        eligibility_hi=source.eligibility_hi,
        icon=source.icon,
        search_keywords=source.search_keywords,
        official_info_url=source.official_info_url,
        capability_type=source.capability_type,
        official_portal_id=source.official_portal_id,
        service_charge=source.service_charge,
        official_fee=source.official_fee,
        other_charge=source.other_charge,
        processing_time_en=source.processing_time_en,
        processing_time_hi=source.processing_time_hi,
        is_active=False,  # review before publishing
        is_examination=source.is_examination,
        is_popular=False, is_featured=False,
    )
    db.session.add(copy)
    db.session.flush()
    for field in source.form_fields.all():
        db.session.add(ServiceFormField(
            service=copy, field_key=field.field_key, label_en=field.label_en,
            label_hi=field.label_hi, field_type=field.field_type,
            placeholder=field.placeholder, help_text_en=field.help_text_en,
            help_text_hi=field.help_text_hi, options=field.options,
            is_required=field.is_required, min_length=field.min_length,
            max_length=field.max_length, min_value=field.min_value,
            max_value=field.max_value, allowed_extensions=field.allowed_extensions,
            max_file_mb=field.max_file_mb, sort_order=field.sort_order))
    for req in source.document_requirements.all():
        db.session.add(ServiceDocumentRequirement(
            service=copy, document_template_id=req.document_template_id,
            label_en=req.label_en, label_hi=req.label_hi,
            description_en=req.description_en, description_hi=req.description_hi,
            allowed_extensions=req.allowed_extensions, max_file_mb=req.max_file_mb,
            is_required=req.is_required, allow_multiple=req.allow_multiple,
            sort_order=req.sort_order))
    db.session.commit()
    log_admin_action(current_user, "service_duplicated", "service", copy.id,
                     {"from": service_id})
    db.session.commit()
    flash("Service duplicated as an INACTIVE copy. Review, rename, adjust prices, then activate it.",
          "success")
    return redirect(url_for("admin.service_edit", service_id=copy.id))


# --------------------------------------------------------------------------
# Dynamic form builder
# --------------------------------------------------------------------------

@admin_bp.route("/services/<int:service_id>/form")
@login_required
def form_builder(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    fields = service.form_fields.order_by(ServiceFormField.sort_order, ServiceFormField.id).all()
    return render_template("admin/form_builder.html", service=service, fields=fields)


@admin_bp.route("/services/<int:service_id>/form/add", methods=["GET", "POST"])
@login_required
def form_field_add(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    if request.method == "POST":
        error = _save_form_field(service)
        if error:
            flash(error, "danger")
            return render_template("admin/form_field_form.html", service=service,
                                   field=None, field_types=FIELD_TYPES)
        db.session.commit()
        flash("Field added.", "success")
        return redirect(url_for("admin.form_builder", service_id=service.id))
    return render_template("admin/form_field_form.html", service=service, field=None,
                           field_types=FIELD_TYPES)


@admin_bp.route("/services/<int:service_id>/form/<int:field_id>/edit", methods=["GET", "POST"])
@login_required
def form_field_edit(service_id, field_id):
    service = db.session.get(Service, service_id) or abort(404)
    field = db.session.get(ServiceFormField, field_id) or abort(404)
    if field.service_id != service.id:
        abort(404)
    if request.method == "POST":
        error = _save_form_field(service, field)
        if error:
            flash(error, "danger")
            return render_template("admin/form_field_form.html", service=service,
                                   field=field, field_types=FIELD_TYPES)
        db.session.commit()
        flash("Field updated.", "success")
        return redirect(url_for("admin.form_builder", service_id=service.id))
    return render_template("admin/form_field_form.html", service=service, field=field,
                           field_types=FIELD_TYPES)


def _parse_options(raw: str) -> list | None:
    """One option per line: `English | Hindi`. Stored as structured JSON."""
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return None
    options = []
    for line in lines:
        if "|" in line:
            en, hi = line.split("|", 1)
            options.append({"en": en.strip(), "hi": hi.strip()})
        else:
            options.append({"en": line, "hi": line})
    return options


def _save_form_field(service, field=None) -> str | None:
    label = (request.form.get("label_en") or "").strip()
    if not label:
        return "English label is required."
    ftype = request.form.get("field_type") or "text"
    if ftype not in FIELD_TYPES:
        return "Invalid field type."

    allowed = (request.form.get("allowed_extensions") or "").strip()
    allowed_list = [a.strip().lstrip(".").lower() for a in allowed.split(",") if a.strip()] \
        or (["jpg", "jpeg", "png", "webp"] if ftype == "image"
            else ["pdf", "jpg", "jpeg", "png"] if ftype in ("file", "file_multi") else None)

    is_new = field is None
    if is_new:
        field = ServiceFormField(service=service)
        existing_keys = {f.field_key for f in service.form_fields.all()}
        base_key = _slugify(label).replace("-", "_")[:50] or "field"
        key = base_key
        n = 2
        while key in existing_keys:
            key = f"{base_key}_{n}"
            n += 1
        field.field_key = key
        max_sort = db.session.query(db.func.max(ServiceFormField.sort_order)).filter_by(
            service_id=service.id).scalar() or 0
        field.sort_order = max_sort + 1

    field.label_en = label
    field.label_hi = (request.form.get("label_hi") or "").strip() or None
    field.field_type = ftype
    field.placeholder = (request.form.get("placeholder") or "").strip() or None
    field.help_text_en = (request.form.get("help_text_en") or "").strip() or None
    field.help_text_hi = (request.form.get("help_text_hi") or "").strip() or None
    field.options = _parse_options(request.form.get("options"))
    field.is_required = bool(request.form.get("is_required"))
    field.min_length = request.form.get("min_length", type=int)
    field.max_length = request.form.get("max_length", type=int)
    field.min_value = request.form.get("min_value", type=float)
    field.max_value = request.form.get("max_value", type=float)
    field.allowed_extensions = allowed_list
    field.max_file_mb = request.form.get("max_file_mb", type=int)
    field.is_active = bool(request.form.get("is_active"))
    db.session.add(field)
    return None


@admin_bp.route("/services/<int:service_id>/form/<int:field_id>/move/<direction>", methods=["POST"])
@login_required
def form_field_move(service_id, field_id, direction):
    field = db.session.get(ServiceFormField, field_id) or abort(404)
    if field.service_id != service_id:
        abort(404)
    if direction == "up":
        field.sort_order -= 1
    elif direction == "down":
        field.sort_order += 1
    db.session.commit()
    return redirect(url_for("admin.form_builder", service_id=service_id))


@admin_bp.route("/services/<int:service_id>/form/<int:field_id>/delete", methods=["POST"])
@login_required
def form_field_delete(service_id, field_id):
    field = db.session.get(ServiceFormField, field_id) or abort(404)
    if field.service_id != service_id:
        abort(404)
    db.session.delete(field)  # ON DELETE SET NULL keeps old answers
    db.session.commit()
    log_admin_action(current_user, "form_field_deleted", "form_field", field_id,
                     {"service": service_id})
    db.session.commit()
    flash("Field deleted. Previous applications keep their stored answers.", "info")
    return redirect(url_for("admin.form_builder", service_id=service_id))


@admin_bp.route("/services/<int:service_id>/form/preview")
@login_required
def form_preview(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    fields = service.active_form_fields
    requirements = service.active_document_requirements
    return render_template("admin/form_preview.html", service=service,
                           fields=fields, requirements=requirements)


# --------------------------------------------------------------------------
# Document requirements manager
# --------------------------------------------------------------------------

@admin_bp.route("/services/<int:service_id>/documents")
@login_required
def doc_requirements(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    requirements = service.document_requirements.order_by(
        ServiceDocumentRequirement.sort_order, ServiceDocumentRequirement.id).all()
    return render_template("admin/doc_requirements.html", service=service,
                           requirements=requirements)


@admin_bp.route("/services/<int:service_id>/documents/add", methods=["POST"])
@login_required
def doc_requirement_add(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    label = (request.form.get("label_en") or "").strip()
    if not label:
        flash("Document label is required.", "danger")
        return redirect(url_for("admin.doc_requirements", service_id=service.id))
    allowed = (request.form.get("allowed_extensions") or "").strip()
    allowed_list = [a.strip().lstrip(".").lower() for a in allowed.split(",") if a.strip()] \
        or ["pdf", "jpg", "jpeg", "png"]
    max_sort = db.session.query(db.func.max(ServiceDocumentRequirement.sort_order)).filter_by(
        service_id=service.id).scalar() or 0
    requirement = ServiceDocumentRequirement(
        service=service,
        label_en=label,
        label_hi=(request.form.get("label_hi") or "").strip() or None,
        description_en=(request.form.get("description_en") or "").strip() or None,
        description_hi=(request.form.get("description_hi") or "").strip() or None,
        allowed_extensions=allowed_list,
        max_file_mb=request.form.get("max_file_mb", 5, type=int),
        is_required=bool(request.form.get("is_required")),
        allow_multiple=bool(request.form.get("allow_multiple")),
        sort_order=max_sort + 1,
    )
    db.session.add(requirement)
    db.session.commit()
    flash("Document requirement added.", "success")
    return redirect(url_for("admin.doc_requirements", service_id=service.id))


@admin_bp.route("/services/<int:service_id>/documents/<int:req_id>/delete", methods=["POST"])
@login_required
def doc_requirement_delete(service_id, req_id):
    service = db.session.get(Service, service_id) or abort(404)
    requirement = db.session.get(ServiceDocumentRequirement, req_id) or abort(404)
    if requirement.service_id != service.id:
        abort(404)
    db.session.delete(requirement)
    db.session.commit()
    flash("Document requirement removed.", "info")
    return redirect(url_for("admin.doc_requirements", service_id=service.id))


@admin_bp.route("/services/<int:service_id>/documents/<int:req_id>/move/<direction>", methods=["POST"])
@login_required
def doc_requirement_move(service_id, req_id, direction):
    requirement = db.session.get(ServiceDocumentRequirement, req_id) or abort(404)
    if requirement.service_id != service_id:
        abort(404)
    if direction == "up":
        requirement.sort_order -= 1
    elif direction == "down":
        requirement.sort_order += 1
    db.session.commit()
    return redirect(url_for("admin.doc_requirements", service_id=service_id))
