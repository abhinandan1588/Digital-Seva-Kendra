"""Admin subcategory management (Part 7 module 2): two-level catalogue."""
from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import ServiceCategory, ServiceSubcategory, Service
from ..utils.audit import log_admin_action
from .catalog_admin import _slugify, _unique_slug


@admin_bp.route("/subcategories")
@login_required
def subcategories_list():
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    selected = request.args.get("category_id", type=int)
    query = ServiceSubcategory.query
    if selected:
        query = query.filter(ServiceSubcategory.category_id == selected)
    subcategories = query.order_by(ServiceSubcategory.category_id,
                                   ServiceSubcategory.sort_order, ServiceSubcategory.id).all()
    counts = {}
    for sub in subcategories:
        counts[sub.id] = Service.query.filter_by(subcategory_id=sub.id).count()
    return render_template("admin/subcategories_list.html", subcategories=subcategories,
                           categories=categories, selected=selected, counts=counts)


@admin_bp.route("/subcategories/new", methods=["GET", "POST"])
@login_required
def subcategory_create():
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    if request.method == "POST":
        name = (request.form.get("name_en") or "").strip()
        category_id = request.form.get("category_id", type=int)
        if not name or not category_id or not db.session.get(ServiceCategory, category_id):
            flash("Name and a valid category are required.", "danger")
            return render_template("admin/subcategory_form.html", subcategory=None,
                                   categories=categories)
        base = _slugify(name)
        slug = base
        n = 2
        while ServiceSubcategory.query.filter_by(category_id=category_id, slug=slug).first():
            slug = f"{base}-{n}"
            n += 1
        sub = ServiceSubcategory(
            category_id=category_id, slug=slug, name_en=name,
            name_hi=(request.form.get("name_hi") or "").strip() or None,
            description_en=(request.form.get("description_en") or "").strip() or None,
            description_hi=(request.form.get("description_hi") or "").strip() or None,
            icon=(request.form.get("icon") or "").strip() or None,
            is_active=bool(request.form.get("is_active")),
        )
        db.session.add(sub)
        db.session.commit()
        log_admin_action(current_user, "subcategory_created", "subcategory", sub.id)
        db.session.commit()
        flash("Subcategory created.", "success")
        return redirect(url_for("admin.subcategories_list"))
    return render_template("admin/subcategory_form.html", subcategory=None, categories=categories)


@admin_bp.route("/subcategories/<int:sub_id>/edit", methods=["GET", "POST"])
@login_required
def subcategory_edit(sub_id):
    sub = db.session.get(ServiceSubcategory, sub_id) or abort(404)
    categories = ServiceCategory.query.order_by(ServiceCategory.sort_order).all()
    if request.method == "POST":
        sub.name_en = (request.form.get("name_en") or "").strip() or sub.name_en
        sub.name_hi = (request.form.get("name_hi") or "").strip() or None
        sub.description_en = (request.form.get("description_en") or "").strip() or None
        sub.description_hi = (request.form.get("description_hi") or "").strip() or None
        sub.icon = (request.form.get("icon") or "").strip() or None
        sub.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        log_admin_action(current_user, "subcategory_updated", "subcategory", sub.id)
        db.session.commit()
        flash("Subcategory updated.", "success")
        return redirect(url_for("admin.subcategories_list"))
    return render_template("admin/subcategory_form.html", subcategory=sub, categories=categories)


@admin_bp.route("/subcategories/<int:sub_id>/move/<direction>", methods=["POST"])
@login_required
def subcategory_move(sub_id, direction):
    sub = db.session.get(ServiceSubcategory, sub_id) or abort(404)
    if direction == "up":
        sub.sort_order -= 1
    elif direction == "down":
        sub.sort_order += 1
    db.session.commit()
    return redirect(url_for("admin.subcategories_list"))


@admin_bp.route("/subcategories/<int:sub_id>/delete", methods=["POST"])
@login_required
def subcategory_delete(sub_id):
    sub = db.session.get(ServiceSubcategory, sub_id) or abort(404)
    if Service.query.filter_by(subcategory_id=sub.id).count() > 0:
        flash("This subcategory has services. Deactivate it instead to keep history safe.",
              "warning")
        return redirect(url_for("admin.subcategories_list"))
    db.session.delete(sub)
    db.session.commit()
    log_admin_action(current_user, "subcategory_deleted", "subcategory", sub_id)
    db.session.commit()
    flash("Subcategory deleted.", "success")
    return redirect(url_for("admin.subcategories_list"))
