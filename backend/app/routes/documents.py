from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.middlewares.auth_middleware import get_current_user
from app.models.document import Document, DocumentStatus
from app.models.job import DocumentJob
from app.models.user import User
from app.schemas.documents import (
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    UploadRejection,
)
from app.services.extraction import ExtractionError, detect_file_type
from app.services.indexing import all_graph_and_chunks_deleted
from app.services.jobs import enqueue_document_job
from app.services.storage import (
    StorageError,
    build_storage_path,
    get_storage,
    sanitize_filename,
)
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


def _owned_document(db: Session, user: User, doc_id: str) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.user_id == user.id)
        .first()
    )
    if document is None:
        # Same 404 whether it does not exist or belongs to another user.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept multimodal medical documents, store them privately, queue ingestion."""
    settings = get_settings()
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")
    if len(files) > settings.max_files_per_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload at most {settings.max_files_per_request} files per request",
        )

    created: List[Document] = []
    rejected: List[UploadRejection] = []

    for upload in files:
        filename = sanitize_filename(upload.filename or "document")
        try:
            data = await upload.read()
        except Exception:  # noqa: BLE001
            rejected.append(UploadRejection(filename=filename, reason="The file could not be read."))
            continue
        finally:
            await upload.close()

        if not data:
            rejected.append(UploadRejection(filename=filename, reason="The uploaded file is empty."))
            continue
        if len(data) > settings.max_upload_bytes:
            rejected.append(
                UploadRejection(
                    filename=filename,
                    reason=f"File exceeds the {settings.max_upload_mb} MB limit.",
                )
            )
            continue

        try:
            detect_file_type(data, filename)
        except ExtractionError as exc:
            rejected.append(UploadRejection(filename=filename, reason=str(exc)))
            continue

        doc_id = str(uuid.uuid4())
        storage_path = build_storage_path(user.id, doc_id, filename)
        try:
            await get_storage().upload(
                storage_path,
                data,
                upload.content_type or "application/octet-stream",
            )
        except StorageError as exc:
            logger.error("Storage upload failed for %s: %s", filename, exc)
            rejected.append(
                UploadRejection(
                    filename=filename,
                    reason="Document storage is unavailable. Please retry shortly.",
                )
            )
            continue

        document = Document(
            id=doc_id,
            user_id=user.id,
            filename=filename,
            storage_path=storage_path,
            mime_type=upload.content_type,
            file_size=len(data),
            file_hash=hashlib.sha256(data).hexdigest(),
            status=DocumentStatus.QUEUED.value,
            progress=0,
            stage="queued",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        enqueue_document_job(db, document_id=document.id, user_id=user.id)
        created.append(document)

    if not created:
        return DocumentUploadResponse(
            documents=[],
            rejected=rejected,
            message="None of the uploaded files could be accepted.",
        )
    return DocumentUploadResponse(
        documents=[DocumentResponse.model_validate(document, from_attributes=True) for document in created],
        rejected=rejected,
        message=f"Queued {len(created)} document(s) for processing.",
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    documents = (
        db.query(Document)
        .filter(Document.user_id == user.id)
        .order_by(Document.upload_date.desc())
        .all()
    )
    return {"documents": documents, "total": len(documents)}


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _owned_document(db, user, doc_id)


@router.get("/{doc_id}/download", response_model=DocumentDownloadResponse)
async def get_download_url(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _owned_document(db, user, doc_id)
    settings = get_settings()
    url = await get_storage().signed_url(document.storage_path)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Signed download URLs require Supabase Storage.",
        )
    return {"url": url, "expires_in": settings.signed_url_expires_seconds}


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _owned_document(db, user, doc_id)
    storage_path = document.storage_path
    try:
        all_graph_and_chunks_deleted(db, document.id)
        db.query(DocumentJob).filter(DocumentJob.document_id == document.id).delete(
            synchronize_session=False
        )
        db.delete(document)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Document deletion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be deleted. Please retry.",
        )
    try:
        await get_storage().delete(storage_path)
    except StorageError as exc:
        logger.warning("Stored object cleanup failed for %s: %s", storage_path, exc)
    return {"message": "Document deleted successfully", "document_id": doc_id}


@router.post("/{doc_id}/reindex")
def reindex_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _owned_document(db, user, doc_id)
    document.status = DocumentStatus.QUEUED.value
    document.stage = "queued"
    document.progress = 0
    document.error_message = None
    document.rejection_reason = None
    document.processed_at = None
    db.commit()
    enqueue_document_job(db, document_id=document.id, user_id=user.id, force=True)
    return {"message": "Document queued for re-indexing", "document_id": doc_id}
