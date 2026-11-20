"""File validation: content sniffing, size limits, safe unique names.

Customer-supplied filenames are never used as storage paths. MIME types are
validated from the actual file bytes, not the extension or browser claim.
"""
import os
import secrets

from PIL import Image

MAGIC_SIGNATURES = {
    "pdf": b"%PDF-",
    "jpg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}
MIME_BY_EXT = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def allowed_extension(filename: str, allowed: set[str] | list[str]) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in {a.lower().lstrip(".") for a in allowed}


def snif_file_type(fileobj) -> str | None:
    """Detect real file type from magic bytes: pdf/jpg/png/webp or None."""
    pos = fileobj.tell()
    head = fileobj.read(24)
    fileobj.seek(pos)
    for ext, magic in MAGIC_SIGNATURES.items():
        if head.startswith(magic):
            return ext
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image_bytes(fileobj) -> bool:
    """Pillow-decode image to confirm the content is a real, complete image."""
    pos = fileobj.tell()
    try:
        img = Image.open(fileobj)
        img.verify()
        return True
    except Exception:
        return False
    finally:
        fileobj.seek(pos)


def validate_upload(fileobj, filename: str, allowed_extensions: set[str] | list[str],
                    max_mb: int) -> tuple[bool, str]:
    """Full server-side validation of an uploaded file.

    Returns (ok, error_message). Checks: presence, size, extension,
    content signature, and for images a full decode.
    """
    if fileobj is None or not filename:
        return False, "no_file"
    fileobj.seek(0, os.SEEK_END)
    size = fileobj.tell()
    fileobj.seek(0)
    if size == 0:
        return False, "empty_file"
    max_bytes = max(int(max_mb), 1) * 1024 * 1024
    if size > max_bytes:
        return False, "too_large"
    if not allowed_extension(filename, allowed_extensions):
        return False, "bad_type"
    real = snif_file_type(fileobj)
    if real is None or real not in {a.lower().lstrip(".") for a in allowed_extensions}:
        return False, "bad_content"
    if real in ("jpg", "png", "webp"):
        if not validate_image_bytes(fileobj):
            return False, "bad_content"
    fileobj.seek(0)
    return True, ""


def safe_stored_name(ext: str) -> str:
    """Random name in our own naming scheme; original name kept only for display."""
    ext = ext.lower().lstrip(".")
    return f"{secrets.token_hex(12)}.{ext}"


def doc_kind_for(filename: str) -> str:
    return "image" if snif_file_type_extension(filename) in ("jpg", "jpeg", "png", "webp") else "document"


def snif_file_type_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
