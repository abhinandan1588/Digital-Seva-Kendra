"""End-to-end smoke test for the Flask JSON API + React SPA serving.

Runs against a live Flask dev server (SQLite default). Exercises the full
customer flow: site -> catalogue -> cart -> dynamic form (multipart) ->
checkout -> tracking -> payment info -> proof submission -> re-track.
Also asserts the Jinja site still works alongside the SPA.
"""
import io
import sys

import requests

BASE = "http://127.0.0.1:5000"


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, format="PNG")
    return buf.getvalue()


def main():
    s = requests.Session()

    # Jinja templates still serve the classic site (must stay untouched)
    r = s.get(f"{BASE}/")
    assert r.status_code == 200 and "Digital Seva Kendra" in r.text
    print("1. Jinja home still ok (templates untouched)")

    # site bootstrap
    d = s.get(f"{BASE}/api/site").json()
    assert d["settings"]["shop_name"]
    print("2. /api/site ok:", d["settings"]["shop_name"],
          "| categories:", len(d["categories"]),
          "| featured:", len(d["featured_services"]))

    # SPA serving: index + client-route fallback
    r = s.get(f"{BASE}/app/")
    assert r.status_code == 200 and '<div id="root">' in r.text
    r2 = s.get(f"{BASE}/app/track")
    assert r2.status_code == 200 and '<div id="root">' in r2.text
    print("3. SPA serving ok (index + /app/track fallback)")

    # catalogue + detail
    d = s.get(f"{BASE}/api/services").json()
    svc = d["services"][0]
    detail = s.get(f"{BASE}/api/services/{svc['slug']}").json()
    print("4. catalogue ok:", len(d["services"]), "services; first:",
          svc["slug"], "| fields:", len(detail["form_fields"]),
          "| doc reqs:", len(detail["document_requirements"]))

    # cart
    r = s.post(f"{BASE}/api/cart/add", json={"service_id": svc["id"]}).json()
    key = r["item_key"]
    cart = s.get(f"{BASE}/api/cart").json()
    assert cart["items"] and cart["items"][0]["key"] == key
    assert cart["totals"]["total"] == svc["total_price"]
    print("5. cart ok:", cart["items"][0]["slug"], "total", cart["totals"]["total"])

    # dynamic form (multipart) — fill every field type generically
    data, files = {}, []
    for f in detail["form_fields"]:
        ft = f["field_type"]
        if ft in ("file", "file_multi", "image"):
            files.append((f"file_{f['field_key']}", ("doc.png", png_bytes(), "image/png")))
        elif ft == "checkbox":
            opts = f["options"] or []
            if opts:
                data[f["field_key"]] = opts[0] if isinstance(opts[0], str) else opts[0]["en"]
        elif ft == "date":
            data[f["field_key"]] = "2000-01-01"
        elif ft == "number":
            data[f["field_key"]] = "25"
        elif ft == "email":
            data[f["field_key"]] = "cust@example.com"
        elif ft == "mobile":
            data[f["field_key"]] = "9876543210"
        elif ft in ("select", "radio"):
            opts = f["options"] or []
            assert opts, f"select field {f['field_key']} has no options"
            data[f["field_key"]] = opts[0] if isinstance(opts[0], str) else opts[0]["en"]
        else:
            data[f["field_key"]] = "Ramesh Kumar"
    for req in detail["document_requirements"]:
        files.append((f"req_{req['id']}", ("aadhaar.png", png_bytes(), "image/png")))
    r = s.post(f"{BASE}/api/cart/{key}/form", data=data, files=files)
    assert r.status_code == 200 and r.json().get("ok"), r.text
    print("6. dynamic form ok (validated, files staged)")

    # checkout
    tok = s.post(f"{BASE}/api/checkout/init").json()["checkout_token"]
    payload = {"name": "Ramesh Kumar", "mobile": "9876543210",
               "email": "cust@example.com", "address": "Main Market Road",
               "consent": True, "checkout_token": tok}
    r = s.post(f"{BASE}/api/checkout", json=payload).json()
    assert r.get("ok") and r.get("order_number"), r
    num, token = r["order_number"], r["tracking_token"]
    print("7. checkout ok:", num, "| pin", r["tracking_pin"], "| total", r["total"])

    # tracking
    tr = s.get(f"{BASE}/api/track", params={"order_number": num, "token": token}).json()
    assert tr["order_number"] == num and tr["status"] == "submitted"
    assert tr["items"], tr
    print("8. tracking ok: status", tr["status"], "| items", len(tr["items"]),
          "| history", len(tr["history"]))

    # payment info + QR image (existing token-authorised route)
    pay = s.get(f"{BASE}/api/pay/{num}", params={"token": token}).json()
    assert pay["qr_url"] and pay["upi_intent"] and pay["upi_id"]
    qr = s.get(f"{BASE}{pay['qr_url']}")
    assert qr.status_code == 200 and qr.headers["Content-Type"] == "image/png"
    print("9. payment info ok; QR png", len(qr.content), "bytes")

    # proof submission -> pending_verification
    proof = s.post(f"{BASE}/api/pay/{num}/proof",
                   data={"token": token, "utr": "123456789012"},
                   files={"screenshot": ("proof.png", png_bytes(), "image/png")})
    assert proof.status_code == 200 and proof.json().get("ok"), proof.text
    tr2 = s.get(f"{BASE}/api/track", params={"order_number": num, "token": token}).json()
    assert tr2["payment_status"] == "pending_verification", tr2["payment_status"]
    print("10. proof ok; payment_status ->", tr2["payment_status"])

    # validation error path returns per-field codes
    r = s.post(f"{BASE}/api/cart/add", json={"service_id": svc["id"]}).json()
    key2 = r["item_key"]
    r2 = s.post(f"{BASE}/api/cart/{key2}/form", data={})
    assert r2.status_code == 422 and r2.json().get("errors"), r2.text
    print("11. validation errors ok:", r2.json()["errors"])

    print("\nALL 11 E2E CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("FAILED:", exc, file=sys.stderr)
        sys.exit(1)
