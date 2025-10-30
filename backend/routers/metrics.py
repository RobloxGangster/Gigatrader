"""Metrics endpoints consumed by the UI."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/summary")
async def summary() -> dict:
    """Return a minimal metrics payload even when live data is unavailable."""

    return {"pnl": 0, "exposure": {}, "counts": {}}
