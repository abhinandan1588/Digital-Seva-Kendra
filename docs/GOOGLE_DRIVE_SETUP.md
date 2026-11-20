# Google Drive Setup Guide

Customer documents are stored **privately** in the shop's own Google Drive via
the official Google Drive API with OAuth 2.0. Follow these steps once.

## 1. Create the Google Cloud project

1. Go to <https://console.cloud.google.com/> and create a project (e.g. *Digital Seva Kendra*).
2. **APIs & Services → Library** → search **Google Drive API** → **Enable**.

## 2. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen** → choose **External**.
2. Fill the app name/support email; add the scope `https://www.googleapis.com/auth/drive`.
3. Under **Test users**, add the shop's dedicated Google account (the one whose
   Drive will hold the documents).

## 3. Create the OAuth client

1. **Credentials → Create credentials → OAuth client ID → Web application**.
2. **Authorized redirect URIs** — add exactly:
   ```
   https://YOUR-DOMAIN/admin/settings/drive/callback
   ```
   (for local testing: `http://127.0.0.1:5000/admin/settings/drive/callback`)
3. **Download** the client secret JSON and save it on the server, e.g.
   `/etc/dsk/client_secret.json` — **outside the project folder, never committed to Git**.

## 4. Configure the environment (.env)

```env
STORAGE_PROVIDER=auto
DRIVE_ROOT_FOLDER_NAME=Digital Seva Kendra
GOOGLE_CLIENT_SECRETS_FILE=/etc/dsk/client_secret.json
GOOGLE_OAUTH_REDIRECT_URI=https://YOUR-DOMAIN/admin/settings/drive/callback
```

`STORAGE_PROVIDER` values:
- `auto` — use Drive when connected, secure local fallback otherwise (recommended);
- `gdrive` — always Drive (login to admin fails uploads if not connected);
- `local` — always the local private store.

## 5. Connect the Drive (admin UI)

1. Log in to the admin panel → **Google Drive Settings**.
2. Click **Connect Google Drive** and sign in with the shop's Google account.
   Consent must include *offline access* (the app requests it automatically) so
   refresh tokens work long-term.
3. Click **Test Connection** — it should report the connected account.
4. The folder tree `Digital Seva Kendra/<year>/<order number>/…` is created
   automatically per order.

## 6. Security notes

- OAuth tokens are stored **encrypted** (Fernet, key derived from `SECRET_KEY`)
  in the `website_settings` table — never in code, never exposed to the browser.
- Uploaded files get **no public sharing permissions**; only the service account
  (shop's Google account) can access them.
- Admin preview/download goes through authenticated routes only. The "Open in
  Drive" button opens the private Drive URL for the logged-in admin.
- If Drive is temporarily unavailable, uploads are kept in the secure staging
  area and marked *pending*; retry from **Admin → Google Drive Settings → Retry
  pending uploads** or `flask retry-uploads`. Nothing is discarded.

## 7. Disconnecting / rotating

- **Disconnect** removes the stored credentials (documents already uploaded stay in Drive).
- To rotate: disconnect, update the client secret file, reconnect.
