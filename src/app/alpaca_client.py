from __future__ import annotations

from typing import Any, Optional

from core.config import get_alpaca_settings
from core.utils import ensure_paper_mode

try:  # pragma: no cover - import guard for environments without alpaca-py
    from alpaca.trading.client import TradingClient
except ModuleNotFoundError:  # pragma: no cover - fallback stub to surface friendly error
    TradingClient = None  # type: ignore[assignment]


class MissingCredentialsError(RuntimeError):
    """Raised when Alpaca credentials are absent from the environment."""


def _resolve_credentials() -> tuple[str, str]:
    settings = get_alpaca_settings()
    if not settings.key_id or not settings.secret_key:
        raise MissingCredentialsError(
            "ALPACA_KEY_ID and ALPACA_SECRET_KEY must be set in the environment"
        )
    return settings.key_id, settings.secret_key


def build_trading_client(*, force_paper: Optional[bool] = None) -> Any:
    """Return a configured :class:`TradingClient` respecting paper-first guardrails."""

    if TradingClient is None:  # pragma: no cover - triggered when alpaca-py missing
        raise RuntimeError("alpaca-py is required to build the trading client")

    key, secret = _resolve_credentials()
    mode = ensure_paper_mode(default=True)
    paper = force_paper if force_paper is not None else mode != "live"
    settings = get_alpaca_settings()
    endpoint = settings.paper_endpoint if paper else settings.live_endpoint
    return TradingClient(key, secret, paper=paper, url_override=endpoint)


__all__ = ["build_trading_client", "MissingCredentialsError"]
