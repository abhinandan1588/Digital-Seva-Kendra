"""Local filesystem storage adapter (development fallback / test adapter).

Mirrors the Google Drive folder structure under instance/storage/ so switching
to Drive later changes nothing else in the application. Files are private:
served only through authenticated admin routes.
"""
import os
import shutil

from flask import current_app

from .base import BaseStorage


class LocalStorage(BaseStorage):
    name = "local"

    def __init__(self, root: str | None = None):
        self._root = root or None

    @property
    def root(self) -> str:
        if self._root:
            return self._root
        cfg_root = current_app.config.get("LOCAL_STORAGE_DIR")
        base = cfg_root or current_app.config["STAGING_DIR"].replace("/staging", "/storage")
        os.makedirs(base, exist_ok=True)
        return base

    # -- helpers -----------------------------------------------------------
    def _folder_path(self, order_number: str, subfolder: str | None = None,
                     year: str | None = None) -> str:
        year = year or str(order_number.split("-")[1]) if "-" in order_number else "General"
        path = os.path.join(self.root, year, order_number)
        if subfolder:
            path = os.path.join(path, subfolder)
        os.makedirs(path, exist_ok=True)
        return path

    # -- interface ----------------------------------------------------------
    def test_connection(self) -> dict:
        try:
            os.makedirs(self.root, exist_ok=True)
            probe = os.path.join(self.root, ".probe")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
            return {"ok": True, "detail": f"Local storage ready at {self.root}"}
        except OSError as exc:
            return {"ok": False, "detail": str(exc)}

    def ensure_folder_tree(self, order_number: str, service_labels: list[str],
                           year: str | None = None) -> dict:
        year = year or (order_number.split("-")[1] if "-" in order_number else "General")
        ids = {}
        for label in service_labels:
            safe = label.replace("/", "_").replace("\\", "_")[:80] or "Service"
            ids[label] = self._folder_path(order_number, safe, year)
        ids["__proof__"] = self._folder_path(order_number, "Payment_Proof", year)
        ids["__output__"] = self._folder_path(order_number, "Final_Documents", year)
        ids["__order_dir__"] = self._folder_path(order_number, None, year)
        # In the local adapter "ids" are absolute paths.
        return {"order_folder_id": ids["__order_dir__"], "service_folder_ids": ids}

    def upload_file(self, local_path: str, stored_name: str, mime_type: str,
                    folder_id: str | None = None) -> dict:
        dest_dir = folder_id or self._folder_path("General")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, stored_name)
        shutil.copyfile(local_path, dest)
        return {"provider": self.name, "file_id": dest, "web_view_link": None}

    def download_file(self, file_id: str) -> bytes:
        with open(file_id, "rb") as fh:
            return fh.read()

    def delete_file(self, file_id: str) -> bool:
        try:
            if os.path.isfile(file_id):
                os.remove(file_id)
                return True
        except OSError:
            return False
        return False

    def delete_folder_tree(self, order_number: str) -> bool:
        base = os.path.join(self.root)
        for dirpath, dirnames, _files in os.walk(base):
            if os.path.basename(dirpath) == order_number:
                shutil.rmtree(dirpath, ignore_errors=True)
                return True
        return False
