# Digital Seva Kendra — Online Service Portal

A complete, production-oriented website for a Digital Seva Kendra (Digital Citizen
Service Centre): customers order government and private application services
online, upload documents, pay by UPI QR and track applications — **without ever
creating an account**. The shop owner manages everything from a powerful admin
dashboard.

Built with **Flask + PostgreSQL + Google Drive API**, following the master
development prompt's architecture, business rules and security requirements.

---

## The service catalogue (database-driven, admin-managed)

The complete catalogue — **15 categories / 55 subcategories / 336 services** —
lives in PostgreSQL and is managed entirely from the admin dashboard. The data
ships as importable JSON/CSV files under `data/` and is loaded **automatically
on first start** (empty database + applied migrations → the app seeds itself,
including default website settings and, when `ADMIN_EMAIL` +
`ADMIN_INITIAL_PASSWORD` are set in `.env`, the first admin account). Two
manual alternatives exist for special cases:

```bash
flask seed-catalogue   # CLI: loads data/*.json (idempotent, update-or-create)
# or: Admin -> Catalogue Import/Export -> "Load built-in catalogue" (one click)
```

| Category (A–O per the master spec) | Contents |
|---|---|
| Government Certificates & Documents | Caste (SC/ST/BC/EBC/OBC + correction/download), Income, Residential, EWS, Non-Creamy Layer, Birth/Death/Marriage, Character, Disability/UDID, Land records, other RTPS |
| Identity Card Services | PAN (new/correction/reprint/e-PAN/status), Aadhaar (download/PVC/update/appointment/status), Voter ID (Forms 6/8, e-EPIC), Passport (fresh/reissue/Tatkaal/PCC), Driving Licence (Sarathi) |
| Education & Admissions | School→University admissions (NIOS/IGNOU/B.Ed/…), exam forms, revaluation/scrutiny, migration/duplicate marksheets |
| Scholarships | NSP, pre/post-matric, minority, Bihar MedhaSoft (matric/inter/CM incentive), category scholarships, renewal/correction/status |
| Central Govt Examinations | UPSC (11), SSC (10), Railway RRB/RPF (10), Banking (10), Defence (Agniveer/AFCAT/Coast Guard) |
| Bihar Govt Examinations | BPSC (CCE/TRE/APO/AE/…), Bihar Police (CSBC/BPSSC), BSSC, BTSC, STET, Panchayati Raj, district-level |
| National Entrances | JEE, NEET, CUET, UGC/CSIR NET, GATE, CAT/MAT/CMAT, CLAT/AILET, NIFT/NID/NATA/JIPMAT |
| Bihar Entrances | BCECE, DCECE, ITICAT, UGEAC/UGMAC/PGMAC, nursing & paramedical (BCECEB) |
| Examination Support | Admit cards, city slips, results, answer keys & objections, counselling, choice filling, DV, corrections |
| Government Welfare Schemes | PM-KISAN, Ayushman, e-Shram, labour card, pensions (Bihar SSP), ration card, PMAY, SVANidhi, Ujjwala, APY, Jeevan Pramaan, KCC, PMFBY |
| Business & Taxation | GST, ITR, PAN/TAN, Udyam, FSSAI, trade licence, EPFO/ESIC, DSC, trademark |
| Transport & Vehicle | Sarathi licences, VAHAN RC/transfer/tax, e-Challan, FASTag, PUC |
| Digital Document & Computer | Typing/resume/affidavits, 13 PDF tools, photo & signature work, scanning/printing/lamination, data entry |
| Legal & Civic | e-Courts, e-stamp, property registration, Bihar Bhumi land records & mutation, CPGRAMS, RTI, police verification |
| Other Digital & Utility | Bookings, telemedicine (eSanjeevani), Skill India, recharges & bill payments |

**Every service row carries**: bilingual name/description/instructions, slug,
category + subcategory, icon, shop service charge, official fee (verified by
the admin — never guessed), other charges, processing time, required/optional
documents, dynamic form configuration, eligibility, official portal reference,
compliance capability and popular/featured flags.

### Compliance capability (per service)

| Capability | Customer sees |
|---|---|
| `internal_service` | Completed at the centre (typing, PDF tools, photo work) |
| `assisted_application` | Details/documents collected here; operator submits on the official portal |
| `authorized_integration` | Performed through a real authorized partner/API |
| `external_portal` | Redirected to the official portal; shop assists |
| `restricted_authorization_required` | **Visible but never orderable** — "authorization required" until the admin activates it (used for GST/ITR returns, DSC, trademark, ticketing, BC services…) |

OTP/biometric/identity verification is always completed by the customer
personally; the system never asks for portal passwords and never stores Aadhaar
OTPs. Applications are submitted only after customer review and consent.

### Examination & recruitment module

A service with *Examination service* enabled is an exam **TYPE** (e.g. SSC CGL);
each notification is an **exam cycle** (e.g. SSC CGL 2027, Advt. 1/2027):

- Public listing at `/exams` with filters (organization, education level,
  qualification, status, state, deadline-within-N-days) and countdown badges
  ("Last Date Approaching", "days left", "opens in…").
- Cycle detail page: verified dates, category-wise fees, age limits,
  extra documents, official links, notification PDF, honest closed-state.
- Statuses (`upcoming`/`open`/`closed`) are **computed from verified dates only** —
  a cycle auto-closes after its application deadline; extensions exist only when
  the admin ticks official confirmation. Nothing is ever invented or silently
  updated; unverifiable cycles are flagged `needs_review` for admin action.
- Ordering an exam service requires choosing an **open** cycle; closed cycles
  are never orderable or displayed as available.
- CLI compliance helpers: `flask flag-stale-cycles --days 14`, and
  `flask check-official-sources` (polite RSS/Atom-feed-only monitoring hook;
  a failed check flags for review instead of updating anything).

### Other new modules

- **Dedicated category pages** (`/category/<slug>`) with subcategory chips, search,
  price/document previews and capability badges; homepage rebuilt from 12 data-driven sections.
- **Bilingual search**: Hindi + romanised-Hindi aliases ("aay praman patra" →
  Income Certificate) in `data/search_aliases.json`, keyword boosts, JSON
  suggestions for the search box, anonymous popular-search chips.
- **Reusable document templates** (27 seeded) attached to services in one click;
  per-service copies stay customisable (dimensions, compression, expiry).
- **Official portal directory** (79 seeded portals) referenced by every service;
  "Open Official Website" buttons + honest "we are a private centre" disclaimers.
- **Pricing & availability admin pages** with inline price editing (snapshots
  protect historical orders) and one-click capability switching.
- **Catalogue import/export**: CSV/JSON import with validation, duplicate
  detection, preview and explicit confirmation (update-or-create by slug;
  nothing overwritten silently); CSV + full JSON export; sample template.

### Admin dashboard — catalogue modules

Service Categories · Subcategories · All Services (filters incl. archived) ·
Popular Services · Featured Services · Examination Management · Recruitment
Notifications · Examination Cycles (+ archive) · Scholarship Management ·
Government Scheme Management (scheme year/cycle per service) · Document
Templates · Official Portal Directory · Service Pricing · Service Availability ·
Catalogue Import/Export — plus the existing orders/payments/forms/customers/
settings/reports/audit modules. Hundreds of services and new notifications can
be managed without touching Python code.

---

## Feature highlights

| Area | What it does |
|---|---|
| Public site | Bilingual (English/हिन्दी) home with 12 catalogue sections, services catalogue + category pages with search & filters, exam listing with countdowns, service detail with price breakdown/eligibility/documents/cycles, About/Contact/FAQ, Privacy/Terms (admin-editable) |
| No-account ordering | Cart supporting **multiple services in one order** and the **same service multiple times** (different applicants); per-application dynamic forms; per-service document uploads; exam-cycle selection for exam applications |
| Dynamic form builder | Admin builds each service's form (12 field types, bilingual labels, required/optional, min/max lengths, dropdown options, file rules) and document requirements — **no code changes needed** |
| Payments | Per-order UPI intent QR (amount fixed server-side), UTR + screenshot submission, **manual verification** queue with approve/reject/request-corrected-proof; gateway-ready schema |
| Tracking | Order number + secure tracking token/PIN (only SHA-256 hashes stored), customer-visible timeline, output-document download, rate-limited |
| Documents | Google Drive as primary store (`Digital Seva Kendra/<year>/<order no>/…`), private files only, secure local fallback with pending-state retry, admin preview/download/delete |
| Admin dashboard | Real PostgreSQL analytics (verified-only revenue), orders/applications with independent statuses, status history with internal notes, customers, document manager, notifications, reports + CSV export, audit logs, settings (website/payment/Drive/notification templates) |
| Receipts | Server-generated PDF receipt (ReportLab) — never marks pending payment as paid |
| Security | scrypt password hashing, CSRF everywhere, rate limiting (login/checkout/tracking/uploads), content-sniffing file validation, server-side pricing, audit logging, encrypted Drive OAuth tokens, no PII in logs |

---

## Quick start (development)

### 1. Prerequisites
- Python 3.10+
- PostgreSQL 12+ — required for production, **optional** for a quick dev run:
  without `DATABASE_URL` the app falls back to a local SQLite file automatically

### 2. Install
```bash
cd digital_seva_kendra
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# edit .env: SECRET_KEY, ADMIN_EMAIL, ADMIN_INITIAL_PASSWORD
# DATABASE_URL: leave it commented/absent for a zero-setup SQLite dev database,
#               or point it at PostgreSQL (recommended, required in production)
```

### 4. Database
```bash
export FLASK_APP=run.py
flask db upgrade                           # optional: apply migrations
```
On the first start against an **empty database** the app does everything
itself: it creates the table schema (marking the alembic head, so migrations
keep working), loads default website settings and the full 336-service
catalogue, and — when `ADMIN_EMAIL` + `ADMIN_INITIAL_PASSWORD` are set in
`.env` — creates the first admin account. Plain `python run.py` on a fresh
machine is enough. Everything below stays available if you prefer doing it by
hand or need to re-run a step:

```bash
flask init-defaults                        # default website settings
flask create-admin                         # first admin from .env credentials
flask seed-catalogue                       # load the full 336-service catalogue + portals + doc templates + search aliases
flask seed-demo                            # optional: small sample data instead (dev only)
```

> `seed-catalogue` creates every exam cycle as an **unpublished, review-pending
> template** with no dates — the admin verifies each official notification
> (dates, fees, eligibility), marks it verified and only then publishes it.
> Seeded official fees are 0: configure them from current official information
> in Admin → Service Pricing before going live.

### Using PostgreSQL instead of the SQLite fallback

Recommended for real use, required for production. Install, start, and create
the database and user:

```bash
sudo apt install -y postgresql postgresql-client    # Debian/Ubuntu
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE dsk_user LOGIN PASSWORD 'STRONG-PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE digital_seva OWNER dsk_user;"
```

Then set in `.env`:
```env
DATABASE_URL=postgresql://dsk_user:STRONG-PASSWORD@localhost:5432/digital_seva
```
and run the same `flask db upgrade` / `flask init-defaults` /
`flask create-admin` sequence as above. The schema is fully portable between
SQLite (dev) and PostgreSQL (production); `FLASK_CONFIG=production` refuses to
boot without a PostgreSQL `DATABASE_URL`.

### 5. Run
```bash
python run.py            # development server on http://127.0.0.1:5000
```
- Customer site (classic templates): `http://127.0.0.1:5000/`
- Customer site (React SPA): `http://127.0.0.1:5000/app/` — prebuilt in `frontend/dist`
- Admin panel: `http://127.0.0.1:5000/admin/login` (admin email + password from `.env`)

## React SPA frontend (frontend/)

The customer-facing portal also ships as a **React (JavaScript) single-page
app** in `frontend/`. It talks to a JSON API under `/api` that reuses the exact
same session cart, pricing, validation, checkout and tracking helpers as the
Flask templates — so both frontends behave identically and every security
guarantee (server-side pricing, content-sniffed uploads, hashed tracking
credentials, rate limits) applies to both.

- **The Jinja templates and the admin panel are unchanged.** The React app is
  served at **`/app/`** (with client-side route fallback); the classic pages
  keep their original URLs and the admin remains the server-rendered Flask app
  at `/admin`.
- **Zero-build run:** `frontend/dist/` ships prebuilt — just `python run.py`
  and open `/app/`. Rebuild only when you edit the React source.
- **Development (hot reload):**
  ```bash
  cd frontend && npm install && npm run dev   # http://localhost:5173
  ```
  The Vite dev server proxies `/api`, `/pay`, `/order` and `/static` to Flask
  on `:5000`, so sessions, the cart and file uploads work as in production.
- **Production build:** `cd frontend && npm run build` — output lands in
  `frontend/dist` and Flask serves it automatically under `/app/`.
- **Live API smoke test:** `python tests/api_smoke_live.py` against a running
  server drives the whole flow (cart → dynamic form → checkout → track →
  payment proof) through the API.

### Tests
```bash
pytest                       # 106 automated tests (uses a separate test DB)
```
The suite covers admin auth/locking, dynamic form validation, multi-service
orders, price snapshots/tampering prevention, duplicate-order prevention,
QR/UPI generation, payment proof/verification flows, independent application
statuses, secure tracking + data isolation, document validation, storage
adapters (incl. a mock Google Drive adapter), receipts and notifications —
plus the catalogue expansion: seeded catalogue integrity, capability
compliance (restricted services never orderable), bilingual/alias search,
document templates & portals, category pages, the exam-cycle engine
(status transitions, countdowns, filters, closed-cycle ordering guard,
admin publish/verify/extend lifecycle), and CSV/JSON import validation
with historical-order pricing safety.

`python tests/api_smoke_live.py` (against a running server) drives the whole
customer flow over real HTTP (cart → dynamic form → checkout → track →
payment proof) — all 11 checks pass with the seeded catalogue.

---

## Google Drive document storage

Documents are stored **privately** in the shop's Google Drive:

```
Digital Seva Kendra/
└── 2026/
    ├── DSK-2026-000001/
    │   ├── PAN Card Services/
    │   ├── Income Certificate/
    │   ├── Payment_Proof/
    │   └── Final_Documents/
    └── DSK-2026-000002/…
```

Setup is documented in **[docs/GOOGLE_DRIVE_SETUP.md](docs/GOOGLE_DRIVE_SETUP.md)**.
Until Drive is connected the app uses a **secure local fallback** (private files
under `instance/storage/`); when you connect Drive, click *Retry pending
uploads* in Admin → Google Drive Settings (or run `flask retry-uploads`) — no
document is ever lost.

## UPI payments

Documented in **[docs/UPI_CONFIGURATION.md](docs/UPI_CONFIGURATION.md)**.
Set the shop's UPI ID and merchant name in Admin → Payment Settings; each order
gets its own QR generated from the server-calculated total.

## Deployment

Production deployment (gunicorn + nginx + HTTPS, backups, hardening checklist):
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

---

## Project structure

```
digital_seva_kendra/
├── app/
│   ├── __init__.py          # application factory
│   ├── config.py            # env-driven configuration (dev/testing/production)
│   ├── extensions.py        # db, migrate, csrf, login, limiter
│   ├── cli.py               # create-admin, seed-demo, init-defaults, retry-uploads, cleanup-staging
│   ├── cli_catalogue.py     # seed-catalogue, flag-stale-cycles, check-official-sources
│   ├── first_boot.py        # auto-seed on empty database (settings + catalogue + admin from .env)
│   ├── models/              # 23 SQLAlchemy models (JSONB on PostgreSQL, portable to SQLite)
│   │                        #   + subcategory, exam cycle, document template, official portal, search alias/stat
│   ├── auth/                # admin login/logout/change-password
│   ├── public/              # home (12 data-driven sections), about, contact, faq, legal, language switcher
│   ├── services/            # public catalogue + bilingual search + dedicated category pages
│   ├── exams/               # public exam listing/detail with verified-dates countdowns
│   ├── orders/              # cart (incl. exam-cycle selection), checkout, confirmation, tracking, receipts
│   ├── applications/        # customer dynamic form fill + document staging + cycle picker
│   ├── payments/            # UPI QR page, proof submission
│   ├── admin/               # dashboard, orders, payments, catalog + subcategories + templates/portals/
│   │                        #   pricing/availability (catalog_tools_admin), exams & cycles (exam_admin),
│   │                        #   import/export (importexport_admin), documents, customers, settings, reports, audit
│   ├── storage/             # BaseStorage, GoogleDriveStorage, LocalStorage, doc lifecycle
│   ├── notifications/       # in-app records + honest WhatsApp/SMS/email adapters
│   ├── utils/               # i18n, pricing, checkout, search (aliases/suggestions), exams engine, home sections, files, audit, order ids, receipts…
│   ├── templates/           # Jinja2 (public + admin + errors)
│   └── static/              # css/js + vendored Bootstrap 5, Bootstrap Icons, Chart.js
├── data/                    # THE CATALOGUE (database data, not code): catalogue_*.json (15 categories,
│                            #   336 services), portals.json, document_templates.json, search_aliases.json
├── migrations/              # Alembic (Flask-Migrate): initial schema + catalogue-expansion migration
├── frontend/                # React (JavaScript) SPA: Vite + Bootstrap 5, JSON API /api
├── tests/                   # pytest suite (106 tests) + live API smoke (api_smoke_live.py)
├── docs/                    # deployment, Google Drive, UPI guides
├── .env.example             # every configurable value, documented
├── requirements.txt
└── run.py
```

## Key business rules implemented

1. Customers never register/log in; identity = name + mobile at checkout.
2. Multiple services (and the same service twice) in one order; each application
   keeps its own form data, documents and status.
3. All pricing is computed server-side from the database; prices are snapshotted
   at checkout so later price edits never change existing orders.
4. Payment proof submission ≠ verification; verification is manual and audited.
5. Payment, application and order statuses are independent; every change is
   recorded in `status_history` (internal notes never shown publicly).
6. Tracking requires order number + token/PIN; only hashes are stored; public
   pages never expose documents, payment proofs or internal notes.
7. Uploaded files are validated by content (magic bytes + Pillow), stored under
   generated names, and kept private (Drive or local fallback).

## Support / maintenance commands

```bash
flask create-admin          # create/update the admin account
flask init-defaults         # ensure default website settings exist
flask seed-catalogue        # load/update the full catalogue from data/*.json (update-or-create)
# All three also run automatically on first start (AUTO_SEED_CATALOGUE=true,
# the default), and Admin -> Catalogue Import/Export has a one-click
# "Load built-in catalogue" button that runs the same seed.
flask seed-demo             # small sample dataset (dev only)
flask retry-uploads         # retry pending document uploads to storage
flask cleanup-staging       # delete staged files older than STAGING_MAX_AGE_HOURS
flask flag-stale-cycles     # flag exam cycles not re-verified recently for admin review
flask check-official-sources  # polite permitted-feed check; failures flag for review, never edit
```

## Compliance notes (read before going live)

1. Never present the site as a government portal — the templates already carry
   the "private Digital Seva Kendra" disclaimers; keep them.
2. Verify official fees and exam dates from official sources before publishing
   services/cycles; record the verification source and date on each cycle.
3. Services needing licensed professionals or partner authorization stay
   `restricted_authorization_required` (not orderable) until verified.
4. Customers always complete OTP/biometric/identity steps themselves; the shop
   never collects portal passwords and never stores Aadhaar OTPs.
5. Official-source monitoring (`check-official-sources`) contacts only admin
   configured RSS/Atom feeds, one polite request per portal per run, and flags
   — never auto-edits — when a source is unreachable or changed.
# Digital-Seva-Kendra
