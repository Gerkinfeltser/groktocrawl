"""Browser route handlers — manage headless browser sessions."""

import logging

from fastapi import APIRouter

from ..exceptions import BrowserError, NotFoundError
from ..models import (
    BrowserCreateRequest,
    BrowserCreateResponse,
    BrowserDeleteResponse,
    BrowserExecuteRequest,
    BrowserExecuteResponse,
    BrowserListResponse,
)
from ._helpers import _browser_proxy

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v2/browser", response_model=BrowserCreateResponse)
async def create_browser(body: BrowserCreateRequest) -> BrowserCreateResponse:
    result = await _browser_proxy("/browsers", json_data=body.model_dump())
    if not result.get("success"):
        raise BrowserError(
            detail=result.get("detail", result.get("error", "Browser service error"))
        )
    return BrowserCreateResponse(id=result["id"])


@router.post("/v2/browser/{session_id}/execute", response_model=BrowserExecuteResponse)
async def execute_browser(
    session_id: str, body: BrowserExecuteRequest
) -> BrowserExecuteResponse:
    result = await _browser_proxy(
        f"/browsers/{session_id}/execute", json_data=body.model_dump()
    )
    if not result.get("success"):
        raise BrowserError(detail=result.get("error", "Browser execution failed"))
    return BrowserExecuteResponse(success=True, result=result.get("result"))


@router.get("/v2/browser", response_model=BrowserListResponse)
async def list_browsers() -> BrowserListResponse:
    result = await _browser_proxy("/browsers", method="GET")
    return BrowserListResponse(sessions=result.get("sessions", []))


@router.delete("/v2/browser/{session_id}", response_model=BrowserDeleteResponse)
async def destroy_browser(session_id: str) -> BrowserDeleteResponse:
    result = await _browser_proxy(f"/browsers/{session_id}", method="DELETE")
    if not result.get("success"):
        raise NotFoundError(
            detail="Session not found", details={"session_id": session_id}
        )
    return BrowserDeleteResponse(id=session_id)
