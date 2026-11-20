"""Bilingual service search (English + Hindi + romanised Hindi).

Database-driven: ILIKE across both names, descriptions, keywords and admin
search aliases. "aay praman patra" and "आय प्रमाण पत्र" resolve to the same
Income Certificate service record — one service, many spellings. Exact alias
matches are returned first; anonymous term counters power "popular searches".
"""
from sqlalchemy import or_

from ..extensions import db
from ..models import Service, SearchAlias, SearchQueryStat
from .i18n import pick


def normalize(term: str) -> str:
    return " ".join((term or "").lower().split())


def _match_terms(term: str) -> list[str]:
    """Search tokens: the full phrase plus its individual words."""
    words = term.split()
    terms = [term] if len(words) <= 1 else [term, *words]
    return [t for t in terms if len(t) >= 2][:8]


def resolve_alias(term: str):
    """Exact-match alias -> (kind, target) or None. kind: service|category."""
    alias = SearchAlias.query.filter_by(alias=normalize(term)).first()
    if alias is None:
        return None
    if alias.service is not None:
        return ("service", alias.service)
    if alias.category is not None:
        return ("category", alias.category)
    return None


def search_services(query: str, category_id: int | None = None,
                    subcategory_id: int | None = None,
                    include_restricted: bool = True, limit: int | None = None):
    """Ordered search: alias hits, name starts-with, then substring matches."""
    term = normalize(query)
    base = Service.query.filter(Service.is_active.is_(True),
                                Service.is_archived.is_(False))
    if category_id:
        base = base.filter(Service.category_id == category_id)
    if subcategory_id:
        base = base.filter(Service.subcategory_id == subcategory_id)
    if not include_restricted:
        from ..models.service import CAPABILITY_RESTRICTED
        base = base.filter(Service.capability_type != CAPABILITY_RESTRICTED)

    if not term:
        return base.order_by(Service.sort_order, Service.id).limit(limit or 500).all()

    # 1) Exact alias hit takes priority (mapped service or category filter)
    alias = resolve_alias(term)
    if alias and alias[0] == "service":
        svc = alias[1]
        if svc.is_active and (include_restricted or not svc.is_restricted):
            rest = base.filter(Service.id != svc.id).all()
            return [svc, *rest][:limit or 500]
    if alias and alias[0] == "category":
        base = base.filter(Service.category_id == alias[1].id)

    terms = _match_terms(term)
    scored: list[tuple[int, int, Service]] = []
    for svc in base.all():
        haystacks = [svc.name_en or "", svc.name_hi or "",
                     svc.search_keywords or "", svc.description_en or "",
                     svc.description_hi or ""]
        hay = " ".join(h.lower() for h in haystacks)
        name_en = (svc.name_en or "").lower()
        name_hi = (svc.name_hi or "").lower()
        score = 0
        for t in terms:
            if t == name_en or t == name_hi or t in name_en.split() or t in name_hi.split():
                score -= 100
                break
        for t in terms:
            if t in hay:
                score -= 10
                if t in name_en or t in name_hi:
                    score -= 5
        if score < 0:
            scored.append((score, svc.id, svc))
    scored.sort(key=lambda row: (row[0], row[1]))
    services = [s for _, _, s in scored]
    return services[:limit] if limit else services


def suggest(query: str, limit: int = 8) -> list[dict]:
    """Lightweight suggestions for the search box (JSON)."""
    term = normalize(query)
    if len(term) < 2:
        return []
    services = search_services(term, include_restricted=False, limit=limit)
    return [{"slug": s.slug, "name_en": s.name_en, "name_hi": s.name_hi or "",
             "name": pick(s.name_en, s.name_hi),
             "category": pick(s.category.name_en, s.category.name_hi) if s.category else ""}
            for s in services]


def log_search_term(term: str) -> None:
    """Anonymous popularity counter (term only - never any identity data)."""
    clean = normalize(term)[:120]
    if len(clean) < 3:
        return
    stat = SearchQueryStat.query.filter_by(term=clean).first()
    if stat is None:
        stat = SearchQueryStat(term=clean, count=1)
        db.session.add(stat)
    else:
        stat.count = (stat.count or 0) + 1
        stat.last_searched_at = db.func.now()


def popular_searches(limit: int = 8) -> list[str]:
    rows = (SearchQueryStat.query.order_by(SearchQueryStat.count.desc())
            .limit(limit).all())
    return [r.term for r in rows if r.count > 0]
