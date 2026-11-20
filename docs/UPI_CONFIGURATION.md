# UPI Payment Configuration Guide

Version 1 uses **manual verification**: the customer pays the exact order total
to the shop's UPI ID and submits the UTR + screenshot; the shop owner verifies
the payment in the admin panel. Nothing is ever auto-verified.

## 1. Configure the shop's UPI details

Admin panel → **Payment Settings**:

| Field | Meaning |
|---|---|
| UPI ID (VPA) | The shop's UPI address, e.g. `shopname@okhdfcbank` — double-check it! |
| Merchant name on QR | Name shown in payment apps (max 50 chars) |
| Payment instructions | Shown under the QR (English + Hindi) |
| Support info | Shown at the bottom of the payment page |

These are stored in the `website_settings` table — changeable any time without
redeploying.

## 2. How the QR is generated

For every order the backend builds a standard UPI payment intent:

```
upi://pay?pa=<upi id>&pn=<merchant>&am=<exact total>&cu=INR&tr=<order number>&tn=<note>
```

- `am` (amount) comes **only** from the server-calculated order total — the
  browser can never influence it.
- `tr` (reference) is the order number, so the payment statement is traceable.
- The QR PNG is rendered server-side (`qrcode` library) and cached per order.

## 3. Customer flow

1. Order confirmation page → **Pay by UPI Now**.
2. Scan the QR with any UPI app (GPay/PhonePe/Paytm/BHIM) and pay the exact amount.
3. Enter the **UPI transaction ID (UTR)**, attach the **payment screenshot**
   (JPG/PNG/PDF ≤ 5 MB) and submit.
4. Payment moves to *Pending Verification*; the customer sees this on the
   tracking page. Uploading a screenshot never marks the payment as verified.

## 4. Shop owner verification

Admin panel → **Payment Verification** (queue badge shows pending count):

- **Review** shows the order, expected amount, submitted UTR, customer remarks
  and the screenshot (with download + open-in-Drive).
- **Approve** → payment `verified`, order `confirmed`, applications move to
  *Payment Verified*, customer notified on the tracking page, audit entry created.
- **Reject** (mandatory reason) → payment `rejected`, order back to
  *Awaiting Payment*; the customer can resubmit corrected proof.
- **Request corrected proof** → softer option: payment stays pending while the
  customer is asked to resubmit.

Only **verified** payments count as collected revenue in the dashboard/reports.

## 5. Reconciliation tips

- Cross-check the submitted UTR against your bank/UPI app statement for the
  exact amount and the order reference in the payment note.
- Every approve/reject action is written to `admin_audit_logs` with the admin
  identity, IP and reason.

## 6. Future: payment gateway

The payment module was designed for a later gateway integration:

- `payments` table already has `payment_method`, `gateway_reference` columns;
- `app/payments/routes.py` isolates proof submission;
- to add Razorpay/PhonePe etc., implement webhook verification in a new module
  and flip the payment to `verified` **only after server-side signature
  validation** — never trust client-side success pages.
