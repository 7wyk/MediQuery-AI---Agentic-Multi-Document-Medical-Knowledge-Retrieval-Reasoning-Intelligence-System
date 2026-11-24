"""Document ingestion pipeline: storage -> extraction -> validation -> chunks -> vectors."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.job import DocumentJob
from app.providers.base import ProviderError
from app.providers.registry import get_embedding_provider, get_ocr_provider, get_vision_provider
from app.services.chunking import ChunkingError, build_chunks, estimate_tokens
from app.services.domain_validation import validate_document_text
from app.services.extraction import (
    MIME_BY_TYPE,
    DocumentExtractor,
    ExtractionError,
    detect_file_type,
)
from app.services.graph_rag import delete_document_graph, extract_and_store_graph
from app.services.storage import StorageError, get_storage

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    pass


def _set_progress(
    db: Session,
    document: Document,
    job: Optional[DocumentJob],
    progress: int,
    stage: str,
) -> None:
    document.progress = max(0, min(100, int(progress)))
    document.stage = stage[:120]
    if job is not None:
        job.progress = document.progress
        job.stage = document.stage
    db.commit()


async def process_document(
    db: Session,
    document: Document,
    *,
    job: Optional[DocumentJob] = None,
) -> Document:
    """Run the full ingestion pipeline for one stored document.

    Idempotent: existing chunks and graph data are removed before new content is
    written, so retries and explicit re-index requests never duplicate vectors.
    """
    settings = get_settings()
    document.status = DocumentStatus.PROCESSING.value
    document.error_message = None
    document.rejection_reason = None
    document.processed_at = None
    document.chunk_count = 0
    _set_progress(db, document, job, 5, "downloading")

    try:
        data = await get_storage().download(document.storage_path)
    except StorageError as exc:
        raise IngestionError(f"Stored file could not be read: {exc}") from exc

    if len(data) > settings.max_upload_bytes:
        raise IngestionError("Stored file exceeds the configured upload limit.")

    try:
        file_type = detect_file_type(data, document.filename)
    except ExtractionError as exc:
        raise IngestionError(str(exc)) from exc
    document.mime_type = MIME_BY_TYPE.get(file_type, document.mime_type)

    _set_progress(db, document, job, 20, "validating")
    vision = get_vision_provider()
    ocr = get_ocr_provider()
    extractor = DocumentExtractor(settings, ocr=ocr, vision=vision)

    _set_progress(db, document, job, 35, "extracting")
    try:
        extraction = await extractor.extract(data, file_type, document.filename)
    except ExtractionError as exc:
        raise IngestionError(str(exc)) from exc

    _set_progress(db, document, job, 55, "medical_validation")
    sample = extraction.combined_text[:40000]
    validation = await validate_document_text(sample, settings=settings)
    document.is_medical = 1 if validation.is_medical else 0
    document.domain_confidence = int(round(validation.confidence * 100))

    if not validation.is_medical:
        _clear_document_content(db, document.id)
        document.status = DocumentStatus.REJECTED.value
        document.rejection_reason = validation.rejection_message
        document.error_message = None
        document.progress = 100
        document.stage = "rejected"
        document.processed_at = datetime.now(timezone.utc)
        document.document_metadata = {
            "domain_validation": {
                "method": validation.method,
                "confidence": validation.confidence,
                "categories": validation.categories or [],
            }
        }
        db.commit()
        logger.info("Document %s rejected by medical gatekeeper (%s)", document.id, validation.method)
        return document

    _set_progress(db, document, job, 65, "chunking")
    try:
        drafts = build_chunks(
            extraction.blocks,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            max_chunks=settings.max_chunks_per_document,
        )
    except ChunkingError as exc:
        raise IngestionError(str(exc)) from exc

    # Remove previous vectors/graph data before writing new ones (re-index safe).
    _clear_document_content(db, document.id)
    delete_document_graph(db, document.id)

    _set_progress(db, document, job, 78, "generating_embeddings")
    provider = get_embedding_provider()
    texts = [draft.content for draft in drafts]
    try:
        vectors: List[List[float]] = []
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.extend(await provider.embed_documents(batch))
    except ProviderError as exc:
        raise IngestionError(
            "Embedding service is unavailable, so the document was not indexed: "
            f"{exc}"
        ) from exc

    if len(vectors) != len(texts):
        raise IngestionError("Embedding provider returned an unexpected number of vectors.")

    for index, (draft, vector) in enumerate(zip(drafts, vectors)):
        db.add(
            DocumentChunk(
                document_id=document.id,
                user_id=document.user_id,
                chunk_index=index,
                content=draft.content,
                content_type=draft.content_type,
                page=draft.page,
                section=(draft.section or "")[:512] or None,
                table_id=draft.table_id,
                token_estimate=estimate_tokens(draft.content),
                chunk_metadata=draft.metadata,
                embedding=vector,
            )
        )
    document.chunk_count = len(drafts)
    document.page_count = max(1, extraction.page_count)
    _set_progress(db, document, job, 92, "indexing_knowledge_graph")
    db.commit()

    if settings.enable_graph_rag:
        try:
            await extract_and_store_graph(
                db,
                user_id=document.user_id,
                document_id=document.id,
                text=extraction.combined_text,
                page=extraction.blocks[0].page if extraction.blocks else None,
            )
        except Exception as exc:  # noqa: BLE001 - graph RAG is supplementary
            logger.warning("Knowledge graph extraction skipped: %s", exc)

    document.status = DocumentStatus.COMPLETED.value
    document.progress = 100
    document.stage = "completed"
    document.processed_at = datetime.now(timezone.utc)
    document.document_metadata = {
        "extraction": extraction.metadata,
        "domain_validation": {
            "method": validation.method,
            "confidence": validation.confidence,
            "categories": validation.categories or [],
        },
        "chunk_count": len(drafts),
        "page_count": extraction.page_count,
    }
    db.commit()
    logger.info(
        "Document %s indexed chunks=%s pages=%s", document.id, len(drafts), extraction.page_count
    )
    return document


def _clear_document_content(db: Session, document_id: str) -> None:
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete(
        synchronize_session=False
    )
    db.flush()


def all_graph_and_chunks_deleted(db: Session, document_id: str) -> None:
    """Used by the deletion route."""
    _clear_document_content(db, document_id)
    delete_document_graph(db, document_id)
