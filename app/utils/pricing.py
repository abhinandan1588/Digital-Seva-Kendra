"""Server-side pricing. The single source of truth for money in this app.

Prices always come from the database - anything the browser sends is
ignored - and are snapshotted into order_items at checkout.
"""
from decimal import Decimal

from ..extensions import db
from ..models import Service


def price_services(service_ids: list[int]) -> dict:
    """Return {service_id: service} for a list of ids."""
    ids = [int(i) for i in service_ids]
    services = db.session.query(Service).filter(Service.id.in_(ids)).all()
    return {s.id: s for s in services}


def cart_totals(items: list[dict]) -> dict:
    """Compute totals for a cart of {'key','service_id'} items from DB prices.

    Returns detailed breakdown. Inactive/missing services raise ValueError so
    a stale cart cannot be checked out with wrong prices.
    """
    service_ids = [i["service_id"] for i in items]
    services = price_services(service_ids)
    lines = []
    for item in items:
        service = services.get(item["service_id"])
        if service is None or not service.is_active:
            raise ValueError(f"Service {item['service_id']} is unavailable.")
        service_charge = Decimal(service.service_charge or 0)
        official_fee = Decimal(service.official_fee or 0)
        other_charge = Decimal(service.other_charge or 0)
        line_total = service_charge + official_fee + other_charge
        lines.append({
            "item": item,
            "service": service,
            "service_charge": service_charge,
            "official_fee": official_fee,
            "other_charge": other_charge,
            "line_total": line_total,
        })
    totals = {
        "lines": lines,
        "service_charges_total": sum(l["service_charge"] for l in lines),
        "official_fees_total": sum(l["official_fee"] for l in lines),
        "other_charges_total": sum(l["other_charge"] for l in lines),
    }
    totals["total"] = (
        totals["service_charges_total"]
        + totals["official_fees_total"]
        + totals["other_charges_total"]
    )
    return totals
