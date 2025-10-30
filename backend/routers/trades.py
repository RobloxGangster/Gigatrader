"""Trades endpoints for UI compatibility."""

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("")
async def list_trades(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """Return an empty list instead of 404 when no trades exist."""

    return []
