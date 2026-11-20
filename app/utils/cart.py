"""Session cart for selected services.

The cart stores ONLY service ids and a stable key per item - never prices.
All pricing is computed server-side from the database at render and checkout
time (see utils/pricing.py), so a customer cannot tamper with amounts.
Supports the same service multiple times (different applicants).
"""
import secrets
from flask import session

CART_KEY = "dsk_cart"


def get_cart() -> list[dict]:
    return session.get(CART_KEY, [])


def save_cart(items: list[dict]) -> None:
    session[CART_KEY] = items
    session.modified = True


def add_service(service_id: int, exam_cycle_id: int | None = None) -> dict:
    """Add one more application for a service (same service allowed twice).

    For examination services the customer's chosen cycle (notification) is
    stored on the cart item; closed/unpublished cycles are rejected here.
    """
    items = get_cart()
    item = {"key": secrets.token_hex(8), "service_id": int(service_id)}
    if exam_cycle_id:
        item["exam_cycle_id"] = int(exam_cycle_id)
    items.append(item)
    save_cart(items)
    return item


def set_item_cycle(item_key: str, exam_cycle_id: int | None) -> bool:
    """Update (or clear) the exam-cycle selection of a cart item."""
    items = get_cart()
    for item in items:
        if item["key"] == item_key:
            if exam_cycle_id:
                item["exam_cycle_id"] = int(exam_cycle_id)
            else:
                item.pop("exam_cycle_id", None)
            save_cart(items)
            return True
    return False


def remove_item(item_key: str) -> bool:
    items = get_cart()
    remaining = [i for i in items if i["key"] != item_key]
    if len(remaining) != len(items):
        save_cart(remaining)
        return True
    return False


def find_item(item_key: str) -> dict | None:
    for item in get_cart():
        if item["key"] == item_key:
            return item
    return None


def clear_cart() -> None:
    save_cart([])


def cart_service_count() -> int:
    return len(get_cart())
