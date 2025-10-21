from fastapi import APIRouter

from backend.services import reconcile


def test_reconcile_exports_router() -> None:
    assert hasattr(reconcile, "router")
    assert isinstance(reconcile.router, APIRouter)
