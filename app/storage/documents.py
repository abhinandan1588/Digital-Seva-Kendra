"""Document lifecycle: staged files -> storage provider -> metadata rows.

If the storage provider (Google Drive) is temporarily unavailable, the
document row is created with upload_status='pending', the staged file is
kept, and retry endpoints/CLI can push it later. Documents are never
silently discarded.
"""
import os

from flask import current_app

from ..extensions import db
from ..models import UploadedDocument
from .base import get_storage, StorageError


def upload_document_record(order, staged: dict, *, application=None, requirement=None,
                           form_field=None, payment=None, purpose: str = "application_document",
                           uploaded_by: str = "customer", admin=None, folder_ids: dict | None = None,
                           folder_id=None, form_field_id=None, requirement_id=None,
                           keep_staged: bool = False, commit: bool = True) -> UploadedDocument:
    """Upload one staged file and create its metadata row.

    `folder_id` (single pre-computed folder) wins; otherwise `folder_ids`
    (a tree from ensure_folder_tree) or a freshly ensured tree is used.
    On storage failure the row is saved with upload_status='pending' and the
    staged file kept for retry - documents are never discarded.
    `keep_staged=True` never deletes the staged file (used for wallet files,
    which stay reusable across applications/orders).
    """
    storage = get_storage()
    doc = UploadedDocument(
        order_id=order.id,
        application_id=application.id if application else None,
        requirement_id=requirement.id if requirement else (requirement_id or None),
        form_field_id=form_field.id if form_field else (form_field_id or None),
        payment_id=payment.id if payment else None,
        doc_purpose=purpose,
        label_snapshot=staged.get("label", "Document"),
        original_name=staged["original_name"],
        stored_name=staged["stored_name"],
        mime_type=staged["mime_type"],
        size_bytes=staged["size_bytes"],
        uploaded_by=uploaded_by,
        uploaded_by_admin_id=admin.id if admin else None,
        is_private=True,
    )

    try:
        if folder_id is None:
            label = application.service_name_snapshot if application else "Payment_Proof"
            tree = storage.ensure_folder_tree(order.order_number, [label])
            if purpose == "payment_proof":
                folder_id = tree["service_folder_ids"]["__proof__"]
            elif purpose == "output_document":
                folder_id = tree["service_folder_ids"]["__output__"]
            else:
                safe_label = label.replace("/", "_").replace("\\", "_")[:80]
                folder_id = tree["service_folder_ids"].get(safe_label) or tree["order_folder_id"]

        result = storage.upload_file(staged["abs_path"], staged["stored_name"],
                                     staged["mime_type"], folder_id)
        doc.storage_provider = result["provider"]
        doc.drive_file_id = result["file_id"]
        doc.web_view_link = result.get("web_view_link")
        doc.upload_status = "uploaded"
        # Successfully pushed: safe to remove the staged copy (unless the
        # staged file is a shared wallet document that must stay reusable).
        if not keep_staged:
            try:
                os.remove(staged["abs_path"])
            except OSError:
                pass
            doc.local_staging_rel_path = None
    except StorageError as exc:
        # Keep staged file; record pending state for retry.
        doc.storage_provider = storage.name
        doc.upload_status = "pending"
        doc.last_error = str(exc)[:500]
        doc.local_staging_rel_path = os.path.relpath(staged["abs_path"],
                                                     current_app.instance_path)
    except Exception as exc:  # unexpected - still keep the file
        doc.storage_provider = "local"
        doc.upload_status = "pending"
        doc.last_error = f"unexpected: {type(exc).__name__}"[:500]
        doc.local_staging_rel_path = os.path.relpath(staged["abs_path"],
                                                     current_app.instance_path)

    db.session.add(doc)
    if commit:
        db.session.commit()
    return doc


def sync_order_documents(order, staged_files_by_item: dict | None = None) -> int:
    """Upload a whole order's staged files after checkout."""
    count = 0
    tree = get_storage().ensure_folder_tree(order.order_number,
                                            [a.service_name_snapshot for a in order.applications])
    for app in order.applications:
        label = app.service_name_snapshot.replace("/", "_").replace("\\", "_")[:80]
        folder_id = tree["service_folder_ids"].get(label) or tree["order_folder_id"]
        for staged in (staged_files_by_item or {}).get(app.order_item_id, []):
            upload_document_record(order, staged, application=app, folder_id=folder_id,
                                   purpose="application_document")
            count += 1
    return count


def retry_pending_uploads() -> tuple[int, int]:
    """Retry every pending document. Returns (succeeded, still_pending)."""
    pending = UploadedDocument.query.filter_by(upload_status="pending").all()
    storage = get_storage()
    ok = 0
    for doc in pending:
        # Same content already uploaded in this order (shared wallet file)?
        sibling = (UploadedDocument.query
                   .filter(UploadedDocument.order_id == doc.order_id,
                           UploadedDocument.stored_name == doc.stored_name,
                           UploadedDocument.upload_status == "uploaded")
                   .first())
        if sibling is not None:
            doc.storage_provider = sibling.storage_provider
            doc.drive_file_id = sibling.drive_file_id
            doc.drive_folder_id = sibling.drive_folder_id
            doc.web_view_link = sibling.web_view_link
            doc.upload_status = "uploaded"
            doc.last_error = None
            local_path = None
            if doc.local_staging_rel_path:
                local_path = os.path.join(current_app.instance_path, doc.local_staging_rel_path)
            # Never delete shared wallet files - only this doc's staged copy.
            wallet_root = os.path.join(current_app.instance_path, "wallet")
            if local_path and os.path.isfile(local_path) \
                    and not local_path.startswith(wallet_root):
                try:
                    os.remove(local_path)
                except OSError:
                    pass
            doc.local_staging_rel_path = None
            ok += 1
            continue
        local_path = None
        if doc.local_staging_rel_path:
            local_path = os.path.join(current_app.instance_path, doc.local_staging_rel_path)
        if not local_path or not os.path.exists(local_path):
            doc.last_error = "staged file missing; cannot retry"
            doc.retry_count += 1
            continue
        try:
            tree = storage.ensure_folder_tree(doc.order.order_number,
                                              [a.service_name_snapshot for a in doc.order.applications]
                                              or ["Payment_Proof"])
            folder_id = tree["order_folder_id"]
            if doc.doc_purpose == "payment_proof":
                folder_id = tree["service_folder_ids"]["__proof__"]
            elif doc.doc_purpose == "output_document":
                folder_id = tree["service_folder_ids"]["__output__"]
            elif doc.application:
                label = doc.application.service_name_snapshot.replace("/", "_").replace("\\", "_")[:80]
                folder_id = tree["service_folder_ids"].get(label) or folder_id

            result = storage.upload_file(local_path, doc.stored_name, doc.mime_type, folder_id)
            doc.storage_provider = result["provider"]
            doc.drive_file_id = result["file_id"]
            doc.web_view_link = result.get("web_view_link")
            doc.upload_status = "uploaded"
            doc.last_error = None
            os.remove(local_path)
            doc.local_staging_rel_path = None
            ok += 1
        except StorageError as exc:
            doc.last_error = str(exc)[:500]
            doc.retry_count += 1
        except Exception as exc:
            doc.last_error = f"unexpected: {type(exc).__name__}"[:500]
            doc.retry_count += 1
    db.session.commit()
    return ok, len(pending) - ok
