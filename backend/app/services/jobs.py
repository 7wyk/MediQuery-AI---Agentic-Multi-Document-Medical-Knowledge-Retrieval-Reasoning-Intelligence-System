"""Durable, database-backed background job processing.

Jobs live in PostgreSQL, are claimed with ``FOR UPDATE SKIP LOCKED`` on
PostgreSQL, retried with a bounded attempt count, and are safe across process
restarts.  The in-process worker is enabled by default; a dedicated Render
Background Worker can run ``python -m app.worker`` instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.job import DocumentJob, JobStatus
from app.services.indexing import IngestionError, process_document

logger = logging.getLogger(__name__)


def enqueue_document_job(
    db: Session,
    *,
    document_id: str,
    user_id: int,
    job_type: str = "ingest",
    force: bool = False,
) -> DocumentJob:
    """Idempotently enqueue a document job."""
    settings = get_settings()
    existing = (
        db.query(DocumentJob)
        .filter(DocumentJob.document_id == document_id, DocumentJob.job_type == job_type)
        .first()
    )
    if existing is not None:
        if existing.status in {JobStatus.QUEUED, JobStatus.RUNNING} and not force:
            return existing
        existing.status = JobStatus.QUEUED
        existing.attempts = 0
        existing.progress = 0
        existing.stage = "queued"
        existing.error = None
        existing.started_at = None
        existing.finished_at = None
        existing.max_attempts = settings.job_max_attempts
        db.commit()
        return existing

    job = DocumentJob(
        document_id=document_id,
        user_id=user_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        max_attempts=settings.job_max_attempts,
        payload={},
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(DocumentJob)
            .filter(DocumentJob.document_id == document_id, DocumentJob.job_type == job_type)
            .first()
        )
    db.refresh(job)
    return job


def claim_next_job(db: Session, worker_id: str) -> Optional[DocumentJob]:
    query = (
        db.query(DocumentJob)
        .filter(DocumentJob.status == JobStatus.QUEUED)
        .order_by(DocumentJob.created_at.asc())
    )
    try:
        query = query.with_for_update(skip_locked=True)
    except Exception:  # pragma: no cover - dialect without row locking
        pass
    job = query.first()
    if job is None:
        db.rollback()
        return None
    job.status = JobStatus.RUNNING
    job.attempts = int(job.attempts or 0) + 1
    job.worker_id = worker_id
    job.started_at = datetime.now(timezone.utc)
    job.stage = "running"
    db.commit()
    db.refresh(job)
    return job


def recover_stale_jobs(db: Session) -> int:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.job_stale_seconds)
    stale = (
        db.query(DocumentJob)
        .filter(DocumentJob.status == JobStatus.RUNNING, DocumentJob.started_at < cutoff)
        .all()
    )
    for job in stale:
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.error = "Processing timed out"
            job.finished_at = datetime.now(timezone.utc)
            document = db.get(Document, job.document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED.value
                document.error_message = "Processing timed out. Please retry."
                document.stage = "failed"
        else:
            job.status = JobStatus.QUEUED
            job.stage = "queued"
        logger.warning("Recovered stale job %s (attempts=%s)", job.id, job.attempts)
    if stale:
        db.commit()
    return len(stale)


async def run_job(db: Session, job: DocumentJob) -> bool:
    document = db.get(Document, job.document_id)
    if document is None or document.user_id != job.user_id:
        job.status = JobStatus.FAILED
        job.error = "Document no longer exists"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return False

    try:
        await process_document(db, document, job=job)
        if document.status == DocumentStatus.REJECTED.value:
            job.status = JobStatus.SUCCEEDED
            job.stage = "rejected"
        else:
            job.status = JobStatus.SUCCEEDED
            job.stage = "completed"
        job.progress = 100
        job.error = None
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except (IngestionError, Exception) as exc:  # noqa: BLE001 - all failures must persist
        db.rollback()
        # Re-fetch to ensure the session holds a fresh, writable instance.
        job = db.get(DocumentJob, job.id)
        document = db.get(Document, job.document_id) if job else None
        message = str(exc)[:600]
        logger.error("Job %s failed (attempt %s/%s): %s", job.id, job.attempts, job.max_attempts, message)
        if job is None:
            return False
        if job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.stage = "retry_scheduled"
            job.error = message
            if document is not None:
                document.status = DocumentStatus.QUEUED.value
                document.stage = "retry_scheduled"
                document.error_message = message
        else:
            job.status = JobStatus.FAILED
            job.stage = "failed"
            job.error = message
            job.finished_at = datetime.now(timezone.utc)
            if document is not None:
                document.status = DocumentStatus.FAILED.value
                document.stage = "failed"
                document.error_message = message
        db.commit()
        return False


async def process_pending_jobs_once(limit: int = 5, worker_id: Optional[str] = None) -> int:
    """Process up to ``limit`` queued jobs. Used by the external worker endpoint."""
    settings = get_settings()
    worker_id = worker_id or f"worker-{socket.gethostname()}-{os.getpid()}"
    processed = 0
    for _ in range(max(1, limit)):
        with SessionLocal() as db:
            recover_stale_jobs(db)
            job = claim_next_job(db, worker_id)
        if job is None:
            break
        with SessionLocal() as db:
            fresh = db.get(DocumentJob, job.id)
            if fresh is None:
                continue
            await run_job(db, fresh)
        processed += 1
    del settings
    return processed


async def worker_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    worker_id = f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    semaphore = asyncio.Semaphore(max(1, settings.worker_concurrency))
    tasks: set[asyncio.Task] = set()
    logger.info("Background document worker started (%s)", worker_id)

    async def execute(job_id: str) -> None:
        async with semaphore:
            with SessionLocal() as db:
                job = db.get(DocumentJob, job_id)
                if job is not None:
                    await run_job(db, job)

    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                recover_stale_jobs(db)
                job = claim_next_job(db, worker_id)
            if job is None:
                await asyncio.sleep(settings.job_poll_interval_seconds)
                continue
            task = asyncio.create_task(execute(job.id))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            break
        except Exception as exc:  # noqa: BLE001 - loop must survive transient DB errors
            logger.exception("Worker loop error: %s", exc)
            await asyncio.sleep(settings.job_poll_interval_seconds)

    for task in list(tasks):
        task.cancel()
    logger.info("Background document worker stopped (%s)", worker_id)


async def job_status_for_document(db: Session, document_id: str) -> Optional[dict]:
    job = (
        db.query(DocumentJob)
        .filter(DocumentJob.document_id == document_id)
        .order_by(DocumentJob.created_at.desc())
        .first()
    )
    if job is None:
        return None
    return {
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "attempts": job.attempts,
        "error": job.error,
    }
