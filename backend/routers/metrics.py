"""Compatibility wrapper around the telemetry-related routers."""

from fastapi import APIRouter

from .pnl import router as pnl_router
from .telemetry import router as telemetry_router

router = APIRouter()
router.include_router(pnl_router)
router.include_router(telemetry_router)
