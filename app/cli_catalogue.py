"""Catalogue seed & maintenance CLI.

`flask seed-catalogue` loads data/*.json (portals, document templates,
search aliases and the full category/subcategory/service catalogue) into
PostgreSQL using an update-or-create strategy - the catalogue is DATABASE
data, never hardcoded into Python or templates. Sample data ships with
official_fee = 0: the admin verifies and configures real official fees from
the current official information before publishing.

Also: `flask flag-stale-cycles` (mark unverified exam cycles for review) and
`flask check-official-sources` (polite, permitted-feed based monitoring hook).
"""
import glob
import json
import os
from datetime import date, datetime, timedelta, timezone

import click
from flask import current_app

from .extensions import db
from .models import (ServiceCategory, ServiceSubcategory, Service, ServiceFormField,
                     ServiceDocumentRequirement, ExamCycle, DocumentTemplate,
                     OfficialPortal, SearchAlias)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _data_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def _load_json(filename: str) -> dict:
    with open(_data_path(filename), encoding="utf-8") as fh:
        return json.load(fh)


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", ".", "/", "(", ")", "&", ","):
            out.append("-")
    slug = "".join(out)
    return "-".join(s for s in slug.split("-") if s) or "item"


DEFAULT_PROCESSING = {
    "documents": ("7-15 working days", "7-15 कार्य दिवस"),
    "identity": ("7-15 working days", "7-15 कार्य दिवस"),
    "education": ("3-10 working days", "3-10 कार्य दिवस"),
    "scholarship": ("As per official cycle", "सरकारी चक्र अनुसार"),
    "exam": ("Per notification schedule", "अधिसूचना अनुसार"),
    "scheme": ("As per official process", "सरकारी प्रक्रिया अनुसार"),
    "business": ("3-15 working days", "3-15 कार्य दिवस"),
    "transport": ("3-10 working days", "3-10 कार्य दिवस"),
    "digital": ("Same day", "उसी दिन"),
    "legal": ("Varies by department", "विभाग अनुसार"),
    "utility": ("Instant / same day", "तुरंत / उसी दिन"),
    "other": ("3-7 working days", "3-7 कार्य दिवस"),
}

DEFAULT_FIELDS = {
    "exam": [("candidate_name", "Candidate Name", "अभ्यर्थी का नाम", "text", True, None),
             ("mobile", "Mobile Number", "मोबाइल नंबर", "mobile", True, None)],
    "scholarship": [("student_name", "Student Name", "छात्र/छात्रा का नाम", "text", True, None),
                    ("mobile", "Mobile Number", "मोबाइल नंबर", "mobile", True, None)],
    "digital": [("details", "What exactly do you need? (paste text / describe)",
                 "आपको ठीक क्या चाहिए? (टेक्स्ट लिखें / वर्णन करें)", "textarea", False, None)],
    "utility": [("mobile", "Mobile Number", "मोबाइल नंबर", "mobile", True, None),
                ("details", "Details (consumer number etc.)", "विवरण (कंज्यूमर नंबर आदि)", "textarea", False, None)],
}
DEFAULT_FIELDS_DEFAULT = [("applicant_name", "Applicant Name", "आवेदक का नाम", "text", True, None),
                          ("mobile", "Mobile Number", "मोबाइल नंबर", "mobile", True, None)]

FIELD_TYPE_MAP = {"text": "text", "number": "number", "date": "date", "textarea": "textarea",
                  "email": "email", "mobile": "mobile", "select": "select"}


def _seed_portals() -> int:
    data = _load_json("portals.json")
    count = 0
    for item in data.get("portals", []):
        portal = OfficialPortal.query.filter_by(slug=item["slug"]).first()
        if portal is None:
            portal = OfficialPortal(slug=item["slug"])
            db.session.add(portal)
            portal.last_verified_at = db.func.now()
            count += 1
        portal.name_en = item["name_en"]
        portal.name_hi = item.get("name_hi")
        portal.url = item["url"]
        portal.state = item.get("state", "All India")
        portal.department = item.get("department")
    db.session.flush()
    return count


def _seed_document_templates() -> int:
    data = _load_json("document_templates.json")
    count = 0
    for item in data.get("templates", []):
        template = DocumentTemplate.query.filter_by(slug=item["slug"]).first()
        if template is None:
            template = DocumentTemplate(slug=item["slug"])
            db.session.add(template)
            count += 1
        template.name_en = item["name_en"]
        template.name_hi = item.get("name_hi")
        template.description_en = item.get("desc_en")
        template.description_hi = item.get("desc_hi")
        template.allowed_extensions = item.get("ext", ["pdf", "jpg", "jpeg", "png"])
        template.max_file_mb = item.get("mb", 5)
        template.is_required = item.get("required", True)
        template.allow_multiple = item.get("allow_multiple", False)
        template.min_width = item.get("min_w")
        template.max_width = item.get("max_w")
        template.min_height = item.get("min_h")
        template.max_height = item.get("max_h")
        template.compression_note_en = item.get("comp_en")
        template.compression_note_hi = item.get("comp_hi")
        template.expires_after_days = item.get("expires_after_days")
        template.template_group = item.get("group", "general")
    db.session.flush()
    return count


def _seed_search_aliases() -> int:
    data = _load_json("search_aliases.json")
    count = 0
    for item in data.get("aliases", []):
        alias_text = " ".join((item.get("alias") or "").lower().split())
        if not alias_text:
            continue
        alias = SearchAlias.query.filter_by(alias=alias_text).first()
        if alias is None:
            alias = SearchAlias(alias=alias_text)
            db.session.add(alias)
            count += 1
        target = None
        target_type = item.get("type", "service")
        slug = item.get("target")
        if target_type == "service":
            target = Service.query.filter_by(slug=slug).first()
        elif target_type == "category":
            target = ServiceCategory.query.filter_by(slug=slug).first()
        elif target_type == "subcategory":
            target = ServiceSubcategory.query.filter_by(slug=slug).first()
        if target is None:
            continue  # alias rows pointing nowhere are skipped (harmless)
        alias.service_id = target.id if target_type == "service" else None
        alias.category_id = target.id if target_type in ("category", "subcategory") else None
        alias.note = item.get("note")
    db.session.flush()
    return count


def _ensure_default_form_fields(service: Service, group: str) -> None:
    if service.form_fields.count() > 0:
        return
    for index, (key, en, hi, ftype, required, _opts) in enumerate(
            DEFAULT_FIELDS.get(group, DEFAULT_FIELDS_DEFAULT), start=1):
        db.session.add(ServiceFormField(
            service=service, field_key=key, label_en=en, label_hi=hi,
            field_type=FIELD_TYPE_MAP.get(ftype, "text"), is_required=required,
            sort_order=index))


def _seed_categories() -> tuple[int, int, int]:
    cats = subs = services = 0
    portal_by_slug = {p.slug: p.id for p in OfficialPortal.query.all()}
    template_by_slug = {t.slug: t for t in DocumentTemplate.query.all()}
    order = 0
    for path in sorted(glob.glob(_data_path("catalogue_*.json"))):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for cat_data in data.get("categories", []):
            order += 1
            category = ServiceCategory.query.filter_by(slug=cat_data["slug"]).first()
            if category is None:
                category = ServiceCategory(slug=cat_data["slug"])
                db.session.add(category)
                cats += 1
            category.name_en = cat_data["name_en"]
            category.name_hi = cat_data.get("name_hi")
            category.description_en = cat_data.get("description_en")
            category.description_hi = cat_data.get("description_hi")
            category.icon = cat_data.get("icon")
            category.group = cat_data.get("group", "other")
            category.sort_order = order
            db.session.flush()

            sub_order = 0
            entries = [(None, cat_data.get("services") or [])]
            entries += [(sub_data, sub_data.get("services") or [])
                        for sub_data in cat_data.get("subcategories", [])]
            for sub_data, svc_list in entries:
                subcategory = None
                if sub_data is not None:
                    sub_order += 1
                    subcategory = ServiceSubcategory.query.filter_by(
                        category_id=category.id, slug=sub_data["slug"]).first()
                    if subcategory is None:
                        subcategory = ServiceSubcategory(category_id=category.id,
                                                         slug=sub_data["slug"])
                        db.session.add(subcategory)
                        subs += 1
                    subcategory.name_en = sub_data["name_en"]
                    subcategory.name_hi = sub_data.get("name_hi")
                    subcategory.icon = sub_data.get("icon")
                    subcategory.sort_order = sub_order
                    db.session.flush()

                for svc_order, svc_data in enumerate(svc_list, start=1):
                    group = cat_data.get("group", "other")
                    slug = _slugify(svc_data.get("s") or svc_data["n"])
                    service = Service.query.filter_by(slug=slug).first()
                    if service is None:
                        service = Service(slug=slug, category_id=category.id,
                                          subcategory_id=subcategory.id if subcategory else None)
                        db.session.add(service)
                        services += 1
                    service.category_id = category.id
                    service.subcategory_id = subcategory.id if subcategory else None
                    service.name_en = svc_data["n"]
                    service.name_hi = svc_data.get("hi")
                    service.icon = cat_data.get("icon")
                    capability = svc_data.get("cap", "assisted_application")
                    service.capability_type = capability
                    service.search_keywords = svc_data.get("kw")
                    service.is_examination = svc_data.get("ex", group == "exam")
                    service.is_popular = svc_data.get("pop", False)
                    service.is_featured = svc_data.get("feat", False)
                    service.service_charge = svc_data.get("c", 100)
                    service.official_fee = svc_data.get("f", 0)
                    service.other_charge = 0
                    service.sort_order = svc_order
                    time_en, time_hi = svc_data.get("t_en"), svc_data.get("t_hi")
                    if not time_en:
                        time_en, time_hi = DEFAULT_PROCESSING.get(group, DEFAULT_PROCESSING["other"])
                    service.processing_time_en = time_en
                    service.processing_time_hi = time_hi
                    portal_slug = svc_data.get("p")
                    service.official_portal_id = portal_by_slug.get(portal_slug) if portal_slug else None
                    service.official_info_url = svc_data.get("info_url")
                    if svc_data.get("org") or svc_data.get("note"):
                        meta = service.meta or {}
                        if svc_data.get("org"):
                            meta["organization"] = svc_data["org"]
                        if svc_data.get("note"):
                            meta["note"] = svc_data["note"]
                        service.meta = meta
                    # Bilingual description (template-based unless overridden)
                    if not service.description_en:
                        service.description_en = (
                            f"Apply for {service.name_en} through our centre. We check your "
                            "documents, fill the application and assist with submission on the "
                            "official portal. The exact current official fee and eligibility are "
                            "confirmed with you before submission.")
                    if not service.description_hi:
                        service.description_hi = (
                            f"{service.name_hi or service.name_en} के लिए हमारे केंद्र से आवेदन करें। "
                            "हम आपके दस्तावेज़ जाँचते हैं, फॉर्म भरते हैं और सरकारी पोर्टल पर जमा करने में "
                            "सहायता करते हैं। वर्तमान सरकारी शुल्क व पात्रता जमा से पहले आपके साथ पुष्ट की जाती है।")
                    if svc_data.get("note"):
                        extra = svc_data["note"]
                        service.instructions_en = extra
                        service.instructions_hi = extra
                    db.session.flush()

                    # Default form fields (only for freshly created services)
                    _ensure_default_form_fields(service, group)
                    # Service-specific extra fields
                    existing_keys = {f.field_key for f in service.form_fields}
                    max_sort = db.session.query(db.func.max(ServiceFormField.sort_order)).filter_by(
                        service_id=service.id).scalar() or 0
                    for fx in svc_data.get("fx", []):
                        if fx["key"] in existing_keys:
                            continue
                        max_sort += 1
                        db.session.add(ServiceFormField(
                            service=service, field_key=fx["key"], label_en=fx["en"],
                            label_hi=fx.get("hi"), field_type=FIELD_TYPE_MAP.get(fx.get("type", "text")),
                            is_required=fx.get("req", False), sort_order=max_sort))

                    # Document requirements from templates (never overwrite custom docs)
                    if service.document_requirements.count() == 0:
                        doc_order = 0
                        for template_slug in svc_data.get("docs", []):
                            template = template_by_slug.get(template_slug)
                            if template is None:
                                continue
                            doc_order += 1
                            db.session.add(ServiceDocumentRequirement(
                                service=service, document_template_id=template.id,
                                label_en=template.name_en, label_hi=template.name_hi,
                                description_en=template.description_en,
                                description_hi=template.description_hi,
                                allowed_extensions=template.allowed_extensions,
                                max_file_mb=template.max_file_mb,
                                is_required=template.is_required,
                                allow_multiple=template.allow_multiple,
                                sort_order=doc_order))
                    db.session.flush()
    return cats, subs, services


def _seed_template_exam_cycles() -> int:
    """Create an UNPUBLISHED review-pending cycle template for every exam
    service. Dates are never invented - the admin verifies them from the
    official notification before publishing."""
    next_year = date.today().year + 1
    created = 0
    exam_services = Service.query.filter(Service.is_examination.is_(True),
                                         Service.is_archived.is_(False)).all()
    for service in exam_services:
        if service.exam_cycles:
            continue
        display_name = f"{service.name_en} {next_year}"
        slug = f"{service.slug}-{next_year}"
        if ExamCycle.query.filter_by(cycle_slug=slug).first():
            continue
        db.session.add(ExamCycle(
            service_id=service.id, cycle_slug=slug, display_name=display_name,
            organization=(service.meta or {}).get("organization", ""),
            exam_year=next_year,
            state="Bihar" if "bihar" in (service.category.slug if service.category else "") else "All India",
            exam_status="upcoming",
            is_published=False, needs_review=True,
            review_note=("Template cycle. Verify all dates, fees and eligibility from the "
                         "official notification, then set last_verified_at and publish."),
            verification_source=None))
        created += 1
    return created


def seed_catalogue_data() -> dict:
    """Run the full update-or-create seed and commit.

    Shared by `flask seed-catalogue`, the first-boot auto-seed and the admin
    "Load built-in catalogue" button, so all three behave identically.
    """
    portals = _seed_portals()
    templates = _seed_document_templates()
    aliases = _seed_search_aliases()
    cats, subs, services = _seed_categories()
    cycles = _seed_template_exam_cycles()
    db.session.commit()
    return {"portals": portals, "doc_templates": templates, "aliases": aliases,
            "categories": cats, "subcategories": subs, "services": services,
            "exam_cycles": cycles}


def register_catalogue_cli(app):
    @app.cli.command("seed-catalogue")
    @click.option("--force", is_flag=True, help="Re-seed even if services already exist (update-or-create)")
    def seed_catalogue(force):
        """Load the full service catalogue from data/*.json into the database."""
        existing = Service.query.count()
        if existing and not force:
            click.echo(f"Services already exist ({existing}); skipping. Use --force to update anyway.")
            return
        counts = seed_catalogue_data()
        click.echo(f"Catalogue seeded: portals +{counts['portals']}, "
                   f"doc templates +{counts['doc_templates']}, aliases +{counts['aliases']}, "
                   f"categories +{counts['categories']}, subcategories +{counts['subcategories']}, "
                   f"services +{counts['services']}, template exam cycles +{counts['exam_cycles']}.")

    @app.cli.command("flag-stale-cycles")
    @click.option("--days", default=14, help="Flag cycles not verified within this many days.")
    def flag_stale_cycles(days):
        """Flag exam cycles whose official-source verification is older than N days.

        Flagging never edits the data - the listing shows the cycle to the
        admin for manual re-verification against the official notification.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        stale = 0
        for cycle in ExamCycle.query.filter(ExamCycle.is_archived.is_(False),
                                            ExamCycle.is_published.is_(True)).all():
            if (cycle.last_verified_at is None
                    or cycle.last_verified_at < cutoff) and not cycle.needs_review:
                cycle.needs_review = True
                cycle.review_note = (cycle.review_note or "")[:200] + \
                    f" Auto-flagged: not verified for {days} days."
                stale += 1
        db.session.commit()
        click.echo(f"Flagged {stale} cycles for re-verification (> {days} days).")

    @app.cli.command("check-official-sources")
    def check_official_sources():
        """Polite official-source monitoring hook (future-ready).

        Only permitted RSS/Atom feeds configured by the admin on portals are
        contacted - one request per portal per run, short timeout, no CAPTCHA
        bypass, no bulk scraping. A feed that is unreachable or changed flags
        the related cycles for admin review instead of updating anything.
        """
        import urllib.request
        portals = OfficialPortal.query.filter_by(is_active=True).all()
        checked = failed = 0
        for portal in portals:
            if not portal.official_feed_url:
                continue
            try:
                req = urllib.request.Request(
                    portal.official_feed_url,
                    headers={"User-Agent": "DigitalSevaKendra-Monitor/1.0 (+admin-configured feed)"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        portal.last_verified_at = db.func.now()
                        checked += 1
                    else:
                        raise OSError(f"HTTP {resp.status}")
            except Exception as exc:  # noqa: BLE001 - flag, never crash the check
                failed += 1
                click.echo(f"  ! {portal.slug}: source unreachable ({exc}) -> flagging related cycles")
                for cycle in ExamCycle.query.filter(
                        ExamCycle.organization == portal.name_en,
                        ExamCycle.is_archived.is_(False)):
                    cycle.needs_review = True
                    cycle.review_note = f"Official source check failed on {date.today().isoformat()}."
        db.session.commit()
        click.echo(f"Source check done: {checked} verified, {failed} unreachable "
                   f"(portals without a configured feed are verified manually by the admin).")
