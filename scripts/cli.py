"""Compatibility shim so tooling can import the Typer app from ``app.cli``."""

from app.cli import app

__all__ = ["app"]
