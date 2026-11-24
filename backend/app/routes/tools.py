from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middlewares.auth_middleware import get_current_user
from app.models.user import User
from app.services.observability import request_id_var
from app.services.tools import execute_tool, handle_mcp_request, list_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Tools"])


@router.get("/tools")
def get_tools(user: User = Depends(get_current_user)):
    """List approved external tools (MCP-compatible manifests)."""
    return {"tools": list_tools()}


@router.post("/tools/{tool_name}/execute")
async def run_tool(
    tool_name: str,
    arguments: Dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await execute_tool(
        name=tool_name,
        arguments=arguments,
        db=db,
        user_id=user.id,
        request_id=request_id_var.get() or None,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Tool execution failed"),
        )
    return result


@router.post("/mcp")
async def mcp_endpoint(
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Minimal MCP-style JSON-RPC endpoint for approved medical tools."""
    return await handle_mcp_request(
        payload,
        db=db,
        user_id=user.id,
        request_id=request_id_var.get() or None,
    )
