from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from backend.services.indicators_service import (
    IndicatorsNotReadyError,
    build_empty_indicators,
    load_indicator_snapshot,
)

router = APIRouter(tags=["indicators"])

log = logging.getLogger(__name__)


@router.get("")
def get_indicators(
    symbol: str = Query(..., min_length=1, description="Ticker symbol to load indicators for"),
    lookback: int = Query(120, gt=0, le=5000, description="Number of bars to include"),
    interval: str = Query("1m", description="Bar interval used for the indicators"),
) -> Dict[str, Any]:
    normalized_symbol = symbol.upper()
    try:
        snapshot = load_indicator_snapshot(normalized_symbol, lookback, interval=interval)
    except IndicatorsNotReadyError as exc:
        log.info(
            "indicators.empty",
            extra={"symbol": normalized_symbol, "reason": str(exc)},
        )
        return build_empty_indicators(normalized_symbol, interval)
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        log.info(
            "indicators.missing_fixture",
            extra={"symbol": normalized_symbol, "error": str(exc)},
        )
        return build_empty_indicators(normalized_symbol, interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not snapshot.get("indicators"):
        log.info(
            "indicators.empty",
            extra={"symbol": normalized_symbol, "reason": "no indicator values"},
        )
        return build_empty_indicators(normalized_symbol, interval)

    snapshot["symbol"] = normalized_symbol
    snapshot.setdefault("interval", interval)
    snapshot.setdefault("has_data", True)
    return snapshot
