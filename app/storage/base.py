"""Storage provider abstraction.

Google Drive is the primary document store (private folders, OAuth 2.0).
A local filesystem adapter provides the same interface for development,
for tests, and as the staging target when Drive is temporarily down -
customer files are never silently discarded.
"""
from abc import ABC, abstractmethod


class StorageError(Exception):
    """Raised when the storage backend cannot complete an operation."""


class BaseStorage(ABC):
    """Interface implemented by GoogleDriveStorage and LocalStorage."""

    name = "base"

    @abstractmethod
    def test_connection(self) -> dict:
        """Return {'ok': bool, 'detail': str}."""

    @abstractmethod
    def ensure_folder_tree(self, order_number: str, service_labels: list[str],
                           year: str | None = None) -> dict:
        """Create (if needed) root/Year/OrderNumber/{service,Payment_Proof,Final_Documents}.
        Returns {'order_folder_id': ..., 'service_folder_ids': {label: id}, 'proof_folder_id': ...}."""

    @abstractmethod
    def upload_file(self, local_path: str, stored_name: str, mime_type: str,
                    folder_id: str | None = None) -> dict:
        """Upload one file. Returns {'provider': name, 'file_id': ..., 'web_view_link': ...}."""

    @abstractmethod
    def download_file(self, file_id: str) -> bytes:
        """Return file content bytes."""

    @abstractmethod
    def delete_file(self, file_id: str) -> bool:
        """Delete a stored file. Returns True when deleted."""

    @abstractmethod
    def delete_folder_tree(self, order_number: str) -> bool:
        """Used by retention policies / order cancellation cleanup (admin action)."""


def get_storage():
    """Factory: Google Drive when configured, else local fallback.

    Selection order:
    1. STORAGE_PROVIDER config == 'local'  -> local adapter
    2. STORAGE_PROVIDER config == 'gdrive' -> Drive (raise if not configured)
    3. 'auto' (default)                    -> Drive if connected, else local
    """
    from flask import current_app
    from ..utils.drive_settings import is_drive_connected

    provider = current_app.config["STORAGE_PROVIDER"]
    if provider == "local":
        from .local_storage import LocalStorage
        return LocalStorage()
    if provider == "gdrive":
        from .gdrive import GoogleDriveStorage
        return GoogleDriveStorage()
    # auto
    if is_drive_connected():
        from .gdrive import GoogleDriveStorage
        return GoogleDriveStorage()
    from .local_storage import LocalStorage
    return LocalStorage()
