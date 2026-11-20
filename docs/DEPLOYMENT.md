# Deployment Guide

## 1. Recommended production stack

- **Linux server** (Ubuntu 22.04+ / any modern distro)
- **Python 3.10+** with a virtualenv
- **PostgreSQL 14+** (local or managed)
- **gunicorn** (WSGI) behind **nginx** (TLS termination + static files)
- **HTTPS** (Let's Encrypt / certbot) — required; cookies carry admin sessions

> The SQLite fallback built into `app/config.py` is a development convenience
> only — production (multiple gunicorn workers) must use PostgreSQL, and
> `FLASK_CONFIG=production` refuses to boot without a PostgreSQL `DATABASE_URL`.

## 2. Server setup

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip postgresql nginx
sudo -u postgres createuser dsk_user --pwprompt
sudo -u postgres createdb digital_seva -O dsk_user

cd /opt && git clone <your-repo> digital_seva_kendra && cd digital_seva_kendra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Environment (.env)

```bash
cp .env.example .env && nano .env
```

Production requirements:

```env
FLASK_CONFIG=production
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=postgresql://dsk_user:STRONG-PASSWORD@localhost:5432/digital_seva
SESSION_COOKIE_SECURE=true
ADMIN_EMAIL=owner@yourshop.in
ADMIN_INITIAL_PASSWORD=<strong password, changed after first login>
RATELIMIT_STORAGE_URI=memory://          # redis://... when running many workers
GOOGLE_CLIENT_SECRETS_FILE=/etc/dsk/client_secret.json
GOOGLE_OAUTH_REDIRECT_URI=https://your-domain/admin/settings/drive/callback
```

`FLASK_CONFIG=production` refuses to boot without a real `SECRET_KEY`.

## 4. Initialise

```bash
export FLASK_APP=run.py
flask db upgrade
flask init-defaults
flask create-admin
```

With the default `AUTO_SEED_CATALOGUE=true` no command is strictly required:
on the first start against an empty database the application creates the
table schema (and marks the alembic head), inserts the default settings, the
full built-in catalogue and — when `ADMIN_EMAIL` + `ADMIN_INITIAL_PASSWORD`
are set in `.env` — the first admin account. Keeping `flask db upgrade` in
the deploy script is still recommended in production: it makes schema changes
explicit and reviewable. The commands above stay available for manual or
repeat runs.

Optional — rebuild the React SPA (`frontend/`); a prebuilt `frontend/dist`
ships with the project and Flask serves it automatically under `/app/`, so
this step is only needed after editing the React source:

```bash
cd frontend && npm ci && npm run build && cd ..
```

## 5. Run under gunicorn

```bash
pip install gunicorn
gunicorn --workers 3 --bind 127.0.0.1:8000 --access-logfile - "run:app"
```

Example systemd unit `/etc/systemd/system/dsk.service`:

```ini
[Unit]
Description=Digital Seva Kendra
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/digital_seva_kendra
Environment="FLASK_APP=run.py"
ExecStart=/opt/digital_seva_kendra/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 "run:app"
Restart=always

[Install]
WantedBy=multi-user.target
```

## 6. nginx (TLS + static + upload size)

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain;
    ssl_certificate     /etc/letsencrypt/live/your-domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain/privkey.pem;

    client_max_body_size 30m;           # matches MAX_CONTENT_LENGTH_MB

    location /static/ {
        alias /opt/digital_seva_kendra/app/static/;
        expires 30d;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

With TLS termination at nginx, keep `SESSION_COOKIE_SECURE=true`. Flask trusts
`X-Forwarded-Proto` if you add `ProxyFix` or serve `https` directly.

## 7. Backups

**Database** (nightly cron):

```bash
0 2 * * * PGPASSWORD=... pg_dump -h localhost -U dsk_user digital_seva | gzip > /backups/dsk-$(date +\%F).sql.gz
```

**Documents** — primary store is the shop's Google Drive; additionally back up
the local fallback dir if used: `instance/storage/`. Keep `instance/` (staging +
QR cache) on persistent storage.

Restore: `gunzip -c backup.sql.gz | psql -h localhost -U dsk_user digital_seva`
then `flask db upgrade`.

## 8. Maintenance

| Command | Purpose |
|---|---|
| `flask cleanup-staging` | cron hourly: delete staged files older than `STAGING_MAX_AGE_HOURS` |
| `flask retry-uploads` | cron every 5 min (optional): retry pending Drive uploads |
| `flask create-admin` | rotate the admin password |

## 9. Security checklist before go-live

- [ ] `SECRET_KEY` is a fresh random value (never committed)
- [ ] `SESSION_COOKIE_SECURE=true` and site served over HTTPS
- [ ] Admin password changed after first login (Profile → Change Password)
- [ ] Google Drive connected + Test Connection OK; client secret stored outside the repo
- [ ] Real UPI ID configured; test order paid + verified end-to-end
- [ ] `.env`, `client_secret*.json`, `instance/` are NOT in Git (see `.gitignore`)
- [ ] Rate limiting enabled; consider Redis storage for multiple workers
- [ ] Database backups scheduled and tested
- [ ] Privacy policy & terms filled in Admin → Website Settings

## 10. Local development commands

```bash
export FLASK_APP=run.py
python run.py               # dev server with debug
pytest                      # full test suite (separate test DB)
```
