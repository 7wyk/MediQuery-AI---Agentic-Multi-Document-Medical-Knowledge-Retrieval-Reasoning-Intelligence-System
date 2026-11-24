from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.middlewares.auth_middleware import require_worker_token
from app.services.jobs import process_pending_jobs_once

router = APIRouter(prefix="/api/v1/internal", tags=["Internal"])


@router.post("/jobs/run", dependencies=[Depends(require_worker_token)])
async def run_jobs(limit: int = Query(default=5, ge=1, le=20)):
    """Process queued document jobs once (Render cron/worker trigger)."""
    processed = await process_pending_jobs_once(limit=limit)
    return {"processed": processed}
