"""Health check endpoint for the backend API."""

from __future__ import annotations

import os

from fastapi import APIRouter


router = APIRouter()


def _is_mock() -> bool:
    v = os.getenv("MOCK_MODE")
    return v is not None and v.strip().lower() in ("1", "true", "yes", "on")


@router.get("/health")
def health():
    return {
        "status": "ok",
        "mock_mode": _is_mock(),
        "version": os.getenv("APP_VERSION", "dev"),
    }
