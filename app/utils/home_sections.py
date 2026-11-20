"""Homepage sections (Part 12) built from the database - never hardcoded.

Every section is a dict {key, title_en, title_hi, icon, url, kind, items}.
Service items are Service rows; cycle items are ExamCycle rows (verified
notifications only). Sections whose categories/services do not exist yet
simply render empty - the homepage is data-driven from the start.
"""
from ..models import ServiceCategory, Service, ServiceSubcategory, ExamCycle
from ..utils.exams import refresh_all_cycle_statuses, today
from flask import url_for


def _cat(slug: str) -> ServiceCategory | None:
    return ServiceCategory.query.filter_by(slug=slug, is_active=True).first()


def _services_for_category(category_id: int, limit: int = 8) -> list:
    return (Service.query.filter(Service.is_active.is_(True),
                                 Service.is_archived.is_(False),
                                 Service.category_id == category_id)
            .order_by(Service.is_popular.desc(), Service.sort_order, Service.id)
            .limit(limit).all())


def _services_for_subcategories(sub_slugs: list[str], limit: int = 8) -> list:
    subs = (ServiceSubcategory.query.filter(ServiceSubcategory.slug.in_(sub_slugs),
                                            ServiceSubcategory.is_active.is_(True)).all())
    ids = [s.id for s in subs]
    if not ids:
        return []
    return (Service.query.filter(Service.is_active.is_(True),
                                 Service.is_archived.is_(False),
                                 Service.subcategory_id.in_(ids))
            .order_by(Service.sort_order, Service.id).limit(limit).all())


def build_home_sections() -> dict:
    refresh_all_cycle_statuses()
    sections = []

    def section(key, title_en, title_hi, icon, url, kind, items, slug=None):
        if slug:
            href = url_for(url, slug=slug)
        elif "category_page" in url:  # category not seeded yet -> fall back
            href = url_for("services.catalogue")
        else:
            href = url_for(url)
        sections.append({"key": key, "title_en": title_en, "title_hi": title_hi,
                         "icon": icon, "url": href, "kind": kind, "cards": items})

    # 1. Popular government documents & identity services
    doc_cat = _cat("government-certificates-documents")
    id_cat = _cat("identity-card-services")
    popular = (Service.query.filter(Service.is_active.is_(True),
                                    Service.is_archived.is_(False),
                                    Service.is_popular.is_(True))
               .order_by(Service.sort_order, Service.id).limit(8).all())
    if not popular and (doc_cat or id_cat):
        pool = []
        for cat in (doc_cat, id_cat):
            if cat:
                pool += _services_for_category(cat.id, 4)
        popular = pool
    section("popular_documents", "Popular Government Documents", "लोकप्रिय सरकारी दस्तावेज़",
            "bi-award", "services.catalogue", "services", popular)

    # 2. Bihar RTPS services (official ServicePlus/RTPS portal services)
    rtps = []
    if doc_cat:
        rtps = (Service.query.filter(Service.is_active.is_(True),
                                     Service.is_archived.is_(False),
                                     Service.category_id == doc_cat.id,
                                     Service.official_portal_id.isnot(None))
                .order_by(Service.is_popular.desc(), Service.sort_order, Service.id)
                .limit(8).all())
    section("bihar_rtps", "Bihar RTPS Services", "बिहार आरटीपीएस सेवाएँ",
            "bi-bank", "category.category_page", "services", rtps, slug=doc_cat.slug if doc_cat else None)

    # 3. Government job applications (exam service templates)
    job_services = (Service.query.filter(Service.is_active.is_(True),
                                         Service.is_archived.is_(False),
                                         Service.is_examination.is_(True))
                    .order_by(Service.is_popular.desc(), Service.sort_order)
                    .limit(8).all())
    section("govt_jobs", "Government Job Applications", "सरकारी नौकरी आवेदन",
            "bi-briefcase", "exams.exam_list", "services", job_services)

    # 4. Latest recruitment notifications (open cycles, closest deadline first)
    from ..utils.exams import deadline_info
    open_cycles = (ExamCycle.query.filter(ExamCycle.is_published.is_(True),
                                          ExamCycle.is_archived.is_(False),
                                          ExamCycle.exam_status == "open")
                   .order_by(ExamCycle.application_last_date.asc().nullslast())
                   .limit(6).all())
    section("latest_notifications", "Latest Recruitment Notifications", "नवीनतम भर्ती अधिसूचनाएँ",
            "bi-megaphone", "exams.exam_list", "cycles",
            [{"cycle": c, "info": deadline_info(c)} for c in open_cycles])

    # 5. Upcoming examinations (exam date in the future)
    upcoming = (ExamCycle.query.filter(ExamCycle.is_published.is_(True),
                                       ExamCycle.is_archived.is_(False),
                                       ExamCycle.exam_date.isnot(None),
                                       ExamCycle.exam_date >= today())
                .order_by(ExamCycle.exam_date.asc()).limit(6).all())
    section("upcoming_exams", "Upcoming Examinations", "आगामी परीक्षाएँ",
            "bi-calendar2-week", "exams.exam_list", "cycles",
            [{"cycle": c, "info": deadline_info(c)} for c in upcoming])

    # 6. Entrance examinations (national + Bihar)
    entrance = _services_for_subcategories(
        ["engineering-entrance", "medical-entrance", "university-entrance",
         "management-entrance", "bceceb-examinations"], 8)
    section("entrance", "Entrance Examinations", "प्रवेश परीक्षाएँ",
            "bi-pencil-square", "services.catalogue", "services", entrance)

    # 7. Scholarships / 8. Admissions
    sch = _cat("scholarship-applications")
    section("scholarships", "Scholarship Services", "छात्रवृत्ति सेवाएँ",
            "bi-prescription2", "category.category_page", "services",
            _services_for_category(sch.id, 8) if sch else [], slug=sch.slug if sch else None)
    edu = _cat("education-admission-services")
    section("admissions", "Admission Services", "प्रवेश सेवाएँ",
            "bi-mortarboard", "category.category_page", "services",
            _services_for_category(edu.id, 8) if edu else [], slug=edu.slug if edu else None)

    # 9-11. Digital / photo & PDF / computer services
    dig = _cat("digital-document-computer-services")
    section("digital", "Digital Document Services", "डिजिटल दस्तावेज़ सेवाएँ",
            "bi-printer", "category.category_page", "services",
            _services_for_category(dig.id, 8) if dig else [], slug=dig.slug if dig else None)
    section("photo_pdf", "Photo & PDF Tools", "फोटो एवं पीडीएफ टूल",
            "bi-images", "category.category_page", "services",
            _services_for_subcategories(["photo-signature", "pdf-tools"], 8), slug=dig.slug if dig else None)
    section("computer", "Popular Computer Services", "लोकप्रिय कंप्यूटर सेवाएँ",
            "bi-pc-display", "category.category_page", "services",
            _services_for_subcategories(["computer-services"], 8), slug=dig.slug if dig else None)

    # 12. Welfare schemes
    schemes = _cat("government-welfare-schemes")
    section("schemes", "Government Welfare Schemes", "सरकारी कल्याणकारी योजनाएँ",
            "bi-heart-pulse", "category.category_page", "services",
            _services_for_category(schemes.id, 8) if schemes else [], slug=schemes.slug if schemes else None)

    return {"sections": sections,
            "has_notifications": bool(open_cycles or upcoming)}
