"""UPI payment intent + dynamic QR generation (server-side only).

The QR is generated per order from the backend-calculated total; the
frontend can never influence the payable amount.
"""
import os
from urllib.parse import urlencode

import qrcode

from flask import current_app

UPI_INTENT_SCHEME = "upi://pay"


def build_upi_intent(amount, upi_id: str, merchant_name: str,
                     order_number: str, note: str = "") -> str:
    """Standard UPI deep link: upi://pay?pa=...&pn=...&am=...&cu=INR&tr=...&tn=..."""
    params = {
        "pa": upi_id,
        "pn": (merchant_name or "Merchant")[:50],
        "am": f"{float(amount):.2f}",
        "cu": "INR",
        "tr": order_number,
        "tn": (note or order_number)[:50],
    }
    return f"{UPI_INTENT_SCHEME}?{urlencode(params)}"


def generate_qr_png(upi_intent: str, order_number: str) -> str:
    """Render the QR PNG to the cache dir; returns the absolute file path."""
    cache_dir = current_app.config["QR_CACHE_DIR"]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{order_number}.png")
    if not os.path.exists(path):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(upi_intent)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(path)
    return path
