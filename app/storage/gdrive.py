"""Google Drive storage adapter (primary document store).

- OAuth 2.0 with offline refresh; tokens stored encrypted server-side only.
- Folder structure: <root>/<year>/<order number>/<service folders|Payment_Proof|Final_Documents>
- All folders/files private; no public sharing is ever created.
- Raises StorageError on API failure so callers can keep the upload pending
  and retry - customer documents are never silently dropped.
"""
from flask import current_app, url_for

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .base import BaseStorage, StorageError
from ..utils.drive_settings import get_drive_service, is_drive_connected

FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveStorage(BaseStorage):
    name = "gdrive"

    # ------------------------------------------------------------------
    def _service(self):
        service = get_drive_service()
        if service is None:
            raise StorageError("Google Drive is not connected.")
        return service

    def _root_name(self) -> str:
        return current_app.config["DRIVE_ROOT_FOLDER_NAME"]

    def _find_child(self, service, name: str, parent_id: str) -> str | None:
        """Find a child folder id by exact name (private folders only)."""
        query = (
            f"name = '{name.replace(chr(39), chr(39) * 2)}' and "
            f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        resp = service.files().list(q=query, fields="files(id)", pageSize=2).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def _create_folder(self, service, name: str, parent_id: str) -> str:
        meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        folder = service.files().create(body=meta, fields="id").execute()
        return folder["id"]

    def _ensure_folder(self, service, name: str, parent_id: str) -> str:
        return self._find_child(service, name, parent_id) or self._create_folder(service, name, parent_id)

    def _root_folder_id(self, service) -> str:
        root_name = self._root_name()
        query = f"name = '{root_name.replace(chr(39), chr(39) * 2)}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        resp = service.files().list(q=query, fields="files(id)", pageSize=2).execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
        return self._create_folder(service, root_name, "root")

    # ------------------------------------------------------------------
    def test_connection(self) -> dict:
        if not is_drive_connected():
            return {"ok": False, "detail": "Not connected. Complete the Google OAuth flow first."}
        try:
            service = self._service()
            info = service.about().get(fields="user,storageQuota").execute()
            user_email = info.get("user", {}).get("emailAddress", "unknown")
            return {"ok": True, "detail": f"Connected as {user_email}"}
        except Exception as exc:
            return {"ok": False, "detail": f"Drive error: {type(exc).__name__}: {exc}"[:300]}

    def ensure_folder_tree(self, order_number: str, service_labels: list[str],
                           year: str | None = None) -> dict:
        year = year or (order_number.split("-")[1] if "-" in order_number else "General")
        try:
            service = self._service()
            root_id = self._root_folder_id(service)
            year_id = self._ensure_folder(service, year, root_id)
            order_id = self._ensure_folder(service, order_number, year_id)
            service_ids = {}
            for label in service_labels:
                safe = label.replace("/", "_").replace("\\", "_")[:80] or "Service"
                service_ids[safe] = self._ensure_folder(service, safe, order_id)
            proof_id = self._ensure_folder(service, "Payment_Proof", order_id)
            output_id = self._ensure_folder(service, "Final_Documents", order_id)
            service_ids["__proof__"] = proof_id
            service_ids["__output__"] = output_id
            return {"order_folder_id": order_id, "service_folder_ids": service_ids}
        except HttpError as exc:
            raise StorageError(f"Drive folder creation failed: {exc.status_code}") from exc
        except Exception as exc:
            raise StorageError(f"Drive folder creation failed: {type(exc).__name__}") from exc

    def upload_file(self, local_path: str, stored_name: str, mime_type: str,
                    folder_id: str | None = None) -> dict:
        try:
            service = self._service()
            media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
            meta = {"name": stored_name, "parents": [folder_id]}
            # Private by default: no 'permissions' entries created.
            file = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
            return {
                "provider": self.name,
                "file_id": file["id"],
                "web_view_link": file.get("webViewLink"),
            }
        except HttpError as exc:
            raise StorageError(f"Drive upload failed: {exc.status_code}") from exc
        except Exception as exc:
            raise StorageError(f"Drive upload failed: {type(exc).__name__}") from exc

    def download_file(self, file_id: str) -> bytes:
        import io

        try:
            service = self._service()
            request = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
            return buf.getvalue()
        except HttpError as exc:
            raise StorageError(f"Drive download failed: {exc.status_code}") from exc
        except Exception as exc:
            raise StorageError(f"Drive download failed: {type(exc).__name__}") from exc

    def delete_file(self, file_id: str) -> bool:
        try:
            service = self._service()
            service.files().delete(fileId=file_id).execute()
            return True
        except HttpError:
            return False

    def delete_folder_tree(self, order_number: str) -> bool:
        try:
            service = self._service()
            root_id = self._root_folder_id(service)
            folder_id = self._find_child(service, order_number, root_id)
            if folder_id:
                service.files().delete(fileId=folder_id).execute()
                return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    def build_oauth_flow(self, redirect_uri: str):
        """Google OAuth consent flow (drive scope, offline refresh token)."""
        from google_auth_oauthlib.flow import Flow

        secrets_file = current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]
        if not secrets_file:
            raise StorageError("GOOGLE_CLIENT_SECRETS_FILE is not configured.")
        scopes = ["https://www.googleapis.com/auth/drive"]
        flow = Flow.from_client_secrets_file(secrets_file, scopes=scopes,
                                             redirect_uri=redirect_uri)
        flow.access_type = "offline"
        flow.prompt = "consent"
        return flow


def drive_status() -> dict:
    """Summary for the admin Drive settings page."""
    from ..utils.drive_settings import is_drive_connected, load_credentials

    connected = is_drive_connected()
    info = {"connected": connected, "provider": "gdrive"}
    if connected:
        creds = load_credentials() or {}
        info["has_refresh"] = bool(creds.get("refresh_token"))
        info["expiry"] = creds.get("expiry")
    return info
