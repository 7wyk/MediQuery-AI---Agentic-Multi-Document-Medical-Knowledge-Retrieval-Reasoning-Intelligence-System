from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middlewares.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.analytics import (
    ObservabilityOverview,
    ProcessingStatusResponse,
    TopTopics,
    UsageGraphData,
    UsageOverview,
)
from app.services.analytics import (
    get_observability_overview,
    get_processing_status,
    get_top_topics,
    get_usage_graph_data,
    get_usage_overview,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get("/overview", response_model=UsageOverview)
def get_overview(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return get_usage_overview(db, user.id)


@router.get("/usage-graph", response_model=UsageGraphData)
def get_usage_graph(
    period: str = Query(default="daily", pattern="^(daily|weekly)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"data_points": get_usage_graph_data(db, user.id, period), "period": period}


@router.get("/top-topics", response_model=TopTopics)
def get_top_topics_route(
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"topics": get_top_topics(db, user.id, limit)}


@router.get("/observability", response_model=ObservabilityOverview)
def get_observability(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return get_observability_overview(db, user.id)


@router.get("/processing-status", response_model=ProcessingStatusResponse)
def get_processing_status_route(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return get_processing_status(db, user.id)
