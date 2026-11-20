"""CLI commands: admin bootstrap, demo data, staging cleanup, upload retry."""
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import click
from flask import current_app

from .extensions import db
from .models import AdminUser, ServiceCategory, Service, ServiceFormField, ServiceDocumentRequirement
from .models.settings import ensure_default_settings
from .utils.files import safe_stored_name


def register_cli(app):
    from .cli_catalogue import register_catalogue_cli
    register_catalogue_cli(app)

    @app.cli.command("create-admin")
    @click.option("--email", default=None, help="Admin email (else ADMIN_EMAIL env)")
    @click.option("--password", default=None, help="Password (else ADMIN_INITIAL_PASSWORD env)")
    @click.option("--name", default=None, help="Display name")
    def create_admin(email, password, name):
        """Create/update the first admin account from env or options."""
        email = (email or app.config["ADMIN_EMAIL"] or "").strip().lower()
        password = password or app.config["ADMIN_INITIAL_PASSWORD"] or ""
        if not email or not password:
            raise click.ClickException(
                "Provide ADMIN_EMAIL and ADMIN_INITIAL_PASSWORD in .env "
                "or pass --email/--password.")
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters.")
        user = AdminUser.query.filter_by(email=email).first()
        if user is None:
            user = AdminUser(email=email, name=name or app.config["ADMIN_NAME"])
            db.session.add(user)
            action = "created"
        else:
            action = "password updated for"
            if name:
                user.name = name
        user.set_password(password)
        user.is_active = True
        db.session.commit()
        click.echo(f"Admin account {action}: {email}")

    @app.cli.command("seed-demo")
    @click.option("--force", is_flag=True, help="Add demo data even if services exist")
    def seed_demo(force):
        """Insert sample categories/services with forms + document requirements."""
        count = Service.query.count()
        if count and not force:
            click.echo(f"Services already exist ({count}); skipping. Use --force to add anyway.")
            return
        ensure_default_settings()

        def get_category(name_en, name_hi, icon, sort):
            cat = ServiceCategory.query.filter_by(name_en=name_en).first()
            if cat is None:
                cat = ServiceCategory(slug=name_en.lower().replace(" ", "-")[:80],
                                      name_en=name_en, name_hi=name_hi, icon=icon,
                                      sort_order=sort)
                db.session.add(cat)
                db.session.flush()
            return cat

        pan_cat = get_category("PAN Card Services", "पैन कार्ड सेवाएँ", "bi-credit-card-2-front", 1)
        cert_cat = get_category("Certificates", "प्रमाणपत्र", "bi-award", 2)
        exam_cat = get_category("Government Job Applications", "सरकारी नौकरी आवेदन", "bi-briefcase", 3)
        private_cat = get_category("Private Services", "निजी सेवाएँ", "bi-building", 4)

        def add_service(cat, slug, name_en, name_hi, charge, official, fields, docs,
                        featured=False, time_en="3-7 working days", time_hi="3-7 कार्य दिवस"):
            svc = Service.query.filter_by(slug=slug).first()
            if svc:
                return svc
            svc = Service(
                category=cat, slug=slug, name_en=name_en, name_hi=name_hi,
                description_en=f"Apply for {name_en} through our centre. We fill the form, check documents and submit for you.",
                description_hi=f"हमारे केंद्र के माध्यम से {name_hi} के लिए आवेदन करें। हम फॉर्म भरने, दस्तावेज़ जाँचने और जमा करने में सहायता करते हैं।",
                instructions_en="Keep scanned copies ready: PDF/JPG, clear and readable.",
                instructions_hi="स्कैन कॉपी तैयार रखें: PDF/JPG, साफ़ और पढ़ने योग्य।",
                service_charge=charge, official_fee=official,
                processing_time_en=time_en, processing_time_hi=time_hi,
                is_active=True, is_featured=featured)
            db.session.add(svc)
            db.session.flush()
            for i, f in enumerate(fields, 1):
                db.session.add(ServiceFormField(
                    service=svc, field_key=f["key"], label_en=f["en"], label_hi=f.get("hi"),
                    field_type=f["type"], options=f.get("options"),
                    is_required=f.get("required", True), sort_order=i,
                    min_length=f.get("min_length"), max_length=f.get("max_length"),
                    allowed_extensions=f.get("allowed_extensions"), max_file_mb=f.get("max_file_mb")))
            for i, d in enumerate(docs, 1):
                db.session.add(ServiceDocumentRequirement(
                    service=svc, label_en=d["en"], label_hi=d.get("hi"),
                    is_required=d.get("required", True),
                    allow_multiple=d.get("multiple", False), sort_order=i))
            return svc

        add_service(pan_cat, "new-pan-card", "New PAN Card Application", "नया पैन कार्ड आवेदन",
                    150, 110,
                    [
                        {"key": "full_name", "type": "text", "en": "Applicant Full Name", "hi": "आवेदक का पूरा नाम", "min_length": 3, "max_length": 100},
                        {"key": "father_name", "type": "text", "en": "Father's Name", "hi": "पिता का नाम", "min_length": 3, "max_length": 100},
                        {"key": "dob", "type": "date", "en": "Date of Birth", "hi": "जन्म तिथि"},
                        {"key": "mobile", "type": "mobile", "en": "Mobile Number", "hi": "मोबाइल नंबर"},
                        {"key": "email", "type": "email", "en": "Email Address", "hi": "ईमेल पता", "required": False},
                        {"key": "gender", "type": "select", "en": "Gender", "hi": "लिंग", "options": [{"en": "Male", "hi": "पुरुष"}, {"en": "Female", "hi": "महिला"}, {"en": "Other", "hi": "अन्य"}]},
                        {"key": "address", "type": "textarea", "en": "Address", "hi": "पता", "max_length": 400},
                        {"key": "aadhaar_doc", "type": "file", "en": "Aadhaar Document", "hi": "आधार दस्तावेज़", "allowed_extensions": ["pdf", "jpg", "jpeg", "png"], "max_file_mb": 5},
                    ],
                    [
                        {"en": "Aadhaar document", "hi": "आधार दस्तावेज़"},
                        {"en": "Photograph (passport size)", "hi": "फोटो (पासपोर्ट साइज़)"},
                        {"en": "Signature", "hi": "हस्ताक्षर"},
                    ], featured=True)

        add_service(cert_cat, "income-certificate", "Income Certificate", "आय प्रमाणपत्र",
                    100, 30,
                    [
                        {"key": "applicant_name", "type": "text", "en": "Applicant Name", "hi": "आवेदक का नाम"},
                        {"key": "father_name", "type": "text", "en": "Father's Name", "hi": "पिता का नाम"},
                        {"key": "annual_income", "type": "number", "en": "Annual Income (INR)", "hi": "वार्षिक आय (₹)", "min_length": None},
                        {"key": "purpose", "type": "select", "en": "Purpose", "hi": "उद्देश्य", "options": [{"en": "Scholarship", "hi": "छात्रवृत्ति"}, {"en": "Admission", "hi": "प्रवेश"}, {"en": "Other", "hi": "अन्य"}]},
                        {"key": "address", "type": "textarea", "en": "Address", "hi": "पता"},
                    ],
                    [
                        {"en": "Identity document (Aadhaar/Voter ID)", "hi": "पहचान दस्तावेज़ (आधार/वोटर आईडी)"},
                        {"en": "Address proof", "hi": "पते का प्रमाण"},
                        {"en": "Income proof (salary slip/form)", "hi": "आय का प्रमाण"},
                    ])

        add_service(cert_cat, "caste-certificate", "Caste Certificate", "जाति प्रमाणपत्र",
                    100, 30,
                    [
                        {"key": "applicant_name", "type": "text", "en": "Applicant Name", "hi": "आवेदक का नाम"},
                        {"key": "father_name", "type": "text", "en": "Father's Name", "hi": "पिता का नाम"},
                        {"key": "caste", "type": "text", "en": "Caste", "hi": "जाति"},
                        {"key": "address", "type": "textarea", "en": "Address", "hi": "पता"},
                    ],
                    [
                        {"en": "Identity document", "hi": "पहचान दस्तावेज़"},
                        {"en": "Address proof", "hi": "पते का प्रमाण"},
                        {"en": "Father's caste certificate (if any)", "hi": "पिता का जाति प्रमाणपत्र (यदि हो)"},
                    ])

        add_service(exam_cat, "exam-application", "Examination Application Assistance", "परीक्षा आवेदन सहायता",
                    200, 0,
                    [
                        {"key": "candidate_name", "type": "text", "en": "Candidate Name", "hi": "अभ्यर्थी का नाम"},
                        {"key": "exam_name", "type": "text", "en": "Examination Name", "hi": "परीक्षा का नाम"},
                        {"key": "roll_pin", "type": "text", "en": "Preferred Exam Centre", "hi": "पसंदीदा परीक्षा केंद्र", "required": False},
                        {"key": "photo", "type": "image", "en": "Photograph", "hi": "फोटो", "allowed_extensions": ["jpg", "jpeg", "png"], "max_file_mb": 2},
                        {"key": "signature", "type": "image", "en": "Signature", "hi": "हस्ताक्षर", "allowed_extensions": ["jpg", "jpeg", "png"], "max_file_mb": 2},
                    ],
                    [
                        {"en": "Photograph", "hi": "फोटो"},
                        {"en": "Signature", "hi": "हस्ताक्षर"},
                        {"en": "Educational certificates", "hi": "शैक्षिक प्रमाणपत्र"},
                        {"en": "Category certificate (when applicable)", "hi": "श्रेणी प्रमाणपत्र (यदि लागू हो)", "required": False},
                    ], featured=True)

        add_service(private_cat, "printout-scan", "Printout & Scanning Service", "प्रिंटआउट एवं स्कैनिंग सेवा",
                    50, 0,
                    [
                        {"key": "details", "type": "textarea", "en": "What do you need printed/scanned?", "hi": "आपको क्या प्रिंट/स्कैन करना है?"},
                    ],
                    [
                        {"en": "Document file", "hi": "दस्तावेज़ फ़ाइल"},
                    ], time_en="Same day", time_hi="उसी दिन")

        db.session.commit()
        click.echo("Demo categories and services created.")

    @app.cli.command("cleanup-staging")
    def cleanup_staging():
        """Delete staged files older than STAGING_MAX_AGE_HOURS."""
        staging_dir = app.config["STAGING_DIR"]
        max_age = app.config["STAGING_MAX_AGE_HOURS"] * 3600
        removed = 0
        now = time.time()
        for dirpath, _dirnames, filenames in os.walk(staging_dir):
            for fname in filenames:
                path = os.path.join(dirpath, fname)
                try:
                    if now - os.path.getmtime(path) > max_age:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
        click.echo(f"Removed {removed} staged files older than "
                   f"{app.config['STAGING_MAX_AGE_HOURS']}h.")

    @app.cli.command("cleanup-wallet")
    @click.option("--max-age-hours", default=24 * 7, help="Delete wallet files older than this (default 7 days).")
    def cleanup_wallet(max_age_hours):
        """Delete wallet files whose session is long gone (sessions expire in hours)."""
        from .utils.customer_common import cleanup_wallet as _cleanup
        removed, kept = _cleanup(int(max_age_hours))
        click.echo(f"Removed {removed} wallet files; kept {kept}.")

    @app.cli.command("retry-uploads")
    def retry_uploads():
        """Retry all pending document uploads to the storage provider."""
        from .storage.documents import retry_pending_uploads
        ok, pending = retry_pending_uploads()
        click.echo(f"Uploaded: {ok}, still pending: {pending}")

    @app.cli.command("init-defaults")
    def init_defaults():
        """Insert default website settings (idempotent)."""
        ensure_default_settings()
        click.echo("Default website settings ensured.")
